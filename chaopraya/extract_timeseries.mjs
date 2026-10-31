// ดึงข้อมูลรายวันจากรายงานของ chaopraya-c2forecast (src/data/reports/YYYY-MM-DD.js)
// แล้วรวมเป็นอนุกรมเวลา 1 แถวต่อรายงาน (ค่า 06:00 น.) → CSV
//
// Ct.19 ไม่มีเป็นฟิลด์ในรายงาน (มีแต่ในข้อความ ตั้งแต่ 20 ก.ย.) จึงอ่านค่า 06:00 น. ด้วยมือไว้ใน ct19_0600.csv
// ข้างสคริปต์นี้ แล้วนำมาเติมเป็นคอลัมน์ ct19_cms
// คลองรับน้ำฝั่งตะวันตก (พลเทพ, บรมธาตุ, มอ.) และฝั่งตะวันออก (มโนรมย์, มหาราช) ก็มีแต่ในข้อความ
// (21 ก.ย. – 20 ต.ค.) จึงอ่านด้วย regex จากรายการแยกคลอง; ค่าคลองที่กระจายอยู่วันอื่น (ก.ค., 21-22 ต.ค.)
// อ่านด้วยมือไว้ใน canals_extra.csv และเติมเฉพาะช่องที่ว่าง
// excel_daily.csv (จาก import_excel.py) เป็นแหล่งหลักของ C.2, ระดับเหนือ/ท้ายเขื่อน, ระบาย C.13, คลอง และระดับเหนือ ปตร.
// (DF คำนวณใหม่จาก Excel); รายงานใช้เฉพาะช่องที่ Excel ไม่มี และค่าที่ Excel ไม่มีเลย (N.67, P.17, Ct.19, Sideflow ฯลฯ)
// overrides.csv: ค่าที่ผู้ใช้ยืนยันเอง ใช้ทับทุกแหล่งเป็นขั้นสุดท้าย (DF คำนวณใหม่ถ้าแก้ระดับ)
//
// ถ้าไม่มี <reports_dir> (เช่น clone repo รายงานไม่ได้) จะใช้ c13_timeseries.csv เดิมเป็นฐานของค่าที่มาจากรายงาน
// แล้วทับด้วย Excel — วันที่ใหม่กว่า CSV เดิมจะมีเฉพาะค่าจาก Excel จนกว่ารันกับ repo จริงอีกครั้ง
//
// ใช้: node chaopraya/extract_timeseries.mjs <reports_dir> [out.csv]
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [reportsDir, outPath = "chaopraya/c13_timeseries.csv"] = process.argv.slice(2);
if (!reportsDir) {
  console.error("usage: node extract_timeseries.mjs <reports_dir> [out.csv]");
  process.exit(1);
}

const DAMS = { "ภูมิพล": "bhumibol_mcm", "สิริกิติ์": "sirikit_mcm", "แควน้อยฯ": "kwaenoi_mcm", "ป่าสักฯ": "pasak_mcm" };

const columns = [
  "date", "c2_cms", "n67_cms", "p17_cms", "ct19_cms",
  "head_level_m", "tail_level_m", "df_m", "release_cms",
  "sideflow_cms", "intake_cms", "phonlathep_cms", "borommathat_cms", "mo_cms", "manorom_cms", "maharaj_cms",
  "phonlathep_up_m", "borommathat_up_m", "mo_up_m", "manorom_up_m", "maharaj_up_m",
  ...Object.values(DAMS),
];

const ct19Path = new URL("./ct19_0600.csv", import.meta.url);
const ct19 = fs.existsSync(ct19Path)
  ? Object.fromEntries(fs.readFileSync(ct19Path, "utf8").trim().split("\n").slice(1).map((l) => {
      const [d, v] = l.split(",");
      return [d, Number(v)];
    }))
  : {};

// รายการแยกคลองฝั่งตะวันตกในข้อความรายงาน มี 2 รูปแบบ:
//   "มอ. 25.73, มก. 10.43, พลเทพ 60.16 ..., บรมธาตุ 90.85"  (ถึง 9 ต.ค.)
//   "(บรมธาตุ 90.83, พลเทพ 50.12, มอ 10.91, ..."           (ตั้งแต่ 10 ต.ค.)
const N = String.raw`([\d.]+)`;
const CANAL_A = new RegExp(String.raw`มอ\.? ${N}, มก\.? ${N}, พลเทพ ${N}[^,]*, บรมธาตุ ${N}`);
const CANAL_B = new RegExp(String.raw`\(บรมธาตุ ${N}[^,]*, พลเทพ ${N}[^,]*, มอ\.? ${N}`);
// ฝั่งตะวันออก: "ตะวันออก 231.35 (มโนรมย์ 180.65 ..., มหาราช 49.70"
const CANAL_EAST = new RegExp(String.raw`ตะวันออก [\d.,]+ \(มโนรมย์ ${N}[^,]*, มหาราช ${N}`);
const canals = (text) => {
  const out = {};
  const a = text.match(CANAL_A), b = text.match(CANAL_B), e = text.match(CANAL_EAST);
  if (a) Object.assign(out, { mo_cms: +a[1], phonlathep_cms: +a[3], borommathat_cms: +a[4] });
  else if (b) Object.assign(out, { borommathat_cms: +b[1], phonlathep_cms: +b[2], mo_cms: +b[3] });
  if (e) Object.assign(out, { manorom_cms: +e[1], maharaj_cms: +e[2] });
  return out;
};

const extraPath = new URL("./canals_extra.csv", import.meta.url);
const extra = {};
if (fs.existsSync(extraPath)) {
  for (const l of fs.readFileSync(extraPath, "utf8").trim().split("\n").slice(1)) {
    const [d, col, v] = l.split(",");
    (extra[d] ??= {})[col] = Number(v);
  }
}

const excelPath = new URL("./excel_daily.csv", import.meta.url);
const excel = {};
if (fs.existsSync(excelPath)) {
  const [head, ...lines] = fs.readFileSync(excelPath, "utf8").trim().split(/\r?\n/);
  const cols = head.split(",");
  for (const l of lines) {
    const cells = l.split(",");
    excel[cells[0]] = Object.fromEntries(cols.slice(1).map((c, i) => [c, cells[i + 1] === "" ? null : Number(cells[i + 1])]));
  }
}
const EXCEL_COLS = Object.keys(Object.values(excel)[0] ?? {}).filter((c) => columns.includes(c));
const withExcel = (row) => {
  const x = excel[row.date];
  if (!x) return row;
  for (const col of EXCEL_COLS) if (x[col] != null) row[col] = x[col];
  if (x.head_level_m != null && x.tail_level_m != null) row.df_m = Math.round((row.head_level_m - row.tail_level_m) * 100) / 100;
  return row;
};

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

const rows = [];
const fallback = !fs.existsSync(reportsDir);
if (fallback) {
  console.warn(`WARNING: ${reportsDir} not found — using previous ${outPath} for report-only columns`);
  const [head, ...lines] = fs.readFileSync(outPath, "utf8").trim().split(/\r?\n/);
  const cols = head.split(",");
  for (const l of lines) {
    const cells = l.split(",");
    const row = Object.fromEntries(cols.map((c, i) => [c, i === 0 ? cells[0] : cells[i] === "" ? null : Number(cells[i])]));
    rows.push(withExcel(row));
  }
}
const files = fallback ? [] : fs.readdirSync(reportsDir).filter((f) => /^\d{4}-\d{2}-\d{2}\.js$/.test(f)).sort();
for (const f of files) {
  const file = path.resolve(reportsDir, f);
  const r = (await import(pathToFileURL(file).href)).default;
  const canal = canals(fs.readFileSync(file, "utf8"));
  const last = (r.stationHistory ?? []).at(-1) ?? {};
  const c13 = r.c13Status ?? {};
  const bal = c13.balanceBreakdown ?? {};
  const row = {
    date: r.id ?? f.slice(0, 10),
    c2_cms: num(r.reportMeta?.latestReading?.C2) ?? num(last.C2),
    n67_cms: num(last.N67),
    p17_cms: num(last.P17),
    ct19_cms: num(ct19[r.id ?? f.slice(0, 10)]),
    head_level_m: num(c13.headLevel) ?? num(last.headC13),
    tail_level_m: num(c13.tailLevel) ?? num(last.tailC13),
    df_m: num(c13.df),
    // ระบายจริง 06:00 น. จาก balance; ถ้าไม่มี ใช้ค่าในตารางสถานี
    release_cms: num(bal.discharge) != null ? Math.abs(bal.discharge) : num(last.releaseC13),
    sideflow_cms: num(bal.sideflow),
    intake_cms: num(bal.intake) != null ? Math.abs(bal.intake) : null,
    phonlathep_cms: num(canal.phonlathep_cms),
    borommathat_cms: num(canal.borommathat_cms),
    mo_cms: num(canal.mo_cms),
    manorom_cms: num(canal.manorom_cms),
    maharaj_cms: num(canal.maharaj_cms),
  };
  withExcel(row);
  for (const [col, v] of Object.entries(extra[row.date] ?? {})) row[col] ??= num(v);
  for (const col of Object.values(DAMS)) row[col] = null;
  for (const d of r.damReleases?.rows ?? []) {
    if (DAMS[d.dam]) row[DAMS[d.dam]] = num(d.actualMcm);
  }
  rows.push(row);
}

// วันที่มีแต่ใน Excel (ก่อนรายงานเริ่ม)
const have = new Set(rows.map((r) => r.date));
for (const [date, x] of Object.entries(excel)) {
  if (have.has(date)) continue;
  rows.push(withExcel({ date }));
}
rows.sort((a, b) => a.date.localeCompare(b.date));

const overridePath = new URL("./overrides.csv", import.meta.url);
if (fs.existsSync(overridePath)) {
  const byDate = Object.fromEntries(rows.map((r) => [r.date, r]));
  for (const l of fs.readFileSync(overridePath, "utf8").trim().split(/\r?\n/).slice(1)) {
    const [d, col, v] = l.split(",");
    const row = byDate[d];
    if (!row || !columns.includes(col) || !Number.isFinite(Number(v))) continue;
    row[col] = Number(v);
    if ((col === "head_level_m" || col === "tail_level_m") && row.head_level_m != null && row.tail_level_m != null) {
      row.df_m = Math.round((row.head_level_m - row.tail_level_m) * 100) / 100;
    }
  }
}

const csv = [columns.join(","), ...rows.map((row) => columns.map((c) => row[c] ?? "").join(","))].join("\n") + "\n";
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, csv);
console.log(`${rows.length} rows (${rows[0]?.date} → ${rows.at(-1)?.date}) → ${outPath}`);
