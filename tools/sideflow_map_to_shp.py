"""สร้าง shapefile ลำน้ำ ถนน และจุดสำคัญ จากแผนที่ sideflow เหนือเขื่อนเจ้าพระยา (PDF)

แผนที่ต้นฉบับทำใน PowerPoint: เส้นลำน้ำ (สีฟ้า) และถนน (สีแดง) วาดเป็น vector
ทับภาพดาวเทียม แต่ไม่มีพิกัดภูมิศาสตร์ สคริปต์นี้จึง
1. แปลง PDF เป็น SVG (pdftocairo) แล้วดึง path แยกตามสี
2. georeference ด้วยการ fit affine ให้แม่น้ำเจ้าพระยาใน PDF ซ้อนกับ
   แม่น้ำเจ้าพระยาใน `แม่น้ำ คลอง/Main_River.shp` (ICP)
3. เขียน shapefile ใน UTM 47N (EPSG:32647) ไว้ที่ data/sideflow/

ใช้:
    python tools/sideflow_map_to_shp.py <map.pdf> [--out data/sideflow]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

BLUE = "rgb(0%, 68.998718%, 94.099426%)"
RED = "rgb(100%, 0%, 0%)"

_NUM = re.compile(r"-?\d+(?:\.\d*)?(?:e-?\d+)?")


def _bezier(p0, p1, p2, p3, n=8):
    t = np.linspace(0, 1, n + 1)[1:, None]
    return ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1
            + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3)


def parse_d(d: str) -> list[np.ndarray]:
    """แปลง path data ของ cairo (M/L/C/Z แบบ absolute) เป็นรายการ polyline"""
    parts, cur = [], []
    for cmd, args in re.findall(r"([MLCZ])([^MLCZ]*)", d):
        v = np.array([float(x) for x in _NUM.findall(args)]).reshape(-1, 2)
        if cmd == "M":
            if len(cur) > 1:
                parts.append(np.array(cur))
            cur = [v[0], *v[1:]]
        elif cmd == "L":
            cur.extend(v)
        elif cmd == "C":
            for i in range(0, len(v), 3):
                cur.extend(_bezier(np.asarray(cur[-1]), v[i], v[i + 1], v[i + 2]))
        elif cmd == "Z" and cur:
            cur.append(cur[0])
    if len(cur) > 1:
        parts.append(np.array(cur))
    return parts


def _matrix(attr: str) -> np.ndarray:
    m = re.search(r'transform="matrix\(([^)]*)\)"', attr)
    a, b, c, d, e, f = (float(x) for x in m.group(1).split(",")) if m else (1, 0, 0, 1, 0, 0)
    return np.array([[a, c, e], [b, d, f]])


def load_svg_paths(svg_file) -> list[dict]:
    """คืน path ที่สนใจ ในพิกัดหน้ากระดาษ (pt, y ชี้ลง เหมือน pdftotext -bbox)

    kind: blue_line = ลำน้ำสาขา, blue_fill = ผิวน้ำแม่น้ำเจ้าพระยา,
          red_line = ถนน (เส้นแดงหนา ≥ 3 pt; เส้นแดงบางคือกรอบป้าย),
          red_dot = จุดสถานีวัดน้ำ
    """
    s = Path(svg_file).read_text()
    out = []
    for i, m in enumerate(re.finditer(r"<path ([^>]*)/>", s)):
        a = m.group(1)
        d = re.search(r'\bd="([^"]*)"', a)
        if not d:
            continue
        stroke = re.search(r'stroke="([^"]*)"', a)
        fill = re.search(r' fill="([^"]*)"', a)
        width = re.search(r'stroke-width="([^"]*)"', a)
        stroke = stroke.group(1) if stroke else None
        fill = fill.group(1) if fill else None
        width = float(width.group(1)) if width else 0.0
        if stroke == BLUE:
            kind = "blue_line"
        elif stroke is None and fill == BLUE:
            kind = "blue_fill"
        elif stroke == RED and fill is None and width >= 3:
            kind = "red_line"
        elif stroke == RED and fill == RED and width == 1:
            kind = "red_dot"  # วงกลมแดงตำแหน่งสถานีวัดน้ำ
        else:
            continue
        mat = _matrix(a)
        parts = [p @ mat[:, :2].T + mat[:, 2] for p in parse_d(d.group(1))]
        out.append({"id": i, "kind": kind, "width": width, "parts": parts})
    return out


def pdf_to_svg(pdf: Path, workdir: Path) -> Path:
    svg = workdir / "map.svg"
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(svg)], check=True)
    return svg


# ---------------------------------------------------------------------------
# ข้อความและสัญลักษณ์บนแผนที่


def load_words(pdf: Path) -> list[dict]:
    """ข้อความที่เป็น text จริงใน PDF พร้อมกรอบ (pt) จาก pdftotext -bbox"""
    html = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"], check=True,
                          capture_output=True, text=True).stdout
    words = []
    for x0, y0, x1, y1, w in re.findall(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', html):
        words.append({"text": w, "box": (float(x0), float(y0), float(x1), float(y1))})
    return words


def load_icons(svg_file) -> list[np.ndarray]:
    """ตำแหน่งกึ่งกลางของรูปไอคอนเล็ก (ประตูระบายน้ำ สะพาน ฯลฯ) ในพิกัดหน้ากระดาษ"""
    s = Path(svg_file).read_text()
    sizes = {m.group(1): (float(m.group(2)), float(m.group(3))) for m in re.finditer(
        r'<image id="([\w-]+)" x="0" y="0" width="([\d.]+)" height="([\d.]+)"', s)}
    out = []
    for ref, attr in re.findall(r'<use xlink:href="#([\w-]+)"([^>]*)/>', s):
        if ref not in sizes or sizes[ref][0] > 200:  # ข้ามภาพดาวเทียมพื้นหลัง
            continue
        w, h = sizes[ref]
        mat = _matrix(attr)
        out.append(mat[:, :2] @ [w / 2, h / 2] + mat[:, 2])
    return out


# ---------------------------------------------------------------------------
# เส้นกึ่งกลางของแม่น้ำเจ้าพระยา (ในแผนที่วาดเป็น polygon ผิวน้ำ)


def polygon_centerline(poly: np.ndarray, res: float = 0.25) -> np.ndarray:
    """เส้นกึ่งกลางของ polygon แคบยาว: rasterize → skeleton → เส้นทางที่ยาวที่สุด"""
    from collections import deque

    from skimage.draw import polygon as fill_polygon
    from skimage.morphology import skeletonize

    lo = poly.min(0) - 2
    rc = (poly - lo) / res
    shape = (int(rc[:, 1].max()) + 8, int(rc[:, 0].max()) + 8)
    mask = np.zeros(shape, bool)
    rr, cc = fill_polygon(rc[:, 1], rc[:, 0], shape)
    mask[rr, cc] = True
    sk = skeletonize(mask)
    pix = set(zip(*np.nonzero(sk)))
    nb = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def bfs(start):
        prev, q, last = {start: None}, deque([start]), start
        while q:
            last = cur = q.popleft()
            for dr, dc in nb:
                n = (cur[0] + dr, cur[1] + dc)
                if n in pix and n not in prev:
                    prev[n] = cur
                    q.append(n)
        return last, prev

    far, _ = bfs(next(iter(pix)))
    end, prev = bfs(far)
    path, cur = [], end
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path = np.array(path, float)[:, ::-1] * res + lo
    return simplify(path, 0.3)


def simplify(pts: np.ndarray, tol: float) -> np.ndarray:
    """Douglas–Peucker"""
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    ab = b - a
    n = np.hypot(*ab)
    d = (np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / n
         if n else np.hypot(*(pts - a).T))
    i = int(np.argmax(d))
    if d[i] <= tol:
        return np.array([a, b])
    return np.vstack([simplify(pts[:i + 1], tol)[:-1], simplify(pts[i:], tol)])


# ---------------------------------------------------------------------------
# Georeference


def densify(pts: np.ndarray, step: float) -> np.ndarray:
    seg = np.diff(pts, axis=0)
    out = [pts[:1]]
    for p, s in zip(pts[:-1], seg):
        n = max(1, int(np.ceil(np.hypot(*s) / step)))
        out.append(p + s * (np.arange(1, n + 1)[:, None] / n))
    return np.vstack(out)


def design(xy: np.ndarray, order: int) -> np.ndarray:
    x, y = xy[:, 0], xy[:, 1]
    cols = [np.ones_like(x), x, y]
    if order >= 2:
        cols += [x * x, x * y, y * y]
    return np.column_stack(cols)


class Georef:
    """แปลงพิกัดหน้ากระดาษ (pt) → UTM 47N ด้วย polynomial ลำดับ 1 (affine) หรือ 2"""

    def __init__(self, coef: np.ndarray, order: int, origin: np.ndarray):
        self.coef, self.order, self.origin = coef, order, origin

    def __call__(self, xy: np.ndarray) -> np.ndarray:
        return design((np.asarray(xy) - self.origin) / 100.0, self.order) @ self.coef

    @classmethod
    def fit(cls, src, dst, order, origin, weights=None):
        A = design((src - origin) / 100.0, order)
        w = np.ones(len(src)) if weights is None else weights
        coef, *_ = np.linalg.lstsq(A * w[:, None], dst * w[:, None], rcond=None)
        return cls(coef, order, origin)


def icp(pairs, init: Georef, order: int, iters=60, start_tol=3000.0, end_tol=400.0):
    """Iterative closest point: pairs = [(จุด PDF, KDTree ของเส้นอ้างอิง, จุดอ้างอิง), ...]

    แต่ละลำน้ำใน PDF จับคู่กับลำน้ำชื่อเดียวกันในข้อมูลอ้างอิงเท่านั้น
    ระยะตัดคู่ (outlier) ค่อยๆ ลดจาก start_tol ถึง end_tol เมตร
    """
    g = init
    for k in range(iters):
        tol = start_tol * (end_tol / start_tol) ** (k / max(1, iters - 1))
        S, D, W = [], [], []
        for src, tree, ref in pairs:
            d, j = tree.query(g(src))
            ok = d < tol
            S.append(src[ok]); D.append(ref[j[ok]])
            # ให้น้ำหนักเท่ากันต่อลำน้ำ ไม่ให้เส้นยาวครอบงำ
            W.append(np.full(ok.sum(), 1 / np.sqrt(max(ok.sum(), 1))))
        S, D, W = np.vstack(S), np.vstack(D), np.concatenate(W)
        g = Georef.fit(S, D, order if k > iters // 3 else 1, init.origin, W)
    res = np.hypot(*(g(S) - D).T)
    return g, float(np.sqrt(np.mean(res ** 2))), float(np.median(res))


# ---------------------------------------------------------------------------
# ข้อมูลประกอบ (อ่านจากแผนที่และตาราง sideflow วันที่ 14 ต.ค. 2569)

FLOW_DATE = "2026-10-14"

# id ของ path ใน SVG → (ชื่อ, ประเภท, บทบาท, อัตราการไหล ลบ.ม./วิ หรือ None, หมายเหตุ)
# บทบาท: in = ไหลลงแม่น้ำเจ้าพระยา (sideflow), out = รับน้ำออกจากเจ้าพระยา, trib = สาขาของลำน้ำอื่น
RIVERS = {
    164: ("แม่น้ำเจ้าพระยา", "แม่น้ำ", "main", None, "เส้นกึ่งกลางจาก polygon ผิวน้ำในแผนที่"),
    165: ("แม่น้ำสะแกกรัง", "แม่น้ำ", "in", 203.0,
          "ตอนบนคือน้ำตากแดด ผ่าน Ct.19 และ Ct.2A; ค่าที่ Ct.2A รวม Ct.19 (76) + ห้วยอีเติ่ง + น้ำสะสม"),
    166: ("คลองบางประมุง", "คลอง", "in", 121.0, "ต.ยางตาล อ.โกรกพระ จ.นครสวรรค์"),
    167: ("คลองตาแวน", "คลอง", "trib", None, "ไหลลงคลองบางประมุง"),
    168: ("คลองโกรกพระ", "คลอง", "in", 48.0, "ต.ยางตาล อ.โกรกพระ จ.นครสวรรค์"),
    169: ("คลองตะเข้", "คลอง", "in", None, "ฝั่งซ้ายแม่น้ำเจ้าพระยา"),
    177: ("คลองยาง", "คลอง", "in", 17.0, "ต.ท่าซุง อ.เมืองอุทัยธานี จ.อุทัยธานี"),
    179: ("คลองพึ่ง", "คลอง", "trib", None, "ไหลลงคลองยาง"),
    180: ("คลองเคียน", "คลอง", "in", 8.0, "ต.คุ้งสำเภา อ.มโนรมย์ จ.ชัยนาท"),
    181: ("ห้วยขุนแก้ว", "ห้วย", "in", 22.0, "รอยต่อ จ.อุทัยธานี และ จ.ชัยนาท"),
    184: ("ห้วยทับเสลา", "ห้วย", "trib", 10.0, "ต.น้ำซึม อ.เมืองอุทัยธานี จ.อุทัยธานี ไหลลงแม่น้ำสะแกกรัง"),
    218: ("คลองชัยนาท-ป่าสัก", "คลอง", "out", None, "รับน้ำที่ ปตร.มโนรมย์"),
    219: ("คลองชัยนาท-อยุธยา", "คลอง", "out", None, "รับน้ำที่ ปตร.มหาราช"),
    248: ("แม่น้ำน้อย", "แม่น้ำ", "out", None, "รับน้ำที่ ปตร.บรมธาตุ"),
    252: ("แม่น้ำท่าจีน", "แม่น้ำ", "out", None, "รับน้ำที่ ปตร.พลเทพ"),
    253: ("ห้วยขุนแก้ว", "ห้วย", "out", None, "ช่วงต่อลงไปทาง ปตร.พลเทพ / แม่น้ำท่าจีน"),
    254: ("คลองมะขามเฒ่า-อู่ทอง", "คลอง", "out", None, "ป้ายในแผนที่ \"คลอง มอ มก\""),
    263: ("คลองร่องประพาน", "คลอง", "trib", None, "ไหลลงน้ำตากแดด"),
    265: ("คลองพระแวง", "คลอง", "trib", None, "ไหลลงน้ำตากแดด"),
    267: ("ห้วยอีเติ่ง", "ห้วย", "trib", None, "ไหลลงแม่น้ำสะแกกรังเหนือ Ct.2A"),
}

ROADS = {
    235: ("ถนนพหลโยธิน", "1", "ทางหลวงแผ่นดินหมายเลข 1"),
    233: ("ถนนสายเอเชีย", "32", "ทางหลวงแผ่นดินหมายเลข 32 (AH1/AH2)"),
}

# ข้อความในแผนที่ → (ชื่อ, ประเภท, ตำแหน่งยึด)
# ตำแหน่งยึด: "circle" = จุดแดงสถานีวัดน้ำ, "icon" = ไอคอนที่ใกล้ป้ายที่สุด, "label" = กึ่งกลางป้าย
POINTS = {
    "C.2": ("สถานีวัดน้ำ C.2 นครสวรรค์", "สถานีวัดน้ำ", "circle"),
    "Ct.19": ("สถานีวัดน้ำ Ct.19", "สถานีวัดน้ำ", "circle"),
    "Ct.2A": ("สถานีวัดน้ำ Ct.2A", "สถานีวัดน้ำ", "circle"),
    "C.13": ("สถานีวัดน้ำ C.13 ท้ายเขื่อนเจ้าพระยา", "สถานีวัดน้ำ", "circle"),
    "ปตร.คลองขุมทรัพย์": ("ปตร.คลองขุมทรัพย์", "ประตูระบายน้ำ", "icon"),
    "ปตร.ประพาสต้น": ("ปตร.ประพาสต้น", "ประตูระบายน้ำ", "icon"),
    "ปตร.มโนรมย์": ("ปตร.มโนรมย์", "ประตูระบายน้ำ", "icon"),
    "ปตร.พลเทพ": ("ปตร.พลเทพ", "ประตูระบายน้ำ", "icon"),
    "ปตร.มหาราช": ("ปตร.มหาราช", "ประตูระบายน้ำ", "icon"),
    "ปตร.บรมธาตุ": ("ปตร.บรมธาตุ", "ประตูระบายน้ำ", "icon"),
    "เขื่อนเจ้าพระยา": ("เขื่อนเจ้าพระยา", "เขื่อน", "icon"),
    "สะพานมโนรมย์": ("สะพานมโนรมย์", "สะพาน", "icon"),
    "สะพานธรรมมูล": ("สะพานธรรมมูล", "สะพาน", "icon"),
    "ศาลากลางจังหวัดชัยนาท": ("ศาลากลางจังหวัดชัยนาท", "สถานที่ราชการ", "icon"),
}

# path ใน PDF ที่ใช้ georeference → ชื่อลำน้ำใน Main_River.shp
GEOREF_RIVERS = {
    164: ["แม่น้ำเจ้าพระยา"],
    165: ["แม่น้ำสะแกกรัง", "น้ำตากแดด"],
    252: ["แม่น้ำท่าจีน"],
    248: ["แม่น้ำน้อย"],
}
# ใช้ตรวจความแม่นยำเท่านั้น (ไม่ใช้ fit)
CHECK_RIVERS = {
    180: ["คลองเคียน"],
    181: ["ห้วยขุนแก้ว"],
    177: ["คลองยาง"],
}

# พิกัดโดยประมาณสำหรับตั้งต้น ICP (UTM 47N): จุดแดง C.2 และ C.13 ในแผนที่
INIT_CONTROL = {"C.2": (619730.0, 1732940.0), "C.13": (627130.0, 1676000.0)}


# ---------------------------------------------------------------------------
# ประกอบผล


def _similarity(src: list, dst: list) -> tuple[np.ndarray, np.ndarray]:
    """จุดควบคุม 3 จุดจาก 2 จุด (เติมจุดที่สามแบบตั้งฉาก) สำหรับ affine ตั้งต้น
    หน้ากระดาษ y ชี้ลง แต่ UTM y ชี้ขึ้น จึงกลับด้านแกน"""
    (s0, s1), (d0, d1) = np.asarray(src, float), np.asarray(dst, float)
    perp = lambda v: np.array([-v[1], v[0]])  # noqa: E731
    s2 = s0 + perp(s1 - s0)
    d2 = d0 - perp(d1 - d0)
    return np.array([s0, s1, s2]), np.array([d0, d1, d2])


def load_reference(shp_dir: Path, names: list[str], bbox, step=20.0) -> np.ndarray:
    import shapefile

    pts = []
    for fn in ("Main_River", "Main_canal"):
        r = shapefile.Reader(str(shp_dir / fn), encoding="cp874")
        for sr in r.iterShapeRecords():
            if sr.record["NAME"] not in names:
                continue
            p = np.array(sr.shape.points)
            idx = list(sr.shape.parts) + [len(p)]
            for a, b in zip(idx[:-1], idx[1:]):
                part = p[a:b]
                if len(part) > 1:
                    pts.append(densify(part, step))
        if pts:
            break  # ใช้ Main_River เป็นหลัก ถ้าไม่มีจึงใช้ Main_canal
    pts = np.vstack(pts)
    x0, y0, x1, y1 = bbox
    keep = (pts[:, 0] > x0) & (pts[:, 0] < x1) & (pts[:, 1] > y0) & (pts[:, 1] < y1)
    return pts[keep]


def line_length_km(p: np.ndarray) -> float:
    return float(np.hypot(*np.diff(p, axis=0).T).sum() / 1000)


def dist_to(points: np.ndarray, target: np.ndarray) -> float:
    return float(np.min(np.hypot(*(target - points).T)))


def build(pdf: Path, shp_dir: Path, order: int):
    from scipy.spatial import cKDTree

    work = Path(tempfile.mkdtemp())
    svg = pdf_to_svg(pdf, work)
    paths = {p["id"]: p for p in load_svg_paths(svg)}
    words = load_words(pdf)
    icons = load_icons(svg)
    dots = [p["parts"][0].mean(0) for p in paths.values() if p["kind"] == "red_dot"]

    def label_center(text):
        w = next(w for w in words if w["text"] == text)
        x0, y0, x1, y1 = w["box"]
        return np.array([(x0 + x1) / 2, (y0 + y1) / 2])

    def nearest(c, cands):
        return min(cands, key=lambda q: np.hypot(*(q - c)))

    # --- georeference
    names = list(INIT_CONTROL)
    s, d = _similarity([nearest(label_center(n), dots) for n in names],
                       [INIT_CONTROL[n] for n in names])
    origin = np.array([240.0, 500.0])
    init = Georef.fit(s, d, 1, origin)

    page_pts = np.vstack([q for p in paths.values() for q in p["parts"]])
    g0 = init(page_pts)
    bbox = (*(g0.min(0) - 5000), *(g0.max(0) + 5000))

    def src_points(pid):
        return np.vstack([densify(q, 0.5) for q in paths[pid]["parts"]])

    def pairs_for(table):
        out = []
        for pid, ref_names in table.items():
            ref = load_reference(shp_dir, ref_names, bbox)
            out.append((src_points(pid), cKDTree(ref), ref))
        return out

    fit_pairs = pairs_for(GEOREF_RIVERS)
    g, rmse, med = icp(fit_pairs, init, order)
    stats = {"order": order, "fit_rmse_m": round(rmse), "fit_median_m": round(med), "check": {}}
    for (src, tree, _), pid in zip(pairs_for(CHECK_RIVERS), CHECK_RIVERS):
        dd, _ = tree.query(g(src))
        stats["check"][RIVERS[pid][0]] = {"median_m": round(float(np.median(dd))),
                                          "p90_m": round(float(np.percentile(dd, 90)))}

    # --- ลำน้ำ
    cp_poly = paths[164]["parts"][0]
    cp_line = polygon_centerline(cp_poly)
    if cp_line[0, 1] > cp_line[-1, 1]:  # ไหลจากเหนือ (บนกระดาษ) ลงใต้
        cp_line = cp_line[::-1]
    cp_dense = densify(cp_poly, 0.5)
    all_lines = {pid: paths[pid]["parts"][0] for pid in RIVERS if pid != 164}

    rivers = []
    for pid, (name, typ, role, flow, note) in RIVERS.items():
        line = cp_line if pid == 164 else all_lines[pid]
        if role in ("in", "out"):
            s_d, e_d = dist_to(line[:1], cp_dense), dist_to(line[-1:], cp_dense)
            if (role == "in") == (s_d < e_d):
                line = line[::-1]
        elif role == "trib":
            others = np.vstack([densify(v, 0.5) for k, v in all_lines.items() if k != pid])
            if dist_to(line[:1], others) < dist_to(line[-1:], others):
                line = line[::-1]
        geo = g(line)
        rivers.append({"geom": geo, "NAME": name, "TYPE": typ, "ROLE": role, "FLOW_CMS": flow,
                       "FLOW_DATE": FLOW_DATE if flow is not None else "",
                       "LEN_KM": round(line_length_km(geo), 2), "NOTE": note, "SRC_ID": pid})

    area = g(cp_poly)

    # --- ถนน
    roads = []
    for pid, (name, no, note) in ROADS.items():
        geo = g(paths[pid]["parts"][0])
        roads.append({"geom": geo, "NAME": name, "ROUTE_NO": no,
                      "LEN_KM": round(line_length_km(geo), 2), "NOTE": note, "SRC_ID": pid})

    # --- จุด
    points = []
    for text, (name, typ, anchor) in POINTS.items():
        c = label_center(text)
        if anchor == "circle":
            c = nearest(c, dots)
        elif anchor == "icon":
            c = nearest(c, icons)
        x, y = g(c[None])[0]
        points.append({"geom": np.array([x, y]), "NAME": name, "TYPE": typ, "LABEL": text,
                       "ANCHOR": anchor})

    return {"rivers": rivers, "area": area, "roads": roads, "points": points, "stats": stats,
            "georef": g}


# ---------------------------------------------------------------------------
# เขียน shapefile


def _ring_clockwise(ring: np.ndarray) -> np.ndarray:
    x, y = ring[:, 0], ring[:, 1]
    signed = np.sum(x[:-1] * y[1:] - x[1:] * y[:-1])
    return ring if signed < 0 else ring[::-1]


def _write(path: Path, shape_type, fields, feats, add_geom, prj: str):
    import shapefile

    with shapefile.Writer(str(path), shapeType=shape_type, encoding="utf-8") as w:
        for f in fields:
            w.field(*f)
        for ft in feats:
            add_geom(w, ft["geom"])
            w.record(*[ft.get(f[0]) for f in fields])
    path.with_suffix(".prj").write_text(prj)
    path.with_suffix(".cpg").write_text("UTF-8")


def write_all(res: dict, out: Path, prj: str):
    import shapefile

    out.mkdir(parents=True, exist_ok=True)
    line = lambda w, g: w.line([g.round(2).tolist()])  # noqa: E731
    _write(out / "sideflow_rivers.shp", shapefile.POLYLINE,
           [("NAME", "C", 100), ("TYPE", "C", 20), ("ROLE", "C", 10), ("FLOW_CMS", "N", 10, 2),
            ("FLOW_DATE", "C", 10), ("LEN_KM", "N", 10, 2), ("NOTE", "C", 254), ("SRC_ID", "N", 5)],
           res["rivers"], line, prj)
    _write(out / "sideflow_roads.shp", shapefile.POLYLINE,
           [("NAME", "C", 100), ("ROUTE_NO", "C", 10), ("LEN_KM", "N", 10, 2), ("NOTE", "C", 254),
            ("SRC_ID", "N", 5)],
           res["roads"], line, prj)
    _write(out / "sideflow_chaophraya_area.shp", shapefile.POLYGON, [("NAME", "C", 100)],
           [{"geom": _ring_clockwise(res["area"]), "NAME": "แม่น้ำเจ้าพระยา"}],
           lambda w, g: w.poly([g.round(2).tolist()]), prj)
    _write(out / "sideflow_points.shp", shapefile.POINT,
           [("NAME", "C", 100), ("TYPE", "C", 60), ("LABEL", "C", 100), ("ANCHOR", "C", 10)],
           res["points"], lambda w, g: w.point(*g.round(2).tolist()), prj)


def main(argv=None):
    import json

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path, help="PDF แผนที่ sideflow (หน้าเดียว)")
    ap.add_argument("--out", type=Path, default=Path("data/sideflow"))
    ap.add_argument("--ref-dir", type=Path, default=Path("แม่น้ำ คลอง"))
    ap.add_argument("--order", type=int, default=1, choices=(1, 2),
                    help="ลำดับ polynomial ของการ georeference (1 = affine)")
    a = ap.parse_args(argv)

    res = build(a.pdf, a.ref_dir, a.order)
    prj = (a.ref_dir / "Main_River.prj").read_text()
    write_all(res, a.out, prj)
    (a.out / "georef_report.json").write_text(
        json.dumps(res["stats"], ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(res["stats"], ensure_ascii=False, indent=2))
    print(f"เขียน shapefile ไว้ที่ {a.out}/")


if __name__ == "__main__":
    main()
