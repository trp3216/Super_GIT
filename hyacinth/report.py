"""สร้างรายงานหน้าเว็บ (HTML ไฟล์เดียว) แผนที่ผักตบชวา + กราฟ + ตาราง"""
import base64
import io
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject

# สีของแต่ละประเภทบนแผนที่ (R, G, B, A) — ตรงกับค่าใน classify.py
COLORS = {
    1: (150, 150, 150, 150),  # เมฆ
    2: (40, 130, 255, 110),   # น้ำเปิด
    3: (120, 255, 0, 235),    # ผักตบชวา
}
TO_LATLNG = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform


def _overlay(tif):
    """แปลง raster จำแนก (UTM) เป็น PNG บน Web Mercator พร้อมขอบเขต lat/lng สำหรับ Leaflet"""
    with rasterio.open(tif) as src:
        transform, w, h = calculate_default_transform(src.crs, "EPSG:3857", src.width, src.height, *src.bounds)
        out = np.zeros((h, w), dtype="uint8")
        reproject(
            rasterio.band(src, 1), out, dst_transform=transform, dst_crs="EPSG:3857",
            resampling=Resampling.nearest, src_nodata=0, dst_nodata=0,
        )
    if not np.isin(out, list(COLORS)).any():
        return None
    rgba = np.zeros((h, w, 4), dtype="uint8")
    for value, color in COLORS.items():
        rgba[out == value] = color
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    west, north = TO_LATLNG(transform.c, transform.f)
    east, south = TO_LATLNG(transform.c + transform.a * w, transform.f + transform.e * h)
    return {
        "png": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
        "bounds": [[south, west], [north, east]],
    }


def build_report(rows, out_dir, path, title):
    out_dir = Path(out_dir)
    rivers, overlays = [], {}
    for name in dict.fromkeys(r["river"] for r in rows):
        gdf = gpd.read_file(out_dir / "river_polygons.gpkg", layer=name)
        geom = gdf.geometry.iloc[0].simplify(0.00003)
        rivers.append({
            "name": name,
            "label": gdf["label"].iloc[0],
            "geojson": json.loads(gpd.GeoSeries([geom], crs=4326).to_json()),
        })
        for r in (r for r in rows if r["river"] == name):
            tifs = sorted((out_dir / "rasters" / name).glob(f"{r['date'].replace('-', '')}_*.tif"))
            overlays[f"{name}|{r['date']}"] = [o for o in map(_overlay, tifs) if o]

    data = {
        "title": title,
        "rivers": rivers,
        "rows": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()} for r in rows],
        "overlays": overlays,
    }
    template = (Path(__file__).parent / "report_template.html").read_text(encoding="utf-8")
    html = template.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    Path(path).write_text(html, encoding="utf-8")
