// ดึงข้อมูลรายวันจากรายงานของ chaopraya-c2forecast (src/data/reports/YYYY-MM-DD.js)
// แล้วรวมเป็นอนุกรมเวลา 1 แถวต่อรายงาน (ค่า 06:00 น.) → CSV
//
// Ct.19 ไม่มีเป็นฟิลด์ในรายงาน (มีแต่ในข้อความ ตั้งแต่ 20 ก.ย.) จึงอ่านค่า 06:00 น. ด้วยมือไว้ใน ct19_0600.csv
// ข้างสคริปต์นี้ แล้วนำมาเติมเป็นคอลัมน์ ct19_cms
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
  "sideflow_cms", "intake_cms",
  ...Object.values(DAMS),
];

const ct19Path = new URL("./ct19_0600.csv", import.meta.url);
const ct19 = fs.existsSync(ct19Path)
  ? Object.fromEntries(fs.readFileSync(ct19Path, "utf8").trim().split("\n").slice(1).map((l) => {
      const [d, v] = l.split(",");
      return [d, Number(v)];
    }))
  : {};

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

const files = fs.readdirSync(reportsDir).filter((f) => /^\d{4}-\d{2}-\d{2}\.js$/.test(f)).sort();
const rows = [];
for (const f of files) {
  const r = (await import(pathToFileURL(path.resolve(reportsDir, f)).href)).default;
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
  };
  for (const col of Object.values(DAMS)) row[col] = null;
  for (const d of r.damReleases?.rows ?? []) {
    if (DAMS[d.dam]) row[DAMS[d.dam]] = num(d.actualMcm);
  }
  rows.push(row);
}

const csv = [columns.join(","), ...rows.map((row) => columns.map((c) => row[c] ?? "").join(","))].join("\n") + "\n";
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, csv);
console.log(`${rows.length} rows (${rows[0]?.date} → ${rows.at(-1)?.date}) → ${outPath}`);
