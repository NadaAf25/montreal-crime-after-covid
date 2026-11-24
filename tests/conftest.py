"""Shared helpers: small synthetic SPVM-style files for the tests."""
import pandas as pd
import pytest

import crime_utils as cu

RAW_COLUMNS = ["CATEGORIE", "DATE", "QUART", "PDQ", "LONGITUDE", "LATITUDE"]

THEFT = "Vol de véhicule à moteur"
MISCHIEF = "Méfait"
BURGLARY = "Introduction"


def raw_rows(rows):
    """Raw SPVM-style DataFrame from (category, date, quart, pdq, lon, lat) tuples."""
    return pd.DataFrame(rows, columns=RAW_COLUMNS)


@pytest.fixture
def write_csv(tmp_path):
    def _write(df, encoding="utf-8-sig"):
        path = tmp_path / "actes.csv"
        df.to_csv(path, index=False, encoding=encoding)
        return path
    return _write


@pytest.fixture
def load(write_csv):
    """Build a clean DataFrame (through load_crimes) from (category, date, lon, lat, pdq) tuples."""
    def _load(rows, boundary=None):
        raw = raw_rows([(c, d, "jour", pdq, lon, lat) for c, d, lon, lat, pdq in rows])
        return cu.load_crimes(write_csv(raw), boundary=boundary)
    return _load


@pytest.fixture
def small_raw():
    """One valid row per category, plus one unknown category and one invalid date."""
    return raw_rows([
        ("Vol de véhicule à moteur", "2019-03-01", "jour", 21, -73.57, 45.50),
        ("Vol dans / sur véhicule à moteur", "2019-03-02", "soir", 20, -73.58, 45.49),
        ("Introduction", "2019-03-03", "nuit", 38, -73.59, 45.52),
        ("Méfait", "2019-03-04", "jour", 12, -73.60, 45.53),
        ("Vols qualifiés", "2019-03-05", "soir", 7, -73.70, 45.48),
        ("Infractions entrainant la mort", "2019-03-06", "nuit", 5, -73.80, 45.46),
        ("Categorie inconnue", "2019-03-07", "jour", 5, -73.80, 45.46),
        ("Méfait", "pas une date", "jour", 5, -73.80, 45.46),
    ])
