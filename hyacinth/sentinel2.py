"""ค้นหาและอ่านภาพ Sentinel-2 L2A จาก Microsoft Planetary Computer หรือ AWS Open Data (ฟรี ไม่ต้องสมัครบัญชี)"""
import json
import math
import os
import re
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import planetary_computer
import pystac_client
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window, bounds as window_bounds, from_bounds
from shapely.geometry import mapping
from shapely.ops import transform as shp_transform

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

# อ่าน Cloud-Optimized GeoTIFF ผ่านเน็ตให้เร็วขึ้น (ไม่ list โฟลเดอร์บน Azure ทุกครั้งที่เปิดไฟล์)
for _k, _v in {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "VSI_CACHE": "TRUE",
}.items():
    os.environ.setdefault(_k, _v)


def _signed(href):
    # เซ็น URL ตอนอ่านจริง (token มีอายุจำกัด และ planetary_computer ต่ออายุให้อัตโนมัติ)
    if "blob.core.windows.net" not in href:
        return href
    return planetary_computer.sign(href)


def search(geom, start, end, collection="sentinel-2-l2a", max_scene_cloud=60, source="planetary_computer"):
    if source == "aws":
        return search_aws(geom, start, end, max_scene_cloud)
    client = pystac_client.Client.open(STAC_URL)
    items = client.search(
        collections=[collection],
        # ใช้กรอบสี่เหลี่ยมค้นหา (polygon ลำน้ำจริงมีจุดมากเกินกว่า API รับได้)
        bbox=geom.bounds,
        datetime=f"{start}/{end}",
        query={"eo:cloud_cover": {"lt": max_scene_cloud}},
    ).item_collection()
    return list(items)


def group_by_date(items):
    """จัดกลุ่มภาพตามวันที่ถ่าย (ลำน้ำยาวอาจคร่อมหลาย tile ในวันเดียวกัน)"""
    groups = defaultdict(list)
    for item in items:
        groups[item.datetime.date()].append(item)
    for date in groups:
        groups[date].sort(key=lambda i: i.properties.get("eo:cloud_cover", 100))
    return dict(sorted(groups.items()))


AWS_BUCKET = "https://sentinel-cogs.s3.us-west-2.amazonaws.com"
AWS_PREFIX = "sentinel-s2-l2a-cogs"


def _mgrs_tiles(geom, step_deg=0.02):
    """รหัส tile MGRS (เช่น 47PPS) ทุก tile ที่ลำน้ำผ่าน"""
    import mgrs
    from shapely.geometry import Point

    m = mgrs.MGRS()
    minx, miny, maxx, maxy = geom.bounds
    near = geom.buffer(step_deg)
    tiles = set()
    for x in np.arange(minx, maxx + step_deg, step_deg):
        for y in np.arange(miny, maxy + step_deg, step_deg):
            if near.contains(Point(x, y)):
                tiles.add(m.toMGRS(y, x, MGRSPrecision=0))
    return sorted(tiles)


def _s3_prefixes(prefix):
    url = f"{AWS_BUCKET}/?list-type=2&delimiter=/&prefix={prefix}"
    with urllib.request.urlopen(url, timeout=60) as r:
        xml = r.read().decode()
    return re.findall(r"<Prefix>([^<]+/)</Prefix>", xml)[1:]


def search_aws(geom, start, end, max_scene_cloud=60):
    """ค้นภาพจาก bucket sentinel-cogs (AWS Open Data) โดยตรง — ใช้เมื่อเข้า Planetary Computer ไม่ได้"""
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    months = sorted({(y, mo) for y in range(d0.year, d1.year + 1) for mo in range(1, 13)
                     if (y, mo) >= (d0.year, d0.month) and (y, mo) <= (d1.year, d1.month)})
    items = []
    for tile in _mgrs_tiles(geom):
        zone, band, sq = tile[:2], tile[2], tile[3:]
        latest = {}  # (วันที่) -> (sequence, prefix) — เก็บเฉพาะการประมวลผลล่าสุดของแต่ละวัน
        for y, mo in months:
            for pre in _s3_prefixes(f"{AWS_PREFIX}/{zone}/{band}/{sq}/{y}/{mo}/"):
                name = pre.rstrip("/").split("/")[-1]  # S2B_47PPS_20260905_0_L2A
                mt = re.match(r"S2[A-D]_\w{5}_(\d{8})_(\d+)_L2A$", name)
                if not mt:
                    continue
                d = date(int(mt[1][:4]), int(mt[1][4:6]), int(mt[1][6:]))
                if d0 <= d <= d1:
                    key = (d, name[:3])
                    if key not in latest or int(mt[2]) > latest[key][0]:
                        latest[key] = (int(mt[2]), pre, name)
        for _, pre, name in latest.values():
            with urllib.request.urlopen(f"{AWS_BUCKET}/{pre}{name}.json", timeout=60) as r:
                d = json.load(r)
            props = d["properties"]
            if props.get("eo:cloud_cover", 100) >= max_scene_cloud:
                continue
            props["s2:mgrs_tile"] = tile
            base = f"{AWS_BUCKET}/{pre}"
            items.append(SimpleNamespace(
                id=d["id"], geometry=d["geometry"], properties=props,
                datetime=datetime.fromisoformat(props["datetime"].replace("Z", "+00:00")),
                assets={b: SimpleNamespace(href=f"{base}{b}.tif") for b in ("B03", "B04", "B08", "SCL")},
            ))
    return items


def _boa_offset(item):
    if item.properties.get("earthsearch:boa_offset_applied"):
        return 0  # ภาพบน AWS หัก offset ให้แล้ว
    # ตั้งแต่ processing baseline 04.00 (ม.ค. 2022) ค่า DN ถูกบวก offset 1000
    try:
        return 1000 if float(item.properties.get("s2:processing_baseline", "0")) >= 4.0 else 0
    except ValueError:
        return 0


def search_water_history(geom):
    """ไฟล์ความถี่การเป็นน้ำ (JRC Global Surface Water occurrence 1984–2020, 30 ม.) ที่ครอบคลุมลำน้ำ"""
    client = pystac_client.Client.open(STAC_URL)
    items = client.search(collections=["jrc-gsw"], bbox=geom.bounds).item_collection()
    return [item.assets["occurrence"].href for item in items]


def read_water_occurrence(hrefs, crs, transform, shape):
    """% ของเวลาที่พิกเซลเป็นน้ำ (0–100) บนกริดเดียวกับ Sentinel-2 — ใช้ค่าสูงสุดเมื่อคร่อมหลาย tile"""
    occurrence = np.zeros(shape, dtype="uint8")
    for href in hrefs:
        with rasterio.open(_signed(href)) as src, WarpedVRT(
            src, crs=crs, transform=transform, width=shape[1], height=shape[0],
            resampling=Resampling.nearest, src_nodata=255, nodata=0,
        ) as vrt:
            occurrence = np.maximum(occurrence, vrt.read(1))
    return occurrence


def read_bands(item, geom_wgs84, water_hrefs=None):
    """อ่านแบนด์ที่ต้องใช้เฉพาะบริเวณลำน้ำบนกริด 10 ม.

    คืนค่า dict: green, red, nir (ค่าสะท้อน, NaN = ไม่มีข้อมูล), scl, inside (mask ลำน้ำ),
    occurrence (เมื่อส่ง water_hrefs), transform, crs
    """
    with rasterio.open(_signed(item.assets["B04"].href)) as src:
        crs, ref_transform = src.crs, src.transform
        to_utm = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
        geom = shp_transform(to_utm, geom_wgs84)
        w = from_bounds(*geom.bounds, transform=ref_transform)
        col, row = math.floor(w.col_off), math.floor(w.row_off)
        win = Window(col, row, math.ceil(w.col_off + w.width) - col, math.ceil(w.row_off + w.height) - row)
        win = win.intersection(Window(0, 0, src.width, src.height))
        shape = (int(win.height), int(win.width))
        transform = src.window_transform(win)
        red_dn = src.read(1, window=win)

    roi_bounds = window_bounds(win, ref_transform)

    def read(asset, resampling=Resampling.nearest):
        with rasterio.open(_signed(item.assets[asset].href)) as src:
            w = from_bounds(*roi_bounds, transform=src.transform)
            return src.read(1, window=w, out_shape=shape, resampling=resampling)

    offset = _boa_offset(item)

    def reflectance(dn):
        out = (dn.astype("float32") - offset) / 10000.0
        out[dn == 0] = np.nan
        return out

    occurrence = read_water_occurrence(water_hrefs, crs, transform, shape) if water_hrefs else None

    return {
        "occurrence": occurrence,
        "green": reflectance(read("B03")),
        "red": reflectance(red_dn),
        "nir": reflectance(read("B08")),
        "scl": read("SCL"),
        "inside": geometry_mask([mapping(geom)], out_shape=shape, transform=transform, invert=True),
        "transform": transform,
        "crs": crs,
    }
