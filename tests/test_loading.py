import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

import crime_utils as cu
from conftest import raw_rows


def test_all_six_categories_are_translated(small_raw, write_csv):
    df = cu.load_crimes(write_csv(small_raw))
    assert set(df["CATEGORY"]) == set(cu.ALL_CATEGORIES)


def test_unknown_category_and_invalid_date_are_dropped(small_raw, write_csv):
    df = cu.load_crimes(write_csv(small_raw))
    assert len(df) == 6            # 8 raw rows - 1 unknown category - 1 invalid date


def test_latin1_encoding_is_read(small_raw, write_csv):
    df = cu.load_crimes(write_csv(small_raw, encoding="latin1"))
    assert "Vehicle theft" in set(df["CATEGORY"])
    assert len(df) == 6


def test_calendar_columns(small_raw, write_csv):
    df = cu.load_crimes(write_csv(small_raw))
    first = df.iloc[0]
    assert (first["YEAR"], first["MONTH"], str(first["WEEKDAY"])) == (2019, 3, "Friday")


def test_time_of_day_is_translated(small_raw, write_csv):
    df = cu.load_crimes(write_csv(small_raw))
    assert set(df["TIME_OF_DAY"]) == {"day", "evening", "night"}


# --- coordinate validation -------------------------------------------------
def test_coordinate_status_classes():
    lat = pd.Series([45.5, np.nan, 1.0, 45.5, "abc"])
    lon = pd.Series([-73.6, -73.6, 1.0, np.nan, -73.6])
    status = cu.coordinate_status(lat, lon)
    assert status.tolist() == ["ok", "missing", "outside box", "missing", "missing"]


def test_polygon_rejects_points_inside_the_box_but_outside_the_territory():
    boundary = Polygon([(-73.7, 45.4), (-73.5, 45.4), (-73.5, 45.6), (-73.7, 45.6)])
    lat = pd.Series([45.5, 45.5])
    lon = pd.Series([-73.6, -73.45])           # second point: in the box, outside the polygon
    status = cu.coordinate_status(lat, lon, boundary)
    assert status.tolist() == ["ok", "outside territory"]


def test_invalid_positions_are_set_to_nan(write_csv):
    raw = raw_rows([
        ("Méfait", "2020-01-01", "jour", 1, -73.6, 45.5),
        ("Méfait", "2020-01-02", "jour", 1, 0.0, 0.0),
        ("Méfait", "2020-01-03", "jour", 1, np.nan, np.nan),
    ])
    df = cu.load_crimes(write_csv(raw))
    assert df["HAS_LOCATION"].tolist() == [True, False, False]
    assert df.loc[~df["HAS_LOCATION"], ["LAT", "LON", "X_M", "Y_M"]].isna().all().all()


def test_metric_projection_is_in_metres():
    # two points 0.01 degree of latitude apart are about 1.1 km apart
    x, y = cu.project_to_metres([45.50, 45.51], [-73.57, -73.57])
    assert 1000 < abs(y[1] - y[0]) < 1250
    assert abs(x[1] - x[0]) < 50
    lat, lon = cu.metres_to_lat_lon(x, y)
    assert lat == pytest.approx([45.50, 45.51], abs=1e-6)
    assert lon == pytest.approx([-73.57, -73.57], abs=1e-6)


def test_missing_boundary_file_returns_none(tmp_path):
    assert cu.load_boundary(tmp_path / "does-not-exist.geojson") is None


def test_boundary_is_read_from_geojson(tmp_path):
    geojson = tmp_path / "b.geojson"
    geojson.write_text('{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},'
                       '"geometry":{"type":"Polygon","coordinates":'
                       '[[[-73.7,45.4],[-73.5,45.4],[-73.5,45.6],[-73.7,45.6],[-73.7,45.4]]]}}]}')
    boundary = cu.load_boundary(geojson)
    assert boundary.contains(__import__("shapely").geometry.Point(-73.6, 45.5))
