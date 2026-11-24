import numpy as np
import pandas as pd
import pytest

import crime_utils as cu
from conftest import THEFT, MISCHIEF


def frame(dates, categories=None):
    """Minimal frame with the columns the yearly and monthly helpers need."""
    dates = pd.to_datetime(pd.Series(dates))
    return pd.DataFrame({
        "DATE": dates,
        "YEAR": dates.dt.year,
        "MONTH": dates.dt.month,
        "CATEGORY": categories if categories is not None else "Vehicle theft",
    })


def test_yearly_table_counts_per_year_and_category():
    df = frame(["2019-01-05", "2019-02-05", "2020-01-05"], ["Burglary", "Burglary", "Mischief"])
    table = cu.yearly_table(df)
    assert table.loc[2019, "Burglary"] == 2
    assert table.loc[2020, "Mischief"] == 1
    assert table.loc[2020, "Burglary"] == 0


def test_index_to_baseline_is_100_in_the_base_year():
    table = pd.DataFrame({"A": [50, 100, 150], "B": [10, 20, 5]}, index=[2018, 2019, 2020])
    index = cu.index_to_baseline(table, 2019)
    assert (index.loc[2019] == 100).all()
    assert index.loc[2020, "A"] == 150 and index.loc[2018, "B"] == 50


def test_year_over_year_and_cagr():
    table = pd.DataFrame({"A": [100, 110, 121]}, index=[2019, 2020, 2021])
    assert cu.year_over_year(table)["A"].round(6).tolist()[1:] == [10.0, 10.0]
    assert cu.cagr(table, 2019, 2021)["A"] == pytest.approx(10.0)
    with pytest.raises(ValueError):
        cu.cagr(table, 2021, 2019)


def test_annual_variability():
    table = pd.DataFrame({"A": [100, 120, 90]}, index=[2019, 2020, 2021])
    out = cu.annual_variability(table, [2019, 2020, 2021])
    assert out.loc["A", "MEAN"] == pytest.approx(103.3, abs=0.1)
    assert out.loc["A", "LARGEST RISE (%)"] == 20.0
    assert out.loc["A", "LARGEST FALL (%)"] == -25.0


def test_year_to_date_compares_the_same_months():
    df = frame(["2019-01-10", "2019-03-10", "2019-11-10", "2020-02-10", "2020-12-10"])
    ytd = cu.year_to_date(df, through_month=3)
    assert ytd.loc[2019, "Vehicle theft"] == 2          # November is left out
    assert ytd.loc[2020, "Vehicle theft"] == 1          # December is left out


def test_weekday_shares_sum_to_100():
    df = frame(["2019-01-07", "2019-01-08", "2019-01-08"])      # Monday, Tuesday, Tuesday
    df["WEEKDAY"] = pd.Categorical(df["DATE"].dt.day_name(), categories=cu.WEEKDAYS, ordered=True)
    shares = cu.weekday_shares(df, "Vehicle theft", [2019])
    assert shares.sum() == pytest.approx(100)
    assert shares["Tuesday"] == pytest.approx(200 / 3)


# --- complete months -------------------------------------------------------
@pytest.mark.parametrize("last_date, expected", [
    ("2026-11-16", (2026, 10)),     # data stops mid-month: the previous month is complete
    ("2026-10-31", (2026, 9)),      # last day of October: October may still be incomplete
    ("2026-11-07", (2026, 10)),     # 7 days after the end of October: October is complete
    ("2026-11-05", (2026, 9)),      # only 5 days after: October is not yet confirmed
    ("2026-01-10", (2025, 12)),     # year boundary: December complete
    ("2026-01-03", (2025, 11)),     # year boundary: December not yet confirmed
])
def test_last_complete_month(last_date, expected):
    assert cu.last_complete_month(frame([last_date])) == expected


def test_last_covered_month_is_the_month_of_the_last_record():
    assert cu.last_covered_month(frame(["2026-10-31"])) == (2026, 10)


# --- monthly tools ---------------------------------------------------------
def test_year_month_matrix_and_same_month_change():
    df = frame(["2019-01-05", "2019-01-06", "2019-02-01", "2025-01-02", "2025-02-02", "2025-02-03"])
    matrix = cu.year_month_matrix(df)
    assert matrix.loc[2019, 1] == 2 and matrix.shape[1] == 12
    change = cu.same_month_change(df, 2019, 2025)
    assert change.loc[1, "CHANGE (%)"] == -50.0 and change.loc[2, "CHANGE (%)"] == 100.0


def test_monthly_counts_fills_every_month():
    df = frame(["2020-01-10", "2020-01-20", "2020-03-01"])
    monthly = cu.monthly_counts(df)
    assert monthly.loc["2020-01-01"] == 2 and monthly.loc["2020-02-01"] == 0


# --- interrupted time series ----------------------------------------------
def test_interrupted_time_series_recovers_a_known_level_drop():
    rng = np.random.default_rng(1)
    index = pd.date_range("2015-01-01", "2025-12-01", freq="MS")
    t = np.arange(len(index))
    season = 0.15 * np.sin(2 * np.pi * index.month / 12)
    level = np.where(index >= "2020-03-01", -0.25, 0.0)         # a 22% drop at the break
    y = np.exp(np.log(1000) + 0.001 * t + season + level + rng.normal(0, 0.02, len(t)))
    result = cu.interrupted_time_series(pd.Series(y, index=index))
    effect = result["table"].loc["Level change at the break", "EFFECT (%)"]
    assert effect == pytest.approx((np.exp(-0.25) - 1) * 100, abs=3)
    assert result["table"].loc["Level change at the break", "P-VALUE"] < 0.01
    assert result["n_months"] == len(index)
    assert (result["counterfactual"].iloc[-1] > result["fitted"].iloc[-1])


def test_interrupted_time_series_needs_positive_counts():
    index = pd.date_range("2018-01-01", periods=36, freq="MS")
    series = pd.Series(10.0, index=index)
    series.iloc[5] = 0
    with pytest.raises(ValueError):
        cu.interrupted_time_series(series, break_date="2019-06-01")
