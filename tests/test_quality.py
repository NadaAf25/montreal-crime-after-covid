import numpy as np
import pandas as pd

import crime_utils as cu
from conftest import raw_rows, THEFT, MISCHIEF


def test_quality_report_counts(small_raw, write_csv):
    report = cu.quality_report(write_csv(small_raw))
    rows = report["Rows"]
    assert rows["Raw rows"] == 8
    assert rows["Invalid dates (dropped)"] == 1
    assert rows["Unrecognised categories (dropped)"] == 1
    assert rows["Rows kept after cleaning"] == 6
    assert report.loc["Raw rows", "% of raw rows"] == 100.0


def test_quality_report_counts_duplicates_without_removing_them(write_csv):
    row = (THEFT, "2020-05-01", "jour", 1, -73.6, 45.5)
    path = write_csv(raw_rows([row, row, (MISCHIEF, "2020-05-01", "jour", 1, -73.6, 45.5)]))
    report = cu.quality_report(path)
    assert report.loc["Exact duplicate rows (kept, counted only)", "Rows"] == 1
    assert report.loc["Rows kept after cleaning", "Rows"] == 3
    assert len(cu.load_crimes(path)) == 3          # duplicates are not removed


def test_quality_report_separates_missing_and_outside(write_csv):
    path = write_csv(raw_rows([
        (THEFT, "2020-05-01", "jour", 1, -73.6, 45.5),
        (THEFT, "2020-05-02", "jour", 1, np.nan, np.nan),
        (THEFT, "2020-05-03", "jour", 1, 0.0, 0.0),
    ]))
    rows = cu.quality_report(path)["Rows"]
    assert rows["Missing coordinates (kept, no map position)"] == 1
    assert rows["Coordinates outside the Montreal box (kept, no map position)"] == 1


def test_data_quality_percentages(load):
    df = load([
        (THEFT, "2020-01-01", -73.6, 45.5, 1),
        (THEFT, "2020-01-02", np.nan, np.nan, 1),
        (THEFT, "2020-01-03", -73.6, 45.5, np.nan),
        (THEFT, "2020-01-04", -73.6, 45.5, 1),
    ])
    summary = cu.data_quality(df)["Value"]
    assert summary["Records"] == "4"
    assert summary["Without usable location"] == "25.0%"
    assert summary["Without PDQ"] == "25.00%"


def test_missing_location_share(load):
    df = load([
        (THEFT, "2019-01-01", -73.6, 45.5, 1),
        (THEFT, "2019-01-02", np.nan, np.nan, 1),
        (MISCHIEF, "2020-01-01", -73.6, 45.5, 1),
        (MISCHIEF, "2020-01-02", -73.6, 45.5, 1),
    ])
    by_year = cu.missing_location_share(df, "YEAR")["% WITHOUT LOCATION"]
    assert by_year.loc[2019] == 50.0 and by_year.loc[2020] == 0.0
    table = cu.missing_location_share(df, "YEAR", "CATEGORY")
    assert table.loc[2019, "Vehicle theft"] == 50.0
