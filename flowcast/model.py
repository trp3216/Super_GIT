"""แบบจำลองสมการเชิงเส้นพยากรณ์ล่วงหน้า 1–3 วัน

ใช้สมการเชิงเส้นเพราะเปิดดูค่าสัมประสิทธิ์และคำนวณซ้ำใน Excel ได้ตรงๆ
ผลทดสอบแบบเว้นทีละปีไม่ต่างจากการแยกช่วงน้ำมาก/น้อย หรือการแปลงค่าเป็น log อย่างมีนัยสำคัญ
"""
import numpy as np
import pandas as pd

# (คอลัมน์, ย้อนหลังกี่วัน)
FEATURES = [
    ("c2_q", 0), ("c2_q", 1), ("c2_q", 3),
    ("out_q", 0), ("out_q", 1), ("out_q", 3),
    ("up_h", 0), ("up_h", 1),
    ("ct19_q", 0), ("ct19_q", 1),
]
FEATURE_LABELS = {
    "c2_q": "C.2 นครสวรรค์ ปริมาณน้ำ (ลบ.ม./วิ)",
    "out_q": "ระบายท้ายเขื่อนเจ้าพระยา (ลบ.ม./วิ)",
    "up_h": "ระดับน้ำเหนือเขื่อน (ม.รทก.)",
    "ct19_q": "Ct.19 สะแกกรัง ปริมาณน้ำ (ลบ.ม./วิ)",
}
TARGETS = {"c2_q": "C.2 นครสวรรค์", "out_q": "ระบายท้ายเขื่อนเจ้าพระยา"}
HORIZONS = (1, 2, 3)
# ช่วงความคลาดเคลื่อนแยกตามปริมาณน้ำวันปัจจุบัน (ลบ.ม./วิ)
BANDS = [0, 500, 1500]
QUANTILES = (0.1, 0.9)
TRAIN_START = "2020-01-01"


def feature_name(col, lag):
    return f"{col}[t]" if lag == 0 else f"{col}[t-{lag}]"


def features(df):
    src = df.assign(ct19_q=df["ct19_q"].fillna(0))
    return pd.DataFrame({feature_name(c, k): src[c].shift(k) for c, k in FEATURES})


def fit_linear(X, y):
    A = np.c_[np.ones(len(X)), X]
    return np.linalg.lstsq(A, y, rcond=None)[0]


def predict_linear(coef, X):
    return np.clip(np.c_[np.ones(len(X)), X] @ coef, 0, None)


def band_index(value):
    return int(np.searchsorted(BANDS, value, side="right") - 1)


def _dataset(df, target, h):
    X = features(df)
    Z = X.assign(y=df[target].shift(-h), cur=df[target]).dropna()
    return Z[list(X.columns)], Z["y"], Z["cur"]


def backtest(df, target, h):
    """ทดสอบแบบเว้นทีละปี: ฝึกด้วยปีอื่นทั้งหมด แล้วพยากรณ์ปีที่เว้นไว้"""
    X, y, cur = _dataset(df, target, h)
    pred = pd.Series(np.nan, index=y.index)
    for year in sorted(set(y.index.year)):
        test = y.index.year == year
        if test.all():
            continue
        pred[test] = predict_linear(fit_linear(X[~test].values, y[~test].values), X[test].values)
    return pd.DataFrame({"obs": y, "pred": pred, "persist": cur})


def fit_rating(df):
    """ระดับน้ำท้ายเขื่อน = a + b·√Q + c·Q"""
    m = df[["dn_h", "out_q"]].dropna()
    m = m[m["out_q"] > 0]
    A = np.c_[np.ones(len(m)), np.sqrt(m["out_q"]), m["out_q"]]
    return np.linalg.lstsq(A, m["dn_h"].values, rcond=None)[0]


def rating_level(rating, q):
    return rating[0] + rating[1] * np.sqrt(q) + rating[2] * q


def train(df, start=TRAIN_START):
    df = df.loc[start:]
    model = {
        "features": [feature_name(c, k) for c, k in FEATURES],
        "bands": BANDS,
        "quantiles": list(QUANTILES),
        "coef": {},
        "interval": {},
        "metrics": [],
        "rating": fit_rating(df).tolist(),
    }
    backtests = {}
    for target in TARGETS:
        model["coef"][target], model["interval"][target] = {}, {}
        for h in HORIZONS:
            X, y, _ = _dataset(df, target, h)
            model["coef"][target][str(h)] = fit_linear(X.values, y.values).tolist()

            bt = backtest(df, target, h).dropna()
            backtests[(target, h)] = bt
            resid = bt["obs"] - bt["pred"]
            bands = bt["persist"].map(band_index)
            model["interval"][target][str(h)] = [
                resid[bands == i].quantile(list(QUANTILES)).tolist() for i in range(len(BANDS))
            ]
            mae = (bt["obs"] - bt["pred"]).abs()
            mae_p = (bt["obs"] - bt["persist"]).abs()
            high = bt["obs"] > 1000
            model["metrics"].append({
                "target": target,
                "h": h,
                "n": len(bt),
                "mae": round(mae.mean(), 1),
                "mae_persist": round(mae_p.mean(), 1),
                "mae_high": round(mae[high].mean(), 1),
                "mae_persist_high": round(mae_p[high].mean(), 1),
            })
    model["trained_on"] = [str(df.index.min().date()), str(df.dropna(subset=["c2_q"]).index.max().date())]
    return model, backtests


def forecast(model, df):
    """พยากรณ์จากวันล่าสุดที่มีข้อมูลครบ"""
    X = features(df).dropna()
    t = X.index[-1]
    x = X.loc[[t]].values
    rows = []
    for h in HORIZONS:
        row = {"date": t + pd.Timedelta(days=h), "h": h}
        for target in TARGETS:
            p = float(predict_linear(np.array(model["coef"][target][str(h)]), x)[0])
            lo, hi = model["interval"][target][str(h)][band_index(df.loc[t, target])]
            row[target] = p
            row[f"{target}_low"] = max(0.0, p + lo)
            row[f"{target}_high"] = p + hi
        row["dn_h"] = float(rating_level(model["rating"], row["out_q"]))
        rows.append(row)
    return t, pd.DataFrame(rows).set_index("date")
