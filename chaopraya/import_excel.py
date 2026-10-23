# แปลงไฟล์ Excel "ฐานข้อมูลจัดสรรน้ำปี" (ชีตแรก) เป็น excel_daily.csv
# ให้ extract_timeseries.mjs ใช้เติมข้อมูลคลองรับน้ำ 5 สาย และวันก่อนรายงานเริ่ม (ตั้งแต่ 1 พ.ค.)
#
# ใช้: python3 -I chaopraya/import_excel.py <file.xlsx> [out.csv]
import csv
import datetime
import sys

import openpyxl

# index คอลัมน์ (0-based) ตามหัวตารางของชีต: กลุ่มละ 4 คอลัมน์ เหนือ / ท้าย / ระบาย / ใช้จริง
COLUMNS = {
    "c2_cms": 3,  # นครสวรรค์ ระบาย
    "head_level_m": 9,  # เขื่อนเจ้าพระยา เหนือ
    "tail_level_m": 10,  # เขื่อนเจ้าพระยา ท้าย
    "release_cms": 11,  # เขื่อนเจ้าพระยา ระบาย
    "borommathat_cms": 19,
    "phonlathep_cms": 61,
    "mo_cms": 101,  # มะขามเฒ่า-อู่ทอง
    "manorom_cms": 145,
    "maharaj_cms": 151,
    "borommathat_up_m": 17,
    "phonlathep_up_m": 59,
    "mo_up_m": 99,
    "manorom_up_m": 143,
    "maharaj_up_m": 149,
}


def num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 3)
    return None  # ช่องว่างหรือข้อความเสีย (เช่น ".3.78")


def main(src, out="chaopraya/excel_daily.csv"):
    ws = openpyxl.load_workbook(src, data_only=True, read_only=True).worksheets[0]
    rows = []
    for r in ws.iter_rows(min_row=5, values_only=True):
        if not isinstance(r[0], datetime.datetime):
            continue  # แถวสรุปที่ไม่มีวันที่
        row = {"date": r[0].date().isoformat()}
        row.update({k: num(r[i]) if i < len(r) else None for k, i in COLUMNS.items()})
        rows.append(row)
    # ตัดวันท้ายตารางที่ยังไม่มีข้อมูล
    while rows and not rows[-1]["c2_cms"]:
        rows.pop()
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", *COLUMNS])
        w.writeheader()
        for row in rows:
            w.writerow({k: "" if v is None else v for k, v in row.items()})
    print(f"{len(rows)} rows ({rows[0]['date']} -> {rows[-1]['date']}) -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
