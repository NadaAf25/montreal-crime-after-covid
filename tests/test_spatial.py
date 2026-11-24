import numpy as np
import pandas as pd
import pytest

import crime_utils as cu
from conftest import THEFT, MISCHIEF


def rows_at(category, year, lon, lat, n, pdq=1):
    return [(category, f"{year}-06-{1 + i % 28:02d}", lon, lat, pdq) for i in range(n)]


# --- cell_changes ----------------------------------------------------------
def test_cell_changes_ranks_increase_decrease_and_pct(load):
    rows = (rows_at(THEFT, 2019, -73.57, 45.50, 10) + rows_at(THEFT, 2023, -73.57, 45.50, 30)   # +20
            + rows_at(THEFT, 2019, -73.70, 45.48, 40) + rows_at(THEFT, 2023, -73.70, 45.48, 10)  # -30
            + rows_at(THEFT, 2023, -73.62, 45.55, 5))                                           # new cell
    df = load(rows)
    out = cu.cell_changes(df, "Vehicle theft", 2019, 2023, top=10)
    assert out["CHANGE"].tolist() == [20, 5, -30]               # positive first, decrease last
    assert out.loc[0, "PCT_CHANGE"] == pytest.approx(200.0)
    assert np.isnan(out.loc[1, "PCT_CHANGE"])                   # no incident in 2019: no percent
    assert out.loc[2, "PCT_CHANGE"] == pytest.approx(-75.0)
    assert out.loc[0, "MAIN_PDQ"] == "PDQ 1"
    assert 45.4 < out.loc[0, "CENTRE_LAT"] < 45.6


def test_cell_changes_relative_ranking_ignores_tiny_bases(load):
    rows = (rows_at(THEFT, 2019, -73.57, 45.50, 1) + rows_at(THEFT, 2023, -73.57, 45.50, 5)      # +400%, 1 incident
            + rows_at(THEFT, 2019, -73.70, 45.48, 50) + rows_at(THEFT, 2023, -73.70, 45.48, 100))  # +100%
    df = load(rows)
    out = cu.cell_changes(df, "Vehicle theft", 2019, 2023, sort_by="PCT_CHANGE", min_base=20)
    assert len(out) == 1 and out.loc[0, "PCT_CHANGE"] == pytest.approx(100.0)


def test_cell_changes_ignores_incidents_without_position(load):
    rows = rows_at(THEFT, 2023, np.nan, np.nan, 10) + rows_at(THEFT, 2023, -73.57, 45.50, 3)
    df = load(rows)
    out = cu.cell_changes(df, "Vehicle theft", 2019, 2023)
    assert out["CHANGE"].sum() == 3


def test_grid_sensitivity_returns_one_row_per_size_and_full_overlap_for_the_reference(load):
    rows = (rows_at(THEFT, 2019, -73.57, 45.50, 5) + rows_at(THEFT, 2023, -73.57, 45.50, 60)
            + rows_at(THEFT, 2019, -73.70, 45.48, 5) + rows_at(THEFT, 2023, -73.70, 45.48, 40))
    out = cu.grid_sensitivity(load(rows), "Vehicle theft", 2019, 2023, sizes=(500, 1000, 2000), top=2)
    assert list(out.index) == [500, 1000, 2000]
    ref = out.loc[1000, "TOP CELLS OVERLAPPING THE REFERENCE TOP CELLS (%)"]
    assert ref == 100.0
    assert out.loc[500, "TOP CELLS OVERLAPPING THE REFERENCE TOP CELLS (%)"] == 100.0   # same two clusters


# --- concentration ---------------------------------------------------------
def test_gini_extremes():
    assert cu._gini([5, 5, 5, 5]) == pytest.approx(0.0)
    assert cu._gini([0, 0, 0, 100]) == pytest.approx(0.75)       # 1 - 1/n for n = 4
    assert np.isnan(cu._gini([]))


def test_concentration_shares_gini_and_hhi(load):
    # 100 intersections: one has 100 incidents, 99 have 1 each
    rows = rows_at(THEFT, 2020, -73.6000, 45.5000, 100)
    for i in range(99):
        rows.append((THEFT, "2020-07-01", -73.7 + i * 0.001, 45.45, 1))
    out = cu.concentration_by_year(load(rows))
    row = out.loc[2020]
    assert row["LOCATIONS"] == 100
    assert row["TOP 1% OF LOCATIONS"] == pytest.approx(100 / 199 * 100)
    assert row["HHI"] == pytest.approx(((100 / 199) ** 2 + 99 * (1 / 199) ** 2) * 10_000)
    assert 0.4 < row["GINI"] < 0.6


# --- Getis-Ord Gi* -----------------------------------------------------------
def test_fdr_adjustment_is_monotone_and_bounded():
    adjusted = cu._fdr_bh([0.001, 0.04, 0.03, 0.5])
    assert adjusted.max() <= 1 and (adjusted >= np.array([0.001, 0.04, 0.03, 0.5])).all()
    assert adjusted[0] == pytest.approx(0.004)


def test_gi_star_flags_a_dense_cluster_and_not_a_uniform_surface(load):
    rng = np.random.default_rng(0)
    rows = []
    # background: a broad area with a few thefts everywhere
    for lon in np.arange(-73.75, -73.45, 0.004):
        for lat in np.arange(45.45, 45.62, 0.003):
            rows.append((MISCHIEF, "2022-05-05", lon, lat, 1))      # fills the study area
            if rng.random() < 0.15:
                rows.append((THEFT, "2022-05-06", lon, lat, 1))
    # a strong cluster of thefts near the city centre
    rows += rows_at(THEFT, 2022, -73.570, 45.505, 400)
    result = cu.getis_ord_gi_star(load(rows), "Vehicle theft", 2022, cell_m=1000)
    hot = result[result["HOTSPOT"]]
    assert len(hot) >= 1
    top = result.iloc[0]
    assert abs(top["CENTRE_LON"] + 73.570) < 0.02 and abs(top["CENTRE_LAT"] - 45.505) < 0.02
    assert (result["P_FDR"] >= result["P"]).all()


def test_gi_star_uniform_counts_give_no_hotspot(load):
    rows = []
    for lon in np.arange(-73.75, -73.45, 0.004):
        for lat in np.arange(45.45, 45.62, 0.003):
            rows.append((THEFT, "2022-05-06", lon, lat, 1))
    result = cu.getis_ord_gi_star(load(rows), "Vehicle theft", 2022, cell_m=1000)
    assert not result["HOTSPOT"].any()
