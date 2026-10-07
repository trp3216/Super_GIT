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


def _read(base_dir, shapefile, query=None):
    gdf = gpd.read_file(base_dir / shapefile)
    if gdf.crs is None:
        raise ValueError(f"{shapefile}: ไม่มีข้อมูลระบบพิกัด (.prj) กรุณากำหนด CRS ให้ไฟล์")
    if query:
        gdf = gdf.query(query)
    if gdf.empty:
        raise ValueError(f"{shapefile}: ไม่พบ feature ที่ตรงกับ query {query!r}")
    return gdf


def load_river_geometry(river, base_dir):
    """คืนค่าขอบเขตลำน้ำเป็น geometry เดียวในพิกัด EPSG:4326"""
    gdf = _read(base_dir, river["shapefile"], river.get("query"))
    utm = gdf.estimate_utm_crs()
    gdf = gdf.to_crs(utm)

    buffer_m = river.get("buffer_m")
    if buffer_m:
        gdf["geometry"] = gdf.buffer(buffer_m)
    elif not gdf.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError(
            f"{river['name']}: shapefile เป็นเส้น (Line) ต้องกำหนด buffer_m เพื่อแปลงเป็นพื้นที่ลำน้ำ"
        )
    geom = unary_union(gdf.geometry.values)

    clip = river.get("clip")
    if clip:
        clip_gdf = _read(base_dir, clip["shapefile"], clip.get("query")).to_crs(utm)
        geom = geom.intersection(unary_union(clip_gdf.geometry.values))
        if geom.is_empty:
            raise ValueError(f"{river['name']}: ลำน้ำไม่ซ้อนทับกับขอบเขต clip")

    return gpd.GeoSeries([geom], crs=utm).to_crs(4326).iloc[0]
