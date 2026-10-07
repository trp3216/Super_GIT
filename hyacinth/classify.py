"""จำแนกพิกเซลในลำน้ำเป็น น้ำเปิด / ผักตบชวา / อื่นๆ และคำนวณปริมาตร"""
import numpy as np

# ค่าใน raster ผลลัพธ์
OUTSIDE, CLOUD, WATER, HYACINTH, OTHER = 0, 1, 2, 3, 4

# Scene Classification Layer ของ Sentinel-2 ที่ถือว่า "มองเห็นพื้นผิว"
# 4 = พืช, 5 = ดิน/ไม่มีพืช, 6 = น้ำ, 7 = ไม่จัดกลุ่ม
CLEAR_SCL = (4, 5, 6, 7)


def _ratio(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        return (a - b) / (a + b)


def classify(green, red, nir, scl, inside, ndvi_min=0.35, ndwi_water_min=0.0):
    ndvi = _ratio(nir, red)
    ndwi = _ratio(green, nir)

    valid = inside & np.isin(scl, CLEAR_SCL) & np.isfinite(ndvi) & np.isfinite(ndwi)
    hyacinth = valid & (ndvi >= ndvi_min)
    water = valid & ~hyacinth & (ndwi >= ndwi_water_min)

    classes = np.full(inside.shape, OUTSIDE, dtype="uint8")
    classes[inside] = CLOUD
    classes[valid] = OTHER
    classes[water] = WATER
    classes[hyacinth] = HYACINTH
    return classes


def summarize(classes, pixel_area_m2):
    """นับพื้นที่ (ตร.ม.) ของแต่ละประเภทจาก raster ผลลัพธ์"""
    counts = np.bincount(classes.ravel(), minlength=5)
    area = counts * pixel_area_m2
    return {
        "river_m2": area[CLOUD:].sum(),
        "valid_m2": area[WATER:].sum(),
        "water_m2": area[WATER],
        "hyacinth_m2": area[HYACINTH],
        "other_m2": area[OTHER],
    }


def estimate_volume(hyacinth_m2, mat_thickness_m, wet_biomass_kg_m2):
    return {
        "volume_m3": hyacinth_m2 * mat_thickness_m,
        "biomass_t": hyacinth_m2 * wet_biomass_kg_m2 / 1000.0,
    }
