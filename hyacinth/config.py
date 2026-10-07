from pathlib import Path

import geopandas as gpd
import yaml
from shapely import unary_union


def load_config(path):
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_base_dir"] = path.resolve().parent
    return cfg


def _read(base_dir, shapefile, query=None, encoding=None):
    gdf = gpd.read_file(base_dir / shapefile, encoding=encoding)
    if gdf.crs is None:
        raise ValueError(f"{shapefile}: ไม่มีข้อมูลระบบพิกัด (.prj) กรุณากำหนด CRS ให้ไฟล์")
    if query:
        gdf = gdf.query(query)
    if gdf.empty:
        raise ValueError(f"{shapefile}: ไม่พบ feature ที่ตรงกับ query {query!r}")
    return gdf


def load_river_geometry(river, base_dir):
    """คืนค่าขอบเขตลำน้ำเป็น geometry เดียวในพิกัด EPSG:4326"""
    gdf = _read(base_dir, river["shapefile"], river.get("query"), river.get("encoding"))
    utm = gdf.estimate_utm_crs()
    gdf = gdf.to_crs(utm)

    banks_close_m = river.get("banks_close_m")
    buffer_m = river.get("buffer_m")
    if banks_close_m:
        # เส้นตลิ่ง 2 ฝั่ง: ขยายแล้วหดกลับ (morphological closing) เพื่อเติมผิวน้ำระหว่างตลิ่ง
        lines = unary_union(gdf.geometry.values)
        geom = lines.buffer(banks_close_m, cap_style="flat").buffer(-banks_close_m)
        max_bank_distance_m = river.get("max_bank_distance_m")
        if max_bank_distance_m:
            # closing อาจเติมผืนดินระหว่างร่องน้ำ/ในโค้งแคบ — ตัดส่วนที่ไกลจากตลิ่งเกินครึ่งความกว้างลำน้ำออก
            geom = geom.intersection(lines.buffer(max_bank_distance_m))
    elif buffer_m:
        geom = unary_union(gdf.buffer(buffer_m).values)
    elif gdf.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        geom = unary_union(gdf.geometry.values)
    else:
        raise ValueError(
            f"{river['name']}: shapefile เป็นเส้น (Line) ต้องกำหนด banks_close_m (เส้นตลิ่ง 2 ฝั่ง) "
            "หรือ buffer_m (เส้นกลางลำน้ำ)"
        )

    shrink_m = river.get("shrink_m")
    if shrink_m:
        # หดขอบเข้าเล็กน้อย ลดพิกเซลที่ปนกับต้นไม้ริมตลิ่ง
        geom = geom.buffer(-shrink_m)

    clip = river.get("clip")
    if clip:
        clip_gdf = _read(base_dir, clip["shapefile"], clip.get("query"), clip.get("encoding")).to_crs(utm)
        geom = geom.intersection(unary_union(clip_gdf.geometry.values))
        if geom.is_empty:
            raise ValueError(f"{river['name']}: ลำน้ำไม่ซ้อนทับกับขอบเขต clip")

    return gpd.GeoSeries([geom], crs=utm).to_crs(4326).iloc[0]
