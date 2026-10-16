/* Reads the numbers out of a Chao Phraya Dam release-plan PDF (the 4-page RID layout:
 * flows/levels summary, inflow at the dam, the plan table, tidal-zone stations) using
 * pdf.js text positions. Works in the browser (window.PlanParser) and in Node (module.exports).
 *
 *   const { data, warnings } = await PlanParser.parse(pdfDocument);   // throws PlanParseError on failure
 */
(function (root) {
  "use strict";

  const TH_M = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];
  const MON = TH_M.map((m) => m.replace(/\./g, "\\.")).join("|");
  const GATE_KEYS = [
    ["manorom", "มโนรมย์"], ["maharaj", "มหาราช"], ["phonlathep", "พลเทพ"], ["boromathat", "บรมธาตุ"],
    ["uthong", "อู่ทอง"], ["krasiao", "กระเสียว"], ["others", "คลองย่อย"],
  ];
  const STATION_CODES = ["C.29B", "C.38", "C.22A", "C.12"];

  class PlanParseError extends Error {}

  // Thai text from pdf.js arrives split into fragments and sometimes with SARA AM decomposed.
  const norm = (s) => s.replace(/\s+/g, "").replace(/ํา/g, "ำ");
  const isInt = (s) => /^\d{1,3}(,\d{3})+$|^\d{1,5}$/.test(s);
  const isLevel = (s) => /^[+\-−]?\d{1,2}\.\d{2}$/.test(s);
  const isTime = (s) => /^\d{1,2}:\d{2}$/.test(s);
  const num = (s) => Number(s.replace(/,/g, "").replace("−", "-"));

  async function readPages(doc) {
    const pages = [];
    for (let n = 1; n <= doc.numPages; n++) {
      const page = await doc.getPage(n);
      const tc = await page.getTextContent();
      const items = tc.items
        .filter((it) => it.str && it.str.trim())
        .map((it) => ({ s: it.str.trim(), x: it.transform[4], y: it.transform[5], w: it.width || 0 }))
        .map((it) => ({ ...it, cx: it.x + it.w / 2 }));
      pages.push({ n, items, lines: groupLines(items), width: page.getViewport({ scale: 1 }).width });
    }
    return pages;
  }

  function groupLines(items, tol = 2.5) {
    const sorted = [...items].sort((a, b) => b.y - a.y);
    const lines = [];
    for (const it of sorted) {
      const last = lines[lines.length - 1];
      if (last && Math.abs(last.y - it.y) <= tol) last.items.push(it);
      else lines.push({ y: it.y, items: [it] });
    }
    for (const l of lines) {
      l.items.sort((a, b) => a.x - b.x);
      l.norm = norm(l.items.map((i) => i.s).join(""));
    }
    return lines;
  }

  const pageText = (p) => p.lines.map((l) => l.norm).join("\n");

  /* x where the right-hand summary panel starts (the "สรุป…" heading), or the page width. */
  function rightEdge(page) {
    for (const l of page.lines) {
      const it = l.items.find((i) => /^สรุป/.test(norm(i.s)));
      if (it) return it.x - 5;
    }
    return page.width;
  }

  /* Groups items by their nearest column; items further than maxFrac of a column gap are dropped. */
  function byColumn(items, cols, maxFrac = 0.75) {
    const gap = (cols[cols.length - 1] - cols[0]) / Math.max(1, cols.length - 1);
    const out = cols.map(() => []);
    for (const it of items) {
      let best = 0;
      cols.forEach((c, k) => { if (Math.abs(it.cx - c) < Math.abs(it.cx - cols[best])) best = k; });
      if (Math.abs(it.cx - cols[best]) <= gap * maxFrac) out[best].push(it);
    }
    return out;
  }

  /* Day-number tokens on a line, each with the month that follows it (if any). */
  function dayTokens(line, xmin = -Infinity, xmax = Infinity) {
    const out = [];
    const its = line.items;
    for (let i = 0; i < its.length; i++) {
      const it = its[i];
      if (it.x < xmin || it.x > xmax || !/^\d{1,2}$/.test(it.s)) continue;
      let tail = "", end = it.x + it.w;
      for (let j = i + 1; j < its.length && j <= i + 5 && tail.length < 6; j++) {
        tail += norm(its[j].s);
        if (new RegExp("^(" + MON + ")$").test(tail)) { end = its[j].x + its[j].w; break; }
      }
      const m = tail.match(new RegExp("^(" + MON + ")"));
      // centre of the whole "dd เดือน" label, which is what chart labels line up with
      out.push({ day: +it.s, mon: m ? TH_M.indexOf(m[1]) : -1, x: m ? (it.x + end) / 2 : it.cx });
    }
    return out;
  }

  /* Rows of the plan table: values mapped onto the date columns. */
  function columnize(items, cols, accept) {
    const gap = cols.length > 1 ? (cols[cols.length - 1] - cols[0]) / (cols.length - 1) : 40;
    const vals = new Array(cols.length).fill(undefined);
    for (const it of items) {
      if (!accept(it)) continue;
      let best = -1, bd = Infinity;
      cols.forEach((c, k) => { const d = Math.abs(it.cx - c); if (d < bd) { bd = d; best = k; } });
      if (bd <= gap * 0.55 && vals[best] === undefined) vals[best] = it;
    }
    return vals;
  }

  function findYear(pages, title) {
    const all = norm(title || "") + "\n" + pages.map(pageText).join("\n");
    const m = all.match(new RegExp("(\\d{1,2})(" + MON + ")(25\\d\\d)"));
    if (m) return +m[3] - 543;
    const y = all.match(/25[6-9]\d/);
    return y ? +y[0] - 543 : null;
  }

  function parseTable(pages) {
    const page = pages.find((p) => /มโนรมย์/.test(pageText(p)) && /แผนการระบายท้ายเขื่อน/.test(pageText(p)));
    if (!page) throw new PlanParseError("ไม่พบหน้าตารางค่ากำหนดการบริหารจัดการน้ำ (แผนระบาย/การผันน้ำราย ปตร.)");

    // date header: the line with the most "dd เดือน" tokens
    let header = null;
    for (const l of page.lines) {
      const t = dayTokens(l).filter((d) => d.mon >= 0);
      if (t.length >= 3 && (!header || t.length > header.tokens.length)) header = { line: l, tokens: t };
    }
    if (!header) throw new PlanParseError("ไม่พบแถววันที่ในตาราง");
    const cols = header.tokens.map((t) => t.x);
    const gap = (cols[cols.length - 1] - cols[0]) / (cols.length - 1);
    const xmin = cols[0] - gap * 0.6, xmax = cols[cols.length - 1] + gap * 0.6;

    const labelFor = (line) => {
      const own = norm(line.items.filter((i) => i.x < xmin).map((i) => i.s).join(""));
      if (own.length > 3) return own;
      const above = page.lines.filter((l) => l.y > line.y && l.y - line.y <= 13)
        .map((l) => norm(l.items.filter((i) => i.x < xmin).map((i) => i.s).join("")))
        .filter((s) => s.length > 3);
      return above.length ? above[above.length - 1] : "";
    };

    const rows = {};
    for (const l of page.lines) {
      if (l === header.line) continue;
      const inside = l.items.filter((i) => i.x >= xmin && i.x <= xmax);
      const timeVals = columnize(inside, cols, (i) => isTime(i.s));
      if (timeVals.every(Boolean)) { rows.rama8t = rows.rama8t || timeVals.map((i) => i.s); continue; }
      const vals = columnize(inside, cols, (i) => isInt(i.s) || isLevel(i.s));
      if (!vals.every(Boolean)) continue;
      const label = labelFor(l);
      const v = vals.map((i) => num(i.s));
      let key = null;
      if (/แผนการระบายท้ายเขื่อน/.test(label)) key = "release";
      else if (/ระดับน้ำเหนือเขื่อน/.test(label)) key = "pool";
      else if (/พระราม8/.test(label)) key = "rama8";
      else if (/การผันน้ำเข้าระบบชลประทาน/.test(label) && !/รายละเอียด/.test(label)) key = "div";
      else {
        const g = GATE_KEYS.find(([, k]) => label.includes(k));
        if (g) key = "gate:" + g[0];
      }
      if (key && !rows[key]) rows[key] = v;
    }

    const text = pageText(page);
    const notes = {};
    const c2 = text.match(new RegExp("C\\.?2นครสวรรค์([\\d,]+)\\((\\d{1,2})(" + MON + ")\\)[^\\d]*?([\\d,]+)(?:[–\\-]([\\d,]+))?"));
    if (c2) Object.assign(notes, { c2Now: num(c2[1]), c2Day: +c2[2], c2Mon: TH_M.indexOf(c2[3]), c2Lo: num(c2[4]), c2Hi: c2[5] ? num(c2[5]) : null });
    const ps = text.match(/ป่าสัก[^\d→]{0,40}?([\d,]+)→([\d,]+)/);
    if (ps) Object.assign(notes, { pasakFrom: num(ps[1]), pasakTo: num(ps[2]) });
    return { header: header.tokens, rows, notes };
  }

  /* The date axis nearest below `below` that matches the plan dates; returns column x per plan date. */
  function axisColumns(page, dates, xmin = -Infinity, xmax = Infinity, below = Infinity) {
    let best = null;
    for (const l of page.lines) {
      if (l.y >= below) continue;
      const toks = dayTokens(l, xmin, xmax);
      if (toks.length < dates.length) continue;
      // carry the month forward and look for the plan's first date
      let mon = -1;
      for (const t of toks) { if (t.mon >= 0) mon = t.mon; else t.mon = mon; }
      const start = toks.findIndex((t) => t.day === dates[0].day && (t.mon < 0 || t.mon === dates[0].mon));
      if (start < 0 || start + dates.length > toks.length) continue;
      const seq = toks.slice(start, start + dates.length);
      if (!seq.every((t, k) => t.day === dates[k].day)) continue;
      if (!best || l.y > best.y) best = { y: l.y, cols: seq.map((t) => t.x) };
    }
    return best;
  }

  function parseInflow(pages, dates, div) {
    const page = pages.find((p) => /ปริมาณน้ำไหลมาถึงหน้าเขื่อน/.test(pageText(p)));
    if (!page) return null;
    const right = rightEdge(page);
    const axis = axisColumns(page, dates, -Infinity, right);
    if (!axis) return null;
    const arrive = [], net = [];
    // chart area: below the "อัตราการไหล" heading when present; flow labels always carry a thousands comma
    const head = page.lines.find((l) => /^อัตราการไหล/.test(l.norm));
    const top = head ? head.y : Infinity;
    const items = page.lines.filter((l) => l.y > axis.y && l.y < top).flatMap((l) => l.items).filter((i) => i.x < right);
    const groups = byColumn(items.filter((i) => /^\d{1,3}(,\d{3})+$/.test(i.s)), axis.cols);
    for (let k = 0; k < dates.length; k++) {
      const near = groups[k].map((i) => num(i.s));
      if (!near.length) return null;
      const a = Math.max(...near);
      arrive.push(a);
      const n = near.filter((v) => v !== a);
      net.push(n.length ? Math.max(...n) : a - div[k]);
    }
    return { arrive, net };
  }

  function parseTide(pages, dates) {
    const page = pages.find((p) => /สันดอน/.test(pageText(p)) && /สะพานพระราม8และสันดอน/.test(pageText(p)));
    if (!page) return null;
    const title = page.lines.find((l) => /สะพานพระราม8และสันดอน/.test(l.norm));
    const right = rightEdge(page);
    const axis = axisColumns(page, dates, -Infinity, right, title.y);
    if (!axis) return null;
    const tide = [];
    for (const l of page.lines) l.items.forEach((it, i) => { it.plus = i > 0 && l.items[i - 1].s === "+"; });
    const items = page.lines.filter((l) => l.y > axis.y && l.y < title.y).flatMap((l) => l.items)
      .filter((i) => i.x < right && isLevel(i.s) && !i.plus && !/^[+]/.test(i.s));
    const groups = byColumn(items, axis.cols);
    for (let k = 0; k < dates.length; k++) {
      const near = groups[k];
      if (near.length < 2) return null; // Rama 8 + tide labels per column
      tide.push(num(near.reduce((a, b) => (b.y < a.y ? b : a)).s));
    }
    return tide;
  }

  function parseStations(pages, dates) {
    const page = pages.find((p) => /เขตน้ำขึ้นลง/.test(pageText(p)) && /C\.?29B/.test(pageText(p)));
    if (!page) return null;
    const right = rightEdge(page);
    for (const l of page.lines) l.items.forEach((it, i) => { it.plus = i > 0 && l.items[i - 1].s === "+"; });

    // panel titles: lines with a station code followed by "สูงสุด"
    const panels = [];
    for (const l of page.lines) {
      if (!/สูงสุด/.test(l.norm)) continue;
      const its = l.items.filter((i) => i.x < right);
      for (let i = 0; i < its.length; i++) {
        if (!/^C\.?$/.test(its[i].s) && !/^C\.\d/.test(its[i].s)) continue;
        let code = its[i].s;
        for (let j = i + 1; j < its.length && j <= i + 2 && /^[0-9A-Z]{1,3}$/.test(its[j].s.split(/\s/)[0]); j++) code += its[j].s.split(/\s/)[0];
        code = code.replace(/^C\.?/, "C.");
        if (STATION_CODES.includes(code)) panels.push({ code, x: its[i].x, y: l.y, line: l });
      }
    }
    const out = {};
    for (const p of panels) {
      const sameRow = panels.filter((q) => Math.abs(q.y - p.y) < 3 && q.x > p.x).sort((a, b) => a.x - b.x);
      const x0 = p.x - 35, x1 = sameRow.length ? sameRow[0].x - 35 : right;
      const axis = axisColumns(page, dates, x0, x1, p.y);
      if (!axis) continue;
      const lines = page.lines.filter((l) => l.y > axis.y && l.y < p.y);
      const items = lines.flatMap((l) => l.items).filter((i) => i.x >= x0 && i.x < x1 && isLevel(i.s) && !i.plus);
      const lv = [];
      const groups = byColumn(items, axis.cols);
      for (let k = 0; k < dates.length; k++) {
        const near = groups[k];
        if (near.length !== 1) { lv.length = 0; break; }
        lv.push(num(near[0].s));
      }
      if (lv.length !== dates.length) continue;
      const bankLine = [p.line, ...lines].map((l) => norm(l.items.filter((i) => i.x >= x0 && i.x < x1).map((i) => i.s).join(""))).join("");
      const bank = bankLine.match(/ตลิ่ง\+(\d\.\d{2})/);
      out[p.code] = { lv, bank: bank ? +bank[1] : null };
    }
    return out;
  }

  function thresholds(pages) {
    const t = pages.map(pageText).join("\n");
    const f = (re) => { const m = t.match(re); return m ? +m[1] : null; };
    return {
      poolMax: f(/สูงสุดที่ยอมรับ\+?(1\d\.\d{1,2})/) ?? f(/สูงสุด\+(1\d\.\d{2})/),
      poolCtrl: f(/ควบคุม\+?(1\d\.\d{1,2})/),
      poolTgt: f(/เป้าหมาย\+?(1\d\.\d{1,2})/),
      r8Warn: f(/เตือนภัย\+?(\d\.\d{2})/),
      r8Bank: f(/ตลิ่งวิกฤต(?:พระราม8)?\+?(\d\.\d{2})/),
    };
  }

  function stamp(pages, title) {
    const t = norm(title || "") + pages.map(pageText).join("\n");
    const m = t.match(new RegExp("ข้อมูลณ(\\d{1,2})(" + MON + ")(25\\d\\d)·?(\\d{1,2}:\\d{2})"));
    return m ? `ข้อมูล ณ ${m[1]} ${m[2]} ${m[3]} · ${m[4]} น.` : null;
  }

  const iso = (y, m, d) => `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;

  async function parse(doc) {
    let title = "";
    try { title = ((await doc.getMetadata()).info || {}).Title || ""; } catch (e) { /* no metadata */ }
    const pages = await readPages(doc);
    const warnings = [];

    const table = parseTable(pages);
    const year = findYear(pages, title);
    if (!year) throw new PlanParseError("ไม่พบปี พ.ศ. ในเอกสาร");
    // plan dates with month/year roll-over
    let y = year, prevMon = -1;
    const dates = table.header.map((t) => {
      const mon = t.mon;
      if (prevMon >= 0 && mon < prevMon) y += 1;
      prevMon = mon;
      return { day: t.day, mon, iso: iso(y, mon, t.day) };
    });
    const N = dates.length;
    const r = table.rows;
    for (const [k, name] of [["release", "แผนระบายท้ายเขื่อน"], ["pool", "ระดับน้ำเหนือเขื่อน"], ["rama8", "ระดับสูงสุดสะพานพระราม 8"], ["div", "การผันน้ำเข้าระบบชลประทานรวม"]]) {
      if (!r[k]) throw new PlanParseError(`อ่านแถว “${name}” ในตารางไม่ได้`);
    }
    const gates = GATE_KEYS.map(([id]) => ({ id, q: r["gate:" + id] || null }));
    const missingGates = gates.filter((g) => !g.q).map((g) => g.id);
    if (missingGates.length) warnings.push("อ่านค่ารับน้ำบาง ปตร. ไม่ได้: " + missingGates.join(", "));
    const gateSum = r.div.map((_, k) => gates.reduce((s, g) => s + (g.q ? g.q[k] : 0), 0));
    if (!missingGates.length && gateSum.some((s, k) => Math.abs(s - r.div[k]) > 1)) warnings.push("ผลรวมราย ปตร. ไม่ตรงกับยอดผันน้ำรวมบางวัน");

    const inflow = parseInflow(pages, dates, r.div);
    if (!inflow) throw new PlanParseError("อ่านค่าน้ำไหลมาถึงหน้าเขื่อน (หน้ากราฟอัตราการไหล) ไม่ได้");
    inflow.net.forEach((v, k) => {
      if (Math.abs(inflow.arrive[k] - r.div[k] - v) > 3) warnings.push(`น้ำสุทธิวันที่ ${dates[k].day} ไม่เท่ากับ มาถึง − ผันน้ำ`);
    });

    const tide = parseTide(pages, dates);
    if (!tide) throw new PlanParseError("อ่านระดับน้ำขึ้นสูงสุดที่สันดอนไม่ได้");

    const st = parseStations(pages, dates);
    const stations = STATION_CODES.map((code) => ({ code, lv: st && st[code] ? st[code].lv : null, bank: st && st[code] ? st[code].bank : null }));
    const missingSt = stations.filter((s) => !s.lv).map((s) => s.code);
    if (missingSt.length) throw new PlanParseError("อ่านระดับน้ำสถานี " + missingSt.join(", ") + " ไม่ได้");

    if (!r.rama8t) warnings.push("ไม่พบเวลาที่เกิดระดับสูงสุดที่พระราม 8");
    const data = {
      version: 1,
      source: { title: title || null, stamp: stamp(pages, title) },
      dates: dates.map((d) => d.iso),
      release: r.release, arrive: inflow.arrive, net: inflow.net, div: r.div,
      pool: r.pool, rama8: r.rama8, rama8t: r.rama8t || null, tide,
      gates, stations, thresholds: thresholds(pages), notes: table.notes,
    };
    validate(data);
    if (data.notes.c2Now == null) warnings.push("ไม่พบข้อมูลประกอบ C.2 นครสวรรค์");
    if (data.notes.pasakFrom == null) warnings.push("ไม่พบอัตราการไหลแม่น้ำป่าสัก");
    return { data, warnings };
  }

  /* Plausibility checks shared by the parser and the page. Throws PlanParseError. */
  function validate(d) {
    const N = Array.isArray(d.dates) ? d.dates.length : 0;
    if (N < 2 || N > 31) throw new PlanParseError("จำนวนวันในแผนไม่ถูกต้อง");
    const arr = (a, lo, hi, name) => {
      if (!Array.isArray(a) || a.length !== N || !a.every((v) => typeof v === "number" && isFinite(v) && v >= lo && v <= hi)) {
        throw new PlanParseError(`ค่า “${name}” ไม่อยู่ในช่วงที่เป็นไปได้`);
      }
    };
    arr(d.release, 0, 10000, "แผนระบาย"); arr(d.arrive, 0, 15000, "น้ำไหลมาถึง"); arr(d.net, 0, 15000, "น้ำไหลเข้าสุทธิ");
    arr(d.div, 0, 3000, "การผันน้ำ"); arr(d.pool, 10, 20, "ระดับเหนือเขื่อน"); arr(d.rama8, -2, 6, "พระราม 8"); arr(d.tide, -3, 5, "สันดอน");
    (d.stations || []).forEach((s) => arr(s.lv, -2, 8, s.code));
    (d.gates || []).forEach((g) => g.q && arr(g.q, 0, 3000, g.id));
    if (!d.dates.every((s) => /^\d{4}-\d{2}-\d{2}$/.test(s))) throw new PlanParseError("รูปแบบวันที่ไม่ถูกต้อง");
    return true;
  }

  const api = { parse, validate, PlanParseError, TH_M, _internal: { readPages, parseTable, axisColumns, dayTokens, parseInflow } };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PlanParser = api;
})(typeof self !== "undefined" ? self : this);
