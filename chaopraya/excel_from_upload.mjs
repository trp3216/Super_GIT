// แปลงเอกสาร uploads/<id> จากหน้าอัปโหลด Excel (https://claude.ai/artifact/JXN1yqQcidVk8sTM5JPBDZ)
// ที่บันทึกเป็น JSON (ArtifactData get + out_dir) ให้เป็น excel_daily.csv แทนการรัน import_excel.py
//
// ใช้: node chaopraya/excel_from_upload.mjs <upload.json> [out.csv]
import fs from "node:fs";

const [src, outPath = "chaopraya/excel_daily.csv"] = process.argv.slice(2);
if (!src) {
  console.error("usage: node excel_from_upload.mjs <upload.json> [out.csv]");
  process.exit(1);
}

const COLS = [
  "c2_cms", "head_level_m", "tail_level_m", "release_cms",
  "borommathat_cms", "phonlathep_cms", "mo_cms", "manorom_cms", "maharaj_cms",
  "borommathat_up_m", "phonlathep_up_m", "mo_up_m", "manorom_up_m", "maharaj_up_m",
];

const doc = JSON.parse(fs.readFileSync(src, "utf8"));
const data = doc.data ?? doc;
// ข้อมูลมาจากหน้าเว็บ: รับเฉพาะวันที่รูปแบบ YYYY-MM-DD และตัวเลขจริง
const rows = (Array.isArray(data.rows) ? data.rows : [])
  .filter((r) => r && /^\d{4}-\d{2}-\d{2}$/.test(r.date))
  .map((r) => [r.date, ...COLS.map((c) => (typeof r[c] === "number" && Number.isFinite(r[c]) ? r[c] : ""))])
  .sort((a, b) => a[0].localeCompare(b[0]));
if (!rows.length) {
  console.error("no valid rows in upload");
  process.exit(1);
}

fs.writeFileSync(outPath, [["date", ...COLS].join(","), ...rows.map((r) => r.join(","))].join("\n") + "\n");
console.log(`${rows.length} rows (${rows[0][0]} -> ${rows.at(-1)[0]}) -> ${outPath}`);
