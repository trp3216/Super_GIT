import numpy as np

from hyacinth.classify import CLOUD, HYACINTH, OTHER, OUTSIDE, WATER, classify, estimate_volume, summarize


def test_classify_and_summarize():
    # 5 พิกเซล: ผักตบ, น้ำ, ตลิ่ง, เมฆ, นอกลำน้ำ
    green = np.array([[0.08, 0.06, 0.10, 0.30, 0.08]], dtype="float32")
    red = np.array([[0.04, 0.04, 0.12, 0.30, 0.04]], dtype="float32")
    nir = np.array([[0.35, 0.02, 0.15, 0.32, 0.35]], dtype="float32")
    scl = np.array([[4, 6, 5, 9, 4]])
    inside = np.array([[True, True, True, True, False]])

    classes = classify(green, red, nir, scl, inside)
    assert classes.tolist() == [[HYACINTH, WATER, OTHER, CLOUD, OUTSIDE]]

    s = summarize(classes, 100.0)
    assert s["river_m2"] == 400
    assert s["valid_m2"] == 300
    assert s["hyacinth_m2"] == 100
    assert s["water_m2"] == 100


def test_estimate_volume():
    v = estimate_volume(1600.0, mat_thickness_m=0.5, wet_biomass_kg_m2=25.0)
    assert v["volume_m3"] == 800.0
    assert v["biomass_t"] == 40.0
