"""ค้นหาและอ่านภาพ Sentinel-2 L2A จาก Microsoft Planetary Computer (ฟรี ไม่ต้องสมัครบัญชี)"""
import math
from collections import defaultdict

import numpy as np
import planetary_computer
import pystac_client
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.windows import Window, bounds as window_bounds, from_bounds
from shapely.geometry import mapping
from shapely.ops import transform as shp_transform

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def search(geom, start, end, collection="sentinel-2-l2a", max_scene_cloud=60):
    client = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    items = client.search(
        collections=[collection],
        intersects=mapping(geom),
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


def _boa_offset(item):
    # ตั้งแต่ processing baseline 04.00 (ม.ค. 2022) ค่า DN ถูกบวก offset 1000
    try:
        return 1000 if float(item.properties.get("s2:processing_baseline", "0")) >= 4.0 else 0
    except ValueError:
        return 0


def read_bands(item, geom_wgs84):
    """อ่านแบนด์ที่ต้องใช้เฉพาะบริเวณลำน้ำบนกริด 10 ม.

    คืนค่า dict: green, red, nir (ค่าสะท้อน, NaN = ไม่มีข้อมูล), scl, inside (mask ลำน้ำ),
    transform, crs
    """
    with rasterio.open(item.assets["B04"].href) as src:
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
        with rasterio.open(item.assets[asset].href) as src:
            w = from_bounds(*roi_bounds, transform=src.transform)
            return src.read(1, window=w, out_shape=shape, resampling=resampling)

    offset = _boa_offset(item)

    def reflectance(dn):
        out = (dn.astype("float32") - offset) / 10000.0
        out[dn == 0] = np.nan
        return out

    return {
        "green": reflectance(read("B03")),
        "red": reflectance(red_dn),
        "nir": reflectance(read("B08")),
        "scl": read("SCL"),
        "inside": geometry_mask([mapping(geom)], out_shape=shape, transform=transform, invert=True),
        "transform": transform,
        "crs": crs,
    }
