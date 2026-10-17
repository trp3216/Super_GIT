"""Build public/geo.js: real-world geometry for the 3D scene.

River lines come from the repo shapefile (แม่น้ำ คลอง/Main_River.shp, UTM 47N, bank lines);
province and district boundaries (Thai names) from OpenGISData-Thailand (CC BY 4.0).

    pip install pyshp shapely pyproj
    curl -LO https://raw.githubusercontent.com/chingchai/OpenGISData-Thailand/master/provinces.geojson
    curl -LO https://raw.githubusercontent.com/chingchai/OpenGISData-Thailand/master/districts.geojson
    python chao_phraya_3d/tools/build_geo.py --boundaries <dir with the two geojson files>

Scene frame: x = -(N - N0) / 1000 * SCALE (north to the left), z = -(E - E0) / 1000 * SCALE (east toward −z).
"""
import argparse
import datetime
import json
import math
from pathlib import Path

import shapefile
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, box, shape
from shapely.ops import linemerge, transform, unary_union

ROOT = Path(__file__).resolve().parents[2]
RIVER_SHP = ROOT / "แม่น้ำ คลอง" / "Main_River.shp"
OUT = ROOT / "chao_phraya_3d" / "public" / "geo.js"
SCALE = 0.8          # scene units per km
MARGIN_EW_M = 32000  # boundary area east/west of the river
MARGIN_NS_M = 4000

to_utm = Transformer.from_crs(4326, 32647, always_xy=True)
to_ll = Transformer.from_crs(32647, 4326, always_xy=True)

# Approximate locations (lat, lon); each is snapped to the river line.
ANCHORS = {
    "dam": (15.1572, 100.1797),      # เขื่อนเจ้าพระยา
    "c29b": (14.0630, 100.5250),     # C.29B สามโคก
    "c38": (14.0190, 100.5310),      # C.38 เมืองปทุมธานี
    "c22a": (13.9120, 100.4970),     # C.22A ปากเกร็ด
    "rama8": (13.7699, 100.4968),    # สะพานพระราม 8
}
C12_UPSTREAM_OF_RAMA8_M = 3000      # the plan PDF: Rama 8 is ≈3 km downstream of C.12
PASAK_TOP_LAT = 14.56                # Rama VI Dam (Tha Ruea)


def river_lines(name):
    r = shapefile.Reader(str(RIVER_SHP), encoding="cp874")
    geoms = [shape(sr.shape.__geo_interface__) for sr in r.iterShapeRecords() if sr.record["NAME"] == name]
    lines = [l for g in geoms for l in getattr(g, "geoms", [g])]
    merged = linemerge(lines)
    return [p for p in getattr(merged, "geoms", [merged]) if not p.is_ring and p.length > 200]


def chain(parts, start_pt, go_south=True, max_gap=3000.0):
    """Joins line parts end to end from start_pt, always moving north→south (or south→north)."""
    remaining = list(parts)
    coords = []
    cur = start_pt
    while remaining:
        best = None
        for p in remaining:
            for rev in (False, True):
                c = list(p.coords)[::-1] if rev else list(p.coords)
                d = math.dist(cur, c[0])
                gain = (c[0][1] - c[-1][1]) if go_south else (c[-1][1] - c[0][1])
                if gain > 0 and d < max_gap and (best is None or d < best[0]):
                    best = (d, p, c)
        if not best:
            break
        _, p, c = best
        coords.extend(c if not coords else c[1:])
        remaining.remove(p)
        cur = c[-1]
    return LineString(coords)


def q(v):
    return round(v * 100)  # scene units × 100, integer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boundaries", required=True, help="directory with provinces.geojson and districts.geojson")
    args = ap.parse_args()
    bdir = Path(args.boundaries)

    # ---- rivers (UTM metres)
    cp_parts = river_lines("แม่น้ำเจ้าพระยา")
    # start from the longest continuous bank (Nakhon Sawan → Ayutthaya), then join parts southward
    longest = max(cp_parts, key=lambda p: p.length)
    c0 = list(longest.coords) if longest.coords[0][1] > longest.coords[-1][1] else list(longest.coords)[::-1]
    rest = chain([p for p in cp_parts if p is not longest], c0[-1], go_south=True)
    river = LineString(c0 + list(rest.coords)[1:]).simplify(250)
    ps_parts = river_lines("แม่น้ำป่าสัก")
    south_end = min((pt for p in ps_parts for pt in (p.coords[0], p.coords[-1])), key=lambda c: c[1])
    pasak = chain(ps_parts, south_end, go_south=False)
    top_n = to_utm.transform(100.7, PASAK_TOP_LAT)[1]
    pasak = LineString([c for c in pasak.coords if c[1] <= top_n]).simplify(250)
    pasak = LineString(list(pasak.coords)[::-1])  # flows south toward the confluence
    sk = river_lines("แม่น้ำสะแกกรัง")[0]
    if Point(sk.coords[0]).distance(river) < Point(sk.coords[-1]).distance(river):
        sk = LineString(list(sk.coords)[::-1])     # ends at the Chao Phraya
    sakaekrang = sk.simplify(250)

    total = river.length
    anchors = {}
    for k, (lat, lon) in ANCHORS.items():
        p = Point(*to_utm.transform(lon, lat))
        anchors[k] = {"s": river.project(p) / total, "snap_m": round(p.distance(river))}
    anchors["c12"] = {"s": (anchors["rama8"]["s"] * total - C12_UPSTREAM_OF_RAMA8_M) / total, "snap_m": None}
    anchors["join"] = {"s": river.project(Point(pasak.coords[-1])) / total, "snap_m": round(Point(pasak.coords[-1]).distance(river))}
    anchors["skjoin"] = {"s": river.project(Point(sakaekrang.coords[-1])) / total, "snap_m": round(Point(sakaekrang.coords[-1]).distance(river))}
    order = ["skjoin", "dam", "join", "c29b", "c38", "c22a", "c12", "rama8"]
    ss = [anchors[k]["s"] for k in order]
    assert ss == sorted(ss), f"anchors out of order along the river: {list(zip(order, ss))}"

    # ---- frame
    minx, miny, maxx, maxy = river.bounds
    area = box(minx - MARGIN_EW_M, miny - MARGIN_NS_M, maxx + MARGIN_EW_M, maxy + MARGIN_NS_M)
    E0, N0 = (minx + maxx) / 2, (miny + maxy) / 2
    sx = lambda E, N: (-(N - N0) / 1000 * SCALE, -(E - E0) / 1000 * SCALE)
    flat = lambda line: [v for E, N in line.coords for v in map(q, sx(E, N))]

    # ---- boundaries
    def load(fn, name_key):
        fc = json.loads((bdir / fn).read_text(encoding="utf-8"))
        out = []
        for f in fc["features"]:
            g = transform(lambda x, y, z=None: to_utm.transform(x, y), shape(f["geometry"]))
            if g.intersects(area):
                out.append((f["properties"], g))
        return out

    provs = load("provinces.geojson", "pro_th")
    dists = load("districts.geojson", "amp_th")
    prov_lines = unary_union([g.boundary for _, g in provs]).intersection(area)
    dist_lines = unary_union([g.boundary for _, g in dists]).intersection(area).difference(prov_lines.buffer(60))

    def lines_of(geom, tol):
        merged = linemerge(geom) if geom.geom_type == "MultiLineString" else geom
        out = []
        for l in getattr(merged, "geoms", [merged]):
            if l.geom_type != "LineString" or l.length < 300:
                continue
            l = l.simplify(tol)
            if len(l.coords) >= 2:
                out.append(flat(l))
        return out

    def labels(items, key, min_area_km2):
        out = []
        for props, g in items:
            inside = g.intersection(area)
            if inside.is_empty or inside.area / 1e6 < min_area_km2:
                continue
            p = inside.representative_point()
            x, z = sx(p.x, p.y)
            out.append({"name": props[key], "pro": props.get("pro_th"), "x": round(x, 2), "z": round(z, 2)})
        return out

    # sanity: Rama 8 in Bangkok, dam in Chai Nat
    def prov_at(lat, lon):
        p = Point(*to_utm.transform(lon, lat))
        return next((pr["pro_th"] for pr, g in provs if g.contains(p)), None)
    assert prov_at(*ANCHORS["rama8"]) == "กรุงเทพมหานคร", prov_at(*ANCHORS["rama8"])
    assert prov_at(*ANCHORS["dam"]) == "ชัยนาท", prov_at(*ANCHORS["dam"])

    bx0, bz0 = sx(area.bounds[0], area.bounds[3])
    bx1, bz1 = sx(area.bounds[2], area.bounds[1])
    geo = {
        "meta": {
            "generated": datetime.date.today().isoformat(),
            "scale_units_per_km": SCALE,
            "origin_utm47n": [round(E0), round(N0)],
            "sources": {
                "rivers": "แม่น้ำ คลอง/Main_River.shp (repository)",
                "boundaries": "OpenGISData-Thailand provinces.geojson / districts.geojson, CC BY 4.0, https://github.com/chingchai/OpenGISData-Thailand",
            },
            "note": "coordinates are scene units ×100 as flat [x0,z0,x1,z1,...]; station positions are approximate",
        },
        "bounds": {"x0": round(min(bx0, bx1), 2), "x1": round(max(bx0, bx1), 2), "z0": round(min(bz0, bz1), 2), "z1": round(max(bz0, bz1), 2)},
        "river": flat(river),
        "riverKm": round(total / 1000, 1),
        "pasak": flat(pasak),
        "sakaekrang": flat(sakaekrang),
        "anchors": {k: round(v["s"], 5) for k, v in anchors.items()},
        "provinces": {"lines": lines_of(prov_lines, 150), "labels": labels(provs, "pro_th", 40)},
        "districts": {"lines": lines_of(dist_lines, 150), "labels": labels(dists, "amp_th", 8)},
    }
    js = "/* generated by tools/build_geo.py; see meta for sources */\nwindow.GEO=" + json.dumps(geo, ensure_ascii=False, separators=(",", ":")) + ";\n"
    OUT.write_text(js, encoding="utf-8")
    print(f"river {total/1000:.1f} km, {len(river.coords)} pts | pasak {len(pasak.coords)} | sakaekrang {len(sakaekrang.coords)}")
    print("anchors", {k: (round(v['s'], 4), v['snap_m']) for k, v in anchors.items()})
    print(f"provinces {len(provs)} ({len(geo['provinces']['labels'])} labels), districts {len(dists)} ({len(geo['districts']['labels'])} labels)")
    print("bounds", geo["bounds"], f"| {OUT.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
