"""Helpers for the "Montreal Crime After COVID" analysis (Nada Afiri).

The module loads the SPVM open-data file, checks and cleans it, and provides the
calculations used in the notebook: baseline index, rates per 100,000 residents,
confidence intervals, interrupted time series, monthly comparisons, grid-based
location changes (metric projection), concentration indicators and Getis-Ord
Gi* hotspots.

Important about the data: in the SPVM file, DATE is the date the event was
*reported* to the police and QUART is the part of the day of the *report*
(official data dictionary of the "Actes criminels" dataset). Weekday and
time-of-day analyses therefore describe reporting patterns.
"""

import json
import unicodedata
from pathlib import Path

import folium
import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALL_CATEGORIES = [
    "Vehicle contents or parts theft",
    "Burglary",
    "Mischief",
    "Vehicle theft",
    "Robbery",
    "Offenses causing death",
]
# Offenses causing death are too rare (~30 per year) for percentage trends
MAIN_CATEGORIES = ALL_CATEGORIES[:5]

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIMES_OF_DAY = ["day", "evening", "night"]

# first-pass check: bounding box that contains the island of Montreal.
# A polygon of the territory (see load_boundary) is used on top of it when available.
_LAT_RANGE = (45.3, 45.8)
_LON_RANGE = (-74.1, -73.3)

# Metric projection used for the grid: NAD83(CSRS) / MTM zone 8 (EPSG:2950),
# the projection the SPVM itself uses for its X and Y columns.
METRIC_CRS = "EPSG:2950"

# SPVM label (lower case, accents removed) -> English name.
# Source: column CATEGORIE of the "Actes criminels" dataset (6 distinct values).
CATEGORY_MAP = {
    "vol de vehicule a moteur": "Vehicle theft",
    "vol dans / sur vehicule a moteur": "Vehicle contents or parts theft",
    "introduction": "Burglary",
    "mefait": "Mischief",
    "vols qualifies": "Robbery",
    "infractions entrainant la mort": "Offenses causing death",
}
_TIME_RULES = {"jour": "day", "soir": "evening", "nuit": "night"}


# ---------------------------------------------------------------------------
# Loading, validation and cleaning
# ---------------------------------------------------------------------------
def _plain(text):
    """Lower-case text without accents."""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return nfkd.encode("ascii", "ignore").decode().lower().strip()


def _english_category(label):
    """English name of an SPVM category; NaN if the label is not in CATEGORY_MAP."""
    return CATEGORY_MAP.get(_plain(label), np.nan)


def _read_raw(path):
    """Read the SPVM csv as is, with upper-case column names."""
    raw = None
    for encoding in ("utf-8-sig", "latin1"):
        try:
            raw = pd.read_csv(path, encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    raw.columns = [c.strip().upper() for c in raw.columns]
    return raw.rename(columns={"LATITUDE": "LAT", "LONGITUDE": "LON", "LONG": "LON"})


def load_boundary(path="data/montreal_boundary.geojson"):
    """Territory of the Montreal agglomeration as one shapely geometry (WGS84).

    Reads a GeoJSON file (see download_data.py) and merges all its polygons.
    Returns None when the file does not exist, in which case the validation
    falls back to the bounding box only.
    """
    path = Path(path)
    if not path.exists():
        return None
    from shapely.geometry import shape
    from shapely.ops import unary_union

    gj = json.loads(path.read_text(encoding="utf-8"))
    features = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
    geoms = [shape(f["geometry"] if "geometry" in f else f) for f in features]
    return unary_union([g.buffer(0) for g in geoms])


def coordinate_status(lat, lon, boundary=None):
    """Classify each coordinate pair.

    Returns a Series of strings:
    * "missing": latitude or longitude is empty or not a number;
    * "outside box": numeric but outside the rectangle around Montreal
      (placeholder values such as 0 or 1 end up here);
    * "outside territory": inside the box but outside the polygon `boundary`
      (only checked when a boundary is given);
    * "ok": usable position.
    """
    lat = pd.to_numeric(lat, errors="coerce")
    lon = pd.to_numeric(lon, errors="coerce")
    missing = lat.isna() | lon.isna()
    in_box = lat.between(*_LAT_RANGE) & lon.between(*_LON_RANGE)

    status = pd.Series("ok", index=lat.index, dtype=object)
    status[~missing & ~in_box] = "outside box"
    if boundary is not None:
        import shapely

        candidates = ~missing & in_box
        inside = pd.Series(False, index=lat.index)
        if candidates.any():
            inside[candidates] = shapely.intersects_xy(
                boundary, lon[candidates].to_numpy(), lat[candidates].to_numpy())
        status[candidates & ~inside] = "outside territory"
    status[missing] = "missing"
    return status


def project_to_metres(lat, lon):
    """Convert WGS84 latitude/longitude to metres (METRIC_CRS). NaN stays NaN."""
    from pyproj import Transformer

    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    x = np.full(lat.shape, np.nan)
    y = np.full(lat.shape, np.nan)
    ok = np.isfinite(lat) & np.isfinite(lon)
    if ok.any():
        transformer = Transformer.from_crs("EPSG:4326", METRIC_CRS, always_xy=True)
        x[ok], y[ok] = transformer.transform(lon[ok], lat[ok])
    return x, y


def metres_to_lat_lon(x, y):
    """Inverse of project_to_metres."""
    from pyproj import Transformer

    transformer = Transformer.from_crs(METRIC_CRS, "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    return lat, lon


def load_crimes(path, boundary=None):
    """Read the SPVM csv and return a clean, analysis-ready DataFrame.

    Rows with an unknown category or an invalid date are dropped (quality_report
    counts them). Added columns: YEAR, MONTH, WEEKDAY, LOCATION_STATUS,
    HAS_LOCATION and the metric coordinates X_M, Y_M (metres, EPSG:2950).
    Positions that are not "ok" (see coordinate_status) are set to NaN.
    `boundary` is an optional polygon from load_boundary().
    """
    raw = _read_raw(path)

    pdq = pd.to_numeric(raw["PDQ"], errors="coerce").astype("Int64")
    df = pd.DataFrame({
        "CATEGORY": raw["CATEGORIE"].map(_english_category),
        "DATE": pd.to_datetime(raw["DATE"], errors="coerce"),
        "TIME_OF_DAY": raw["QUART"].map(lambda v: _TIME_RULES.get(_plain(v), np.nan)),
        "PDQ": pdq,
        "LAT": pd.to_numeric(raw["LAT"], errors="coerce"),
        "LON": pd.to_numeric(raw["LON"], errors="coerce"),
    }).dropna(subset=["CATEGORY", "DATE"])

    df["YEAR"] = df["DATE"].dt.year
    df["MONTH"] = df["DATE"].dt.month
    df["WEEKDAY"] = pd.Categorical(df["DATE"].dt.day_name(), categories=WEEKDAYS, ordered=True)

    df["LOCATION_STATUS"] = coordinate_status(df["LAT"], df["LON"], boundary)
    df["HAS_LOCATION"] = df["LOCATION_STATUS"] == "ok"
    df.loc[~df["HAS_LOCATION"], ["LAT", "LON"]] = np.nan

    df["X_M"], df["Y_M"] = project_to_metres(df["LAT"], df["LON"])
    return df.reset_index(drop=True)


def quality_report(path, boundary=None):
    """Check the raw file and report what the cleaning keeps, drops or flags.

    Returns a DataFrame with the number of rows and the share of the raw file
    for each check. Nothing is removed here: exact duplicates are only counted,
    because the file has no incident identifier and two different incidents can
    share a date, a category and an intersection.
    """
    raw = _read_raw(path)
    total = len(raw)

    bad_date = pd.to_datetime(raw["DATE"], errors="coerce").isna()
    bad_category = raw["CATEGORIE"].map(_english_category).isna()
    bad_time = raw["QUART"].map(lambda v: _TIME_RULES.get(_plain(v), np.nan)).isna()
    no_pdq = pd.to_numeric(raw["PDQ"], errors="coerce").isna()
    status = coordinate_status(raw["LAT"], raw["LON"], boundary)

    rows = [
        ("Raw rows", total),
        ("Invalid dates (dropped)", int(bad_date.sum())),
        ("Unrecognised categories (dropped)", int(bad_category.sum())),
        ("Rows kept after cleaning", int((~bad_date & ~bad_category).sum())),
        ("Exact duplicate rows (kept, counted only)", int(raw.duplicated().sum())),
        ("Missing coordinates (kept, no map position)", int((status == "missing").sum())),
        ("Coordinates outside the Montreal box (kept, no map position)",
         int((status == "outside box").sum())),
    ]
    if boundary is not None:
        rows.append(("Coordinates outside the territory polygon (kept, no map position)",
                     int((status == "outside territory").sum())))
    rows += [
        ("Missing PDQ (kept)", int(no_pdq.sum())),
        ("Unrecognised time of day (kept)", int(bad_time.sum())),
    ]
    out = pd.DataFrame(rows, columns=["Check", "Rows"]).set_index("Check")
    out["% of raw rows"] = (out["Rows"] / total * 100).round(2)
    return out


def data_quality(df):
    """One-row-per-indicator summary of the loaded file."""
    return pd.Series({
        "Records": f"{len(df):,}",
        "First date": df["DATE"].min().date(),
        "Last date": df["DATE"].max().date(),
        "Without usable location": f"{1 - df['HAS_LOCATION'].mean():.1%}",
        "Without PDQ": f"{df['PDQ'].isna().mean():.2%}",
        "Without time of day": f"{df['TIME_OF_DAY'].isna().mean():.2%}",
    }, name="Value").to_frame()


def missing_location_share(df, rows, columns=None):
    """Percentage of incidents without a usable location.

    Grouped by the column `rows` (e.g. "YEAR") and, if given, `columns`
    (e.g. "CATEGORY"). Use it to check that the geographic analysis is not
    biased because some years or crime types lose more coordinates than others.
    """
    missing = (~df["HAS_LOCATION"]).astype(float) * 100
    if columns is None:
        out = missing.groupby(df[rows], observed=True).mean()
        return out.round(1).rename("% WITHOUT LOCATION").to_frame()
    out = missing.groupby([df[rows], df[columns]], observed=True).mean().unstack()
    return out.round(1)


# ---------------------------------------------------------------------------
# Yearly calculations
# ---------------------------------------------------------------------------
def yearly_table(df, categories=ALL_CATEGORIES):
    """Incidents per year (rows) and category (columns)."""
    table = df.pivot_table(index="YEAR", columns="CATEGORY", values="DATE",
                           aggfunc="count", fill_value=0)
    return table[[c for c in categories if c in table.columns]]


def index_to_baseline(table, base_year):
    """Rescale each column so that `base_year` equals 100."""
    return table.div(table.loc[base_year]) * 100


def year_over_year(table):
    """Year-over-year change in percent: (N_t - N_{t-1}) / N_{t-1} * 100."""
    return table.pct_change() * 100


def cagr(table, start_year, end_year):
    """Compound annual growth rate in percent between two years."""
    years = end_year - start_year
    if years <= 0:
        raise ValueError("end_year must be after start_year")
    return ((table.loc[end_year] / table.loc[start_year]) ** (1 / years) - 1) * 100


def annual_variability(table, years):
    """Year-to-year variability of each column over `years` (list of years).

    Columns: mean level, standard deviation, coefficient of variation (%),
    and the largest rise and fall between two consecutive years (%).
    """
    sub = table.loc[list(years)]
    yoy = sub.pct_change().dropna(how="all") * 100
    return pd.DataFrame({
        "MEAN": sub.mean(),
        "STD": sub.std(),
        "CV (%)": sub.std() / sub.mean() * 100,
        "LARGEST RISE (%)": yoy.max(),
        "LARGEST FALL (%)": yoy.min(),
    }).round(1)


def weekday_shares(df, category, years):
    """Share (%) of a category's incidents reported on each weekday, over `years`."""
    sub = df[(df["CATEGORY"] == category) & df["YEAR"].isin(list(years))]
    counts = sub["WEEKDAY"].value_counts().reindex(WEEKDAYS, fill_value=0)
    return counts / counts.sum() * 100


# ---------------------------------------------------------------------------
# Population, rates and confidence intervals
# ---------------------------------------------------------------------------
def load_population(path="reference/population_montreal.csv"):
    """Annual population (July 1) as a Series indexed by year.

    Years whose population is empty in the file are left out, so the rate
    functions return NaN for them instead of a wrong number.
    """
    pop = pd.read_csv(path, comment="#")
    pop = pop.dropna(subset=["population"])
    return pop.set_index("year")["population"].astype(float).sort_index()


def rate_per_100k(counts, population):
    """Incidents per 100,000 residents. NaN for years without population."""
    pop = population.reindex(counts.index)
    if isinstance(counts, pd.DataFrame):
        return counts.div(pop, axis=0) * 100_000
    return counts / pop * 100_000


def poisson_ci(counts, alpha=0.05):
    """Exact (Garwood) confidence interval of a Poisson count.

    Returns (low, high). It assumes incidents are independent events with a
    constant average rate; real crime data is usually more variable than that,
    so the interval is a lower bound on the true uncertainty.
    """
    k = np.asarray(counts, dtype=float)
    low = np.where(k > 0, stats.chi2.ppf(alpha / 2, 2 * np.maximum(k, 1)) / 2, 0.0)
    high = stats.chi2.ppf(1 - alpha / 2, 2 * (k + 1)) / 2
    return low, high


def rate_with_ci(counts, population, alpha=0.05):
    """Rate per 100,000 residents with its Poisson confidence interval.

    `counts` is a Series indexed by year. The population is treated as known.
    """
    pop = population.reindex(counts.index)
    low, high = poisson_ci(counts.to_numpy(), alpha)
    return pd.DataFrame({
        "INCIDENTS": counts,
        "POPULATION": pop,
        "RATE": counts / pop * 100_000,
        "LOW": low / pop.to_numpy() * 100_000,
        "HIGH": high / pop.to_numpy() * 100_000,
    })


def rate_ratio(k_a, pop_a, k_b, pop_b, alpha=0.05):
    """Ratio of the rate in period b to the rate in period a, with a CI.

    Log-normal approximation for two independent Poisson counts. Returns
    (ratio, low, high); a CI that excludes 1 means the difference is larger
    than Poisson noise alone (not a proof of a real change in crime).
    """
    ratio = (k_b / pop_b) / (k_a / pop_a)
    se = np.sqrt(1 / k_a + 1 / k_b)
    z = stats.norm.ppf(1 - alpha / 2)
    return ratio, ratio * np.exp(-z * se), ratio * np.exp(z * se)


def compare_years(table, year_a, year_b, population=None):
    """Change between two years for each column of a yearly table.

    Always gives the change in the number of incidents with a 95% interval
    (population assumed equal). When `population` (a Series indexed by year)
    has both years, it also gives the change of the rate per resident with its
    interval. An interval that excludes 0 means the change is larger than
    Poisson noise alone.
    """
    has_pop = (population is not None and year_a in population.index
               and year_b in population.index)
    rows = {}
    for column in table.columns:
        k_a, k_b = table.loc[year_a, column], table.loc[year_b, column]
        row = {str(year_a): k_a, str(year_b): k_b}
        ratio, low, high = rate_ratio(k_a, 1.0, k_b, 1.0)
        row.update({"CHANGE (%)": (ratio - 1) * 100,
                    "CI LOW (%)": (low - 1) * 100, "CI HIGH (%)": (high - 1) * 100})
        if has_pop:
            ratio, low, high = rate_ratio(k_a, population[year_a], k_b, population[year_b])
            row.update({"RATE CHANGE (%)": (ratio - 1) * 100,
                        "RATE CI LOW (%)": (low - 1) * 100, "RATE CI HIGH (%)": (high - 1) * 100})
        rows[column] = row
    out = pd.DataFrame(rows).T.round(1)
    out[[str(year_a), str(year_b)]] = out[[str(year_a), str(year_b)]].astype(int)
    return out


# ---------------------------------------------------------------------------
# Monthly analysis and interrupted time series
# ---------------------------------------------------------------------------
def monthly_counts(df, category=None):
    """Incidents per calendar month (index = first day of the month)."""
    sub = df if category is None else df[df["CATEGORY"] == category]
    return sub.groupby(pd.Grouper(key="DATE", freq="MS")).size().rename("INCIDENTS")


def year_month_matrix(df, category=None):
    """Incidents per year (rows) and month (columns 1-12)."""
    sub = df if category is None else df[df["CATEGORY"] == category]
    return (sub.groupby(["YEAR", "MONTH"]).size().unstack(fill_value=0)
               .reindex(columns=range(1, 13), fill_value=0))


def same_month_change(df, year_a, year_b, category=None):
    """Compare each calendar month of year_b with the same month of year_a."""
    matrix = year_month_matrix(df, category)
    out = pd.DataFrame({year_a: matrix.loc[year_a], year_b: matrix.loc[year_b]})
    out["CHANGE (%)"] = ((out[year_b] / out[year_a] - 1) * 100).round(1)
    out.index.name = "MONTH"
    return out


def interrupted_time_series(monthly, break_date="2020-03-01", maxlags=12):
    """Segmented regression of monthly counts around a break date.

    Model: log(count) = const + trend + level_change + slope_change + month
    dummies. `trend` is the pre-break monthly trend, `level_change` the jump at
    the break and `slope_change` the change of trend afterwards (all on the log
    scale, shown as percent). Standard errors are robust to autocorrelation
    (Newey-West, `maxlags` months). Returns a dict with the coefficient table,
    the Durbin-Watson statistic of the residuals, and the fitted and
    counterfactual (no break) series in incidents per month.

    This describes a temporal association with the break date; it does not
    prove that the pandemic caused the change.
    """
    import statsmodels.api as sm
    from statsmodels.stats.stattools import durbin_watson

    y = monthly.astype(float)
    if (y <= 0).any():
        raise ValueError("monthly counts must be positive to use the log scale")
    brk = pd.Timestamp(break_date)
    t = np.arange(len(y))
    t_break = int(np.searchsorted(y.index, brk))
    post = (y.index >= brk).astype(float)

    X = pd.DataFrame({
        "trend": t.astype(float),
        "level_change": post,
        "slope_change": np.where(post == 1, t - t_break, 0).astype(float),
    }, index=y.index)
    months = pd.get_dummies(pd.Series(y.index.month, index=y.index), prefix="m",
                            drop_first=True).astype(float)
    X = sm.add_constant(pd.concat([X, months], axis=1))

    model = sm.OLS(np.log(y), X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    conf = model.conf_int()
    terms = ["trend", "level_change", "slope_change"]
    table = pd.DataFrame({
        "COEF": model.params[terms],
        "EFFECT (%)": (np.exp(model.params[terms]) - 1) * 100,
        "LOW (%)": (np.exp(conf.loc[terms, 0]) - 1) * 100,
        "HIGH (%)": (np.exp(conf.loc[terms, 1]) - 1) * 100,
        "P-VALUE": model.pvalues[terms],
    })
    table.index = ["Monthly trend before the break", "Level change at the break",
                   "Change of monthly trend after the break"]

    counterfactual = X.copy()
    counterfactual[["level_change", "slope_change"]] = 0
    return {
        "table": table,
        "durbin_watson": float(durbin_watson(model.resid)),
        "fitted": np.exp(model.fittedvalues).rename("FITTED"),
        "counterfactual": np.exp(model.predict(counterfactual)).rename("NO BREAK"),
        "n_months": len(y),
    }


# ---------------------------------------------------------------------------
# Complete months
# ---------------------------------------------------------------------------
def last_covered_month(df):
    """(year, month) of the last calendar month that has any data."""
    last = df["DATE"].max()
    return last.year, last.month


def last_complete_month(df, lag_days=7):
    """(year, month) of the most recent month considered complete.

    The file only tells us the last date that has data, not which months the
    source has finished publishing. A month is therefore counted as complete
    only when the data extends at least `lag_days` days beyond its end. With
    the default of 7 days, a file ending on October 31 still treats October as
    incomplete (late records may still arrive); a file ending on November 16
    treats October as complete.
    """
    cutoff = df["DATE"].max().normalize() - pd.Timedelta(days=lag_days)
    month_end = cutoff.replace(day=1) + pd.offsets.MonthEnd(0)
    if month_end <= cutoff:
        return month_end.year, month_end.month
    previous = cutoff.replace(day=1) - pd.Timedelta(days=1)
    return previous.year, previous.month


def year_to_date(df, through_month):
    """Incidents from January to `through_month`, per year and category."""
    sub = df[df["MONTH"] <= through_month]
    table = sub.pivot_table(index="YEAR", columns="CATEGORY", values="DATE",
                            aggfunc="count", fill_value=0)
    return table[[c for c in ALL_CATEGORIES if c in table.columns]]


# ---------------------------------------------------------------------------
# Geography: grid cells, concentration, hotspots
# ---------------------------------------------------------------------------
def cell_changes(df, category, year_a, year_b, top=15, cell_m=1000,
                 sort_by="CHANGE", min_base=0):
    """Square grid cells (side `cell_m` metres) with the largest change of `category`.

    Columns: counts in year_a and year_b, CHANGE (absolute), PCT_CHANGE (NaN
    when the cell had no incident in year_a), cell centre (CENTRE_LAT,
    CENTRE_LON), the PDQ that most often covers the cell and a LABEL.
    `sort_by="PCT_CHANGE"` ranks by relative change; cells with fewer than
    `min_base` incidents in year_a are then left out, because +400% from 1 to 5
    incidents is a small volume.
    """
    sub = df[df["HAS_LOCATION"] & (df["CATEGORY"] == category)
             & df["YEAR"].isin([year_a, year_b])].copy()
    sub["CELL_X"] = np.floor(sub["X_M"] / cell_m) * cell_m
    sub["CELL_Y"] = np.floor(sub["Y_M"] / cell_m) * cell_m
    keys = ["CELL_X", "CELL_Y"]

    counts = (sub.groupby(keys + ["YEAR"]).size().unstack(fill_value=0)
                 .reindex(columns=[year_a, year_b], fill_value=0))
    counts["CHANGE"] = counts[year_b] - counts[year_a]
    counts["PCT_CHANGE"] = np.where(counts[year_a] > 0,
                                    counts["CHANGE"] / counts[year_a].replace(0, np.nan) * 100,
                                    np.nan)

    main_pdq = (sub.dropna(subset=["PDQ"]).groupby(keys)["PDQ"]
                   .agg(lambda s: "PDQ {}".format(int(s.mode().iat[0]))))
    out = counts.join(main_pdq.rename("MAIN_PDQ"))
    if sort_by == "PCT_CHANGE":
        out = out[out[year_a] >= max(min_base, 1)]
    out = out.sort_values(sort_by, ascending=False).head(top).reset_index()

    lat, lon = metres_to_lat_lon(out["CELL_X"] + cell_m / 2, out["CELL_Y"] + cell_m / 2)
    out["CENTRE_LAT"], out["CENTRE_LON"] = lat, lon
    out["LABEL"] = (out["CENTRE_LAT"].map("{:.3f}".format) + ", "
                    + out["CENTRE_LON"].map("{:.3f}".format)
                    + " (" + out["MAIN_PDQ"].fillna("?") + ")")
    return out


def grid_sensitivity(df, category, year_a, year_b, sizes=(500, 1000, 2000),
                     top=15, reference=1000):
    """Do the biggest increases stay in the same places when the cell size changes?

    For each cell size: number of cells that had incidents, share of the total
    increase (sum of positive changes) held by the `top` cells, and the share
    of those top cells that overlap one of the top cells of the `reference`
    size.
    """
    def top_cells(size):
        sub = df[df["HAS_LOCATION"] & (df["CATEGORY"] == category)
                 & df["YEAR"].isin([year_a, year_b])]
        cx = np.floor(sub["X_M"] / size) * size
        cy = np.floor(sub["Y_M"] / size) * size
        counts = (sub.assign(CX=cx, CY=cy).groupby(["CX", "CY", "YEAR"]).size()
                     .unstack(fill_value=0).reindex(columns=[year_a, year_b], fill_value=0))
        change = counts[year_b] - counts[year_a]
        best = change.sort_values(ascending=False).head(top)
        total_up = change[change > 0].sum()
        return len(counts), best, (best[best > 0].sum() / total_up * 100 if total_up else np.nan)

    _, ref_best, _ = top_cells(reference)
    ref_xy = np.array(ref_best.index.tolist(), dtype=float)

    rows = []
    for size in sizes:
        n_cells, best, share = top_cells(size)
        xy = np.array(best.index.tolist(), dtype=float)
        half = (size + reference) / 2
        overlaps = [
            bool(((np.abs(ref_xy[:, 0] - x) < half) & (np.abs(ref_xy[:, 1] - y) < half)).any())
            for x, y in xy
        ]
        rows.append({
            "CELL SIZE (m)": size,
            "CELLS WITH INCIDENTS": n_cells,
            "TOP CELLS' SHARE OF THE INCREASE (%)": round(share, 1),
            "TOP CELLS OVERLAPPING THE REFERENCE TOP CELLS (%)":
                round(float(np.mean(overlaps)) * 100, 1),
        })
    return pd.DataFrame(rows).set_index("CELL SIZE (m)")


def _gini(values):
    """Gini coefficient of non-negative values (0 = equal, 1 = one place has everything)."""
    v = np.sort(np.asarray(values, dtype=float))
    n = len(v)
    if n == 0 or v.sum() == 0:
        return np.nan
    index = np.arange(1, n + 1)
    return float((2 * (index * v).sum()) / (n * v.sum()) - (n + 1) / n)


def concentration_by_year(df, shares=(0.01, 0.05)):
    """Concentration of incidents at intersections, per year.

    Columns: number of intersections with at least one incident, share of
    incidents at the busiest 1% / 5% of them, Gini coefficient and
    Herfindahl-Hirschman index (sum of squared shares, scaled to 0-10,000) of
    the distribution of incidents across intersections.
    """
    rows = []
    for year, group in df[df["HAS_LOCATION"]].groupby("YEAR"):
        counts = (group.groupby(["LAT", "LON"]).size()
                       .sort_values(ascending=False).to_numpy())
        row = {"YEAR": year, "LOCATIONS": len(counts)}
        for share in shares:
            k = max(1, int(round(len(counts) * share)))
            row["TOP {:.0f}% OF LOCATIONS".format(share * 100)] = counts[:k].sum() / counts.sum() * 100
        row["GINI"] = _gini(counts)
        row["HHI"] = float(((counts / counts.sum()) ** 2).sum() * 10_000)
        rows.append(row)
    return pd.DataFrame(rows).set_index("YEAR")


def _fdr_bh(p_values):
    """Benjamini-Hochberg adjusted p-values."""
    p = np.asarray(p_values, dtype=float)
    order = np.argsort(p)
    ranked = p[order] * len(p) / (np.arange(len(p)) + 1)
    adjusted = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty_like(adjusted)
    out[order] = np.minimum(adjusted, 1.0)
    return out


def getis_ord_gi_star(df, category, year, cell_m=1000, alpha=0.05):
    """Getis-Ord Gi* hotspots of one category in one year, on a square grid.

    Study area: every cell that has at least one located incident of any
    category in that year (cells without any incident, such as water or empty
    land, are left out). Neighbourhood: the cell itself and its 8 surrounding
    cells (queen contiguity, binary weights). Returns one row per cell with the
    count, z-score, p-value, Benjamini-Hochberg adjusted p-value and the labels
    HOTSPOT (z > 0 and adjusted p < alpha) / COLDSPOT.

    A hotspot here means a cell whose neighbourhood has significantly more
    incidents than the island average. It is about spatial clustering, not
    about how much an area changed.
    """
    sub = df[df["HAS_LOCATION"] & (df["YEAR"] == year)].copy()
    sub["CELL_X"] = (np.floor(sub["X_M"] / cell_m)).astype(int)
    sub["CELL_Y"] = (np.floor(sub["Y_M"] / cell_m)).astype(int)
    cells = sub.groupby(["CELL_X", "CELL_Y"]).size().rename("ALL").to_frame()
    cells["COUNT"] = (sub[sub["CATEGORY"] == category].groupby(["CELL_X", "CELL_Y"]).size()
                      .reindex(cells.index, fill_value=0))
    cells = cells.reset_index()

    ix, iy = cells["CELL_X"].to_numpy(), cells["CELL_Y"].to_numpy()
    w = ((np.abs(ix[:, None] - ix[None, :]) <= 1)
         & (np.abs(iy[:, None] - iy[None, :]) <= 1)).astype(float)
    x = cells["COUNT"].to_numpy(dtype=float)
    n = len(x)
    mean = x.mean()
    s = np.sqrt((x ** 2).mean() - mean ** 2)
    sum_w = w.sum(axis=1)
    denom = s * np.sqrt((n * sum_w - sum_w ** 2) / (n - 1))   # binary weights: sum(w^2) = sum(w)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (w @ x - mean * sum_w) / denom
    z = np.where(np.isfinite(z), z, 0.0)

    p = 2 * stats.norm.sf(np.abs(z))
    cells["Z"] = z
    cells["P"] = p
    cells["P_FDR"] = _fdr_bh(p)
    cells["HOTSPOT"] = (cells["Z"] > 0) & (cells["P_FDR"] < alpha)
    cells["COLDSPOT"] = (cells["Z"] < 0) & (cells["P_FDR"] < alpha)

    lat, lon = metres_to_lat_lon((cells["CELL_X"] + 0.5) * cell_m, (cells["CELL_Y"] + 0.5) * cell_m)
    cells["CENTRE_LAT"], cells["CENTRE_LON"] = lat, lon
    return cells.sort_values("Z", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
def change_map(changes, filename="docs/map_hotspots.html"):
    """Folium map with one circle per grid cell, sized by the increase."""
    fmap = folium.Map(
        location=[45.55, -73.62], zoom_start=11,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri",
    )
    for row in changes.itertuples():
        pct = "" if pd.isna(row.PCT_CHANGE) else " ({:+.0f}%)".format(row.PCT_CHANGE)
        folium.CircleMarker(
            location=[row.CENTRE_LAT, row.CENTRE_LON],
            radius=max(5, float(np.sqrt(max(row.CHANGE, 0))) * 2),
            color="#b2182b", fill=True, fill_opacity=0.6,
            popup="{}: {:+d}{}".format(row.LABEL, int(row.CHANGE), pct),
        ).add_to(fmap)
    Path(filename).parent.mkdir(parents=True, exist_ok=True)
    fmap.save(filename)   # standalone copy: open it in a browser
    return fmap           # returned in case it is needed in a notebook cell
