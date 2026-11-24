import numpy as np
import pandas as pd
import pytest

import crime_utils as cu


def test_poisson_ci_matches_published_exact_values():
    # exact 95% intervals of a Poisson count (Garwood), e.g. from standard tables
    low, high = cu.poisson_ci([0, 10, 100])
    assert low[0] == 0 and high[0] == pytest.approx(3.689, abs=0.001)
    assert low[1] == pytest.approx(4.795, abs=0.001) and high[1] == pytest.approx(18.390, abs=0.001)
    assert low[2] == pytest.approx(81.37, abs=0.01) and high[2] == pytest.approx(121.63, abs=0.01)


def test_ci_gets_relatively_narrower_with_more_incidents():
    low, high = cu.poisson_ci([20, 2000])
    assert (high[0] - low[0]) / 20 > (high[1] - low[1]) / 2000


def test_rate_per_100k_series_and_frame_and_missing_years():
    population = pd.Series({2019: 2_000_000.0, 2020: 2_100_000.0})
    counts = pd.Series({2019: 4000, 2020: 4200, 2021: 5000})
    rates = cu.rate_per_100k(counts, population)
    assert rates[2019] == 200 and rates[2020] == 200
    assert np.isnan(rates[2021])                              # no population: no rate
    frame = cu.rate_per_100k(counts.to_frame("A"), population)
    assert frame.loc[2019, "A"] == 200


def test_rate_with_ci_columns_and_order():
    population = pd.Series({2019: 2_000_000.0})
    out = cu.rate_with_ci(pd.Series({2019: 4000}), population)
    assert out.loc[2019, "RATE"] == 200
    assert out.loc[2019, "LOW"] < 200 < out.loc[2019, "HIGH"]


def test_rate_ratio_detects_a_large_change_and_not_a_tiny_one():
    ratio, low, high = cu.rate_ratio(4000, 2e6, 6000, 2e6)
    assert ratio == pytest.approx(1.5) and low > 1
    ratio, low, high = cu.rate_ratio(40, 2e6, 41, 2e6)
    assert low < 1 < high                                      # indistinguishable from noise


def test_load_population_skips_empty_years(tmp_path):
    path = tmp_path / "pop.csv"
    path.write_text("year,population,status,source\n2019,,to fill,\n2021,2015879,final,ISQ\n")
    pop = cu.load_population(path)
    assert list(pop.index) == [2021] and pop[2021] == 2015879.0


def test_compare_years_counts_and_rates():
    table = pd.DataFrame({"A": [4000, 6000], "B": [100, 100]}, index=[2019, 2025])
    out = cu.compare_years(table, 2019, 2025)
    assert out.loc["A", "CHANGE (%)"] == 50.0 and out.loc["A", "CI LOW (%)"] > 0
    assert out.loc["B", "CHANGE (%)"] == 0.0 and out.loc["B", "CI LOW (%)"] < 0 < out.loc["B", "CI HIGH (%)"]
    assert "RATE CHANGE (%)" not in out.columns                       # no population given
    population = pd.Series({2019: 2.0e6, 2025: 2.2e6})
    with_pop = cu.compare_years(table, 2019, 2025, population)
    assert with_pop.loc["A", "RATE CHANGE (%)"] == pytest.approx((1.5 / 1.1 - 1) * 100, abs=0.1)
    # population known for only one of the two years: no rate columns
    assert "RATE CHANGE (%)" not in cu.compare_years(table, 2019, 2025, pd.Series({2025: 2.2e6})).columns
