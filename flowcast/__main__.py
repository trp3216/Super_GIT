import argparse
import json
from pathlib import Path

from .data import load_excel
from .excel import build_workbook
from .model import TARGETS, TRAIN_START, forecast, train


def main():
    p = argparse.ArgumentParser(description="พยากรณ์ C.2 นครสวรรค์ และการระบายเขื่อนเจ้าพระยา ล่วงหน้า 1–3 วัน")
    p.add_argument("--excel", required=True, help="ไฟล์ฐานข้อมูลจัดสรรน้ำ (.xlsx)")
    p.add_argument("--out", default="outputs", help="โฟลเดอร์ผลลัพธ์")
    p.add_argument("--start", default=TRAIN_START, help="วันเริ่มต้นข้อมูลที่ใช้ฝึก (ต้องมีข้อมูล C.2)")
    args = p.parse_args()

    df = load_excel(args.excel)
    model, backtests = train(df, args.start)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "flowcast_model.json").write_text(json.dumps(model, ensure_ascii=False, indent=1))
    xlsx = out / "chaophraya_forecast.xlsx"
    build_workbook(df, model, backtests, xlsx)

    print("ความแม่นยำ (ทดสอบแบบเว้นทีละปี, คลาดเฉลี่ย ลบ.ม./วิ):")
    for m in model["metrics"]:
        print(f"  {TARGETS[m['target']]:<26} +{m['h']} วัน  แบบจำลอง {m['mae']:>6.1f}  ไม่ใช้แบบจำลอง {m['mae_persist']:>6.1f}")
    t, fc = forecast(model, df)
    print(f"\nพยากรณ์จากข้อมูลวันที่ {t.date()}:")
    for date, r in fc.iterrows():
        print(f"  {date.date()}  C.2 {r.c2_q:>6,.0f} ({r.c2_q_low:,.0f}–{r.c2_q_high:,.0f})"
              f"  ระบาย {r.out_q:>6,.0f} ({r.out_q_low:,.0f}–{r.out_q_high:,.0f})  ท้ายเขื่อน {r.dn_h:.2f} ม.รทก.")
    print(f"\nบันทึก {xlsx}")


if __name__ == "__main__":
    main()
