"""ตัวอย่าง:
    python -m hyacinth --start 2026-01-01 --end 2026-03-31
    python -m hyacinth --start 2026-09-01 --end 2026-09-30 --river noi --save-rasters --plot
"""
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import box, shape

from .classify import classify, estimate_volume, summarize
from .config import load_config, load_river_geometry
from .sentinel2 import group_by_date, read_bands, search, search_water_history

FIELDS = [
    "date", "river", "label", "tiles", "total_m2", "geom_m2", "river_m2", "valid_m2", "valid_pct",
    "water_m2", "hyacinth_m2", "other_m2", "hyacinth_pct", "volume_m3", "biomass_t",
]


def grid_cells(geom, size_deg=0.05):
    """แบ่งลำน้ำยาวเป็นช่องย่อย (~5 กม.) เพื่ออ่านภาพเฉพาะบริเวณที่มีลำน้ำ ไม่ต้องอ่านทั้งกรอบ"""
    minx, miny, maxx, maxy = geom.bounds
    for x in np.arange(minx, maxx, size_deg):
        for y in np.arange(miny, maxy, size_deg):
            cell = geom.intersection(box(x, y, x + size_deg, y + size_deg))
            if not cell.is_empty and cell.area > 0:
                yield cell


def process_date(items, geom, cfg_cls, water_hrefs=None, raster_dir=None):
    """รวมผลจากทุก tile ของวันเดียวกัน โดยไม่นับพื้นที่ที่ tile ซ้อนกันซ้ำ"""
    totals, tiles, remaining, jobs = None, [], geom, []
    if raster_dir:
        for old in raster_dir.glob(f"{items[0].datetime:%Y%m%d}_*.tif"):
            old.unlink()
    for item in items:
        part = remaining.intersection(shape(item.geometry))
        if part.is_empty or part.area == 0:
            continue
        remaining = remaining.difference(shape(item.geometry))
        tiles.append(item.properties.get("s2:mgrs_tile", item.id))
        for i, cell in enumerate(grid_cells(part)):
            jobs.append((item, cell, cfg_cls, water_hrefs, raster_dir, f"{item.datetime:%Y%m%d}_{tiles[-1]}_{i:03d}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        for stats in pool.map(lambda job: process_cell(*job), jobs):
            totals = stats if totals is None else {k: totals[k] + v for k, v in stats.items()}
    return totals, tiles


def process_cell(item, geom, cfg_cls, water_hrefs, raster_dir, raster_name):
    bands = read_bands(item, geom, water_hrefs)
    inside = bands["inside"]
    if bands["occurrence"] is not None:
        # ตัดพื้นที่ที่ไม่เคยเป็นน้ำเลย (ตลิ่ง เกาะ ที่ดินที่ถูกเติมเข้ามาตอนสร้างขอบเขตจากเส้นตลิ่ง)
        inside = inside & (bands["occurrence"] >= cfg_cls["min_water_occurrence"])
    classes = classify(
        bands["green"], bands["red"], bands["nir"], bands["scl"], inside,
        ndvi_min=cfg_cls["ndvi_min"], ndwi_water_min=cfg_cls["ndwi_water_min"],
    )
    t = bands["transform"]

    if raster_dir:
        raster_dir.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            raster_dir / f"{raster_name}.tif", "w", driver="GTiff",
            height=classes.shape[0], width=classes.shape[1], count=1, dtype="uint8",
            crs=bands["crs"], transform=t, nodata=0, compress="deflate",
        ) as dst:
            dst.write(classes, 1)
    pixel_m2 = abs(t.a * t.e)
    return {**summarize(classes, pixel_m2), "geom_m2": bands["inside"].sum() * pixel_m2}


def run(cfg, start, end, only=None, save_rasters=False):
    out_dir = cfg["_base_dir"] / cfg.get("output_dir", "outputs")
    img, cls, vol = cfg["imagery"], cfg["classification"], cfg["volume"]
    rows = []
    for river in cfg["rivers"]:
        if only and river["name"] not in only:
            continue
        print(f"\n== {river['label']} ({river['name']})")
        geom = load_river_geometry(river, cfg["_base_dir"])
        # บันทึกขอบเขตลำน้ำที่ใช้คำนวณ ไว้ตรวจสอบใน QGIS
        out_dir.mkdir(parents=True, exist_ok=True)
        gdf = gpd.GeoDataFrame({"name": [river["name"]], "label": [river["label"]]}, geometry=[geom], crs=4326)
        gdf.to_file(out_dir / "river_polygons.gpkg", layer=river["name"])
        total_m2 = gdf.to_crs(gdf.estimate_utm_crs()).area.iloc[0]
        items = search(geom, start, end, img["collection"], img["max_scene_cloud"])
        water_hrefs = search_water_history(geom) if cls.get("min_water_occurrence") else None
        groups = group_by_date(items)
        print(f"   พบภาพ {len(items)} ภาพ / {len(groups)} วัน")

        for date, day_items in groups.items():
            raster_dir = out_dir / "rasters" / river["name"] if save_rasters else None
            stats, tiles = process_date(day_items, geom, cls, water_hrefs, raster_dir)
            if not stats or stats["valid_m2"] == 0:
                continue
            # สัดส่วนที่มองเห็น = (ภาพครอบคลุมขอบเขตลำน้ำกี่ส่วน) × (ผิวน้ำในส่วนนั้นไม่ติดเมฆกี่ส่วน)
            valid_frac = (stats["geom_m2"] / total_m2) * (stats["valid_m2"] / stats["river_m2"])
            if valid_frac < img["min_valid_fraction"]:
                print(f"   {date}: ข้าม (มองเห็นลำน้ำเพียง {valid_frac:.0%} เพราะเมฆหรือภาพไม่ครอบคลุม)")
                continue
            v = estimate_volume(stats["hyacinth_m2"], vol["mat_thickness_m"], vol["wet_biomass_kg_m2"])
            row = {
                "date": date.isoformat(), "river": river["name"], "label": river["label"],
                "tiles": "+".join(tiles), "total_m2": total_m2, **stats, **v,
                "valid_pct": 100 * valid_frac,
                "hyacinth_pct": 100 * stats["hyacinth_m2"] / stats["valid_m2"],
            }
            rows.append(row)
            print(
                f"   {date}: ผักตบ {row['hyacinth_m2'] / 1600:,.1f} ไร่ "
                f"({row['hyacinth_pct']:.1f}% ของลำน้ำที่มองเห็น) "
                f"≈ {row['volume_m3']:,.0f} ลบ.ม. / {row['biomass_t']:,.0f} ตัน"
            )
    return rows, out_dir


def write_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: round(v, 2) if isinstance(v, float) else v for k, v in r.items()})


def plot(rows, path):
    import matplotlib.pyplot as plt
    from datetime import date

    fig, ax = plt.subplots(figsize=(10, 5))
    for name in dict.fromkeys(r["river"] for r in rows):
        rs = [r for r in rows if r["river"] == name]
        ax.plot([date.fromisoformat(r["date"]) for r in rs], [r["hyacinth_m2"] / 1600 for r in rs],
                marker="o", label=name)
    ax.set_ylabel("Water hyacinth area (rai)")
    ax.set_title("Water hyacinth coverage from Sentinel-2")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.autofmt_xdate()
    fig.savefig(path, dpi=150, bbox_inches="tight")


def main():
    p = argparse.ArgumentParser(description="ตรวจวัดผักตบชวาในลำน้ำจาก Sentinel-2")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--start", required=True, help="วันเริ่มต้น YYYY-MM-DD")
    p.add_argument("--end", required=True, help="วันสิ้นสุด YYYY-MM-DD")
    p.add_argument("--river", action="append", help="ประมวลผลเฉพาะลำน้ำนี้ (ใส่ซ้ำได้)")
    p.add_argument("--save-rasters", action="store_true", help="บันทึกแผนที่จำแนก GeoTIFF")
    p.add_argument("--plot", action="store_true", help="สร้างกราฟ PNG")
    p.add_argument("--html", action="store_true", help="สร้างรายงานหน้าเว็บ (แผนที่ + กราฟ + ตาราง)")
    args = p.parse_args()

    cfg = load_config(args.config)
    rows, out_dir = run(cfg, args.start, args.end, args.river, args.save_rasters or args.html)
    if not rows:
        print("\nไม่มีผลลัพธ์ในช่วงวันที่นี้")
        return
    stem = f"hyacinth_{args.start}_{args.end}"
    write_csv(rows, out_dir / f"{stem}.csv")
    print(f"\nบันทึกผล: {out_dir / f'{stem}.csv'}")
    if args.plot:
        plot(rows, out_dir / f"{stem}.png")
        print(f"บันทึกกราฟ: {out_dir / f'{stem}.png'}")
    if args.html:
        from .report import build_report

        title = f"ผักตบชวาในลำน้ำ {args.start} ถึง {args.end}"
        build_report(rows, out_dir, out_dir / f"{stem}.html", title)
        print(f"บันทึกรายงานเว็บ: {out_dir / f'{stem}.html'}")


if __name__ == "__main__":
    main()
