"""Helpers for the "Montreal Crime After COVID" analysis (Nada Afiri).

The module loads the SPVM open-data file, cleans it, and provides the
calculations used in the notebook (baseline index, location changes,
concentration of incidents, year-to-date comparison).
"""

import unicodedata

import folium
import numpy as np
import pandas as pd

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

# bounding box that contains the island of Montreal
_LAT_RANGE = (45.3, 45.8)
_LON_RANGE = (-74.1, -73.3)

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
# Loading and cleaning
# ---------------------------------------------------------------------------
def _plain(text):
    """Lower-case text without accents."""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return nfkd.encode("ascii", "ignore").decode().lower().strip()


def _english_category(label):
    """English name of an SPVM category; NaN if the label is not in CATEGORY_MAP."""
    return CATEGORY_MAP.get(_plain(label), np.nan)


def load_crimes(path, cell_size=0.01):
    """Read the SPVM csv and return a clean, analysis-ready DataFrame.

    Added columns: YEAR, MONTH, WEEKDAY, HAS_LOCATION and the grid cell
    (CELL_LAT, CELL_LON) of each incident. `cell_size` is in degrees
    (0.01 is roughly 1.1 km north-south and 0.8 km east-west in Montreal).
    """
    raw = None
    for encoding in ("utf-8-sig", "latin1"):
        try:
            raw = pd.read_csv(path, encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    raw.columns = [c.strip().upper() for c in raw.columns]
    raw = raw.rename(columns={"LATITUDE": "LAT", "LONGITUDE": "LON", "LONG": "LON"})

    pdq = pd.to_numeric(raw["PDQ"], errors="coerce").astype("Int64")
    df = pd.DataFrame({
        "CATEGORY": raw["CATEGORIE"].map(_english_category),
        "DATE": pd.to_datetime(raw["DATE"], errors="coerce"),
        "TIME_OF_DAY": raw["QUART"].map(lambda v: _TIME_RULES.get(_plain(v), np.nan)),
        "PDQ": pdq,
        "LAT": raw["LAT"],
        "LON": raw["LON"],
    }).dropna(subset=["CATEGORY", "DATE"])

    df["YEAR"] = df["DATE"].dt.year
    df["MONTH"] = df["DATE"].dt.month
    df["WEEKDAY"] = pd.Categorical(df["DATE"].dt.day_name(), categories=WEEKDAYS, ordered=True)

    # missing positions are stored with placeholder values: use a bounding box
    inside = df["LAT"].between(*_LAT_RANGE) & df["LON"].between(*_LON_RANGE)
    df["HAS_LOCATION"] = inside
    df.loc[~inside, ["LAT", "LON"]] = np.nan

    df["CELL_LAT"] = (np.floor(df["LAT"] / cell_size) * cell_size).round(3)
    df["CELL_LON"] = (np.floor(df["LON"] / cell_size) * cell_size).round(3)
    return df.reset_index(drop=True)


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


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def yearly_table(df, categories=ALL_CATEGORIES):
    """Incidents per year (rows) and category (columns)."""
    table = df.pivot_table(index="YEAR", columns="CATEGORY", values="DATE",
                           aggfunc="count", fill_value=0)
    return table[[c for c in categories if c in table.columns]]


def index_to_baseline(table, base_year):
    """Rescale each column so that `base_year` equals 100."""
    return table.div(table.loc[base_year]) * 100


def cell_changes(df, category, year_a, year_b, top=15):
    """Grid cells with the largest increase of `category` from year_a to year_b."""
    sub = df[df["HAS_LOCATION"] & (df["CATEGORY"] == category)
             & df["YEAR"].isin([year_a, year_b])]
    keys = ["CELL_LAT", "CELL_LON"]

    counts = (sub.groupby(keys + ["YEAR"]).size().unstack(fill_value=0)
                 .reindex(columns=[year_a, year_b], fill_value=0))
    counts["CHANGE"] = counts[year_b] - counts[year_a]

    main_pdq = (sub.dropna(subset=["PDQ"]).groupby(keys)["PDQ"]
                   .agg(lambda s: "PDQ {}".format(int(s.mode().iat[0]))))
    out = counts.join(main_pdq.rename("MAIN_PDQ")).sort_values("CHANGE", ascending=False)
    out = out.head(top).reset_index()
    out["LABEL"] = (out["CELL_LAT"].map("{:.2f}".format) + ", "
                    + out["CELL_LON"].map("{:.2f}".format) + " (" + out["MAIN_PDQ"].fillna("?") + ")")
    return out


def concentration_by_year(df, shares=(0.01, 0.05)):
    """Share of incidents located at the busiest 1% / 5% of intersections."""
    rows = []
    for year, group in df[df["HAS_LOCATION"]].groupby("YEAR"):
        counts = (group.groupby(["LAT", "LON"]).size()
                       .sort_values(ascending=False).to_numpy())
        row = {"YEAR": year, "LOCATIONS": len(counts)}
        for share in shares:
            k = max(1, int(round(len(counts) * share)))
            row["TOP {:.0f}% OF LOCATIONS".format(share * 100)] = counts[:k].sum() / counts.sum() * 100
        rows.append(row)
    return pd.DataFrame(rows).set_index("YEAR")


def last_complete_month(df):
    """(year, month) of the most recent month that is fully covered by the data."""
    last = df["DATE"].max().normalize()
    if last == (last + pd.offsets.MonthEnd(0)).normalize():
        return last.year, last.month
    previous = last.replace(day=1) - pd.Timedelta(days=1)
    return previous.year, previous.month


def year_to_date(df, through_month):
    """Incidents from January to `through_month`, per year and category."""
    sub = df[df["MONTH"] <= through_month]
    table = sub.pivot_table(index="YEAR", columns="CATEGORY", values="DATE",
                            aggfunc="count", fill_value=0)
    return table[[c for c in ALL_CATEGORIES if c in table.columns]]


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
def change_map(changes, filename="map_hotspots.html"):
    """Folium map with one circle per grid cell, sized by the increase."""
    fmap = folium.Map(
        location=[45.55, -73.62], zoom_start=11,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri",
    )
    half = 0.005  # half a cell: draw circles at the cell centre
    for row in changes.itertuples():
        folium.CircleMarker(
            location=[row.CELL_LAT + half, row.CELL_LON + half],
            radius=max(5, float(np.sqrt(max(row.CHANGE, 0))) * 2),
            color="#b2182b", fill=True, fill_opacity=0.6,
            popup="{}: {:+d}".format(row.LABEL, int(row.CHANGE)),
        ).add_to(fmap)
    fmap.save(filename)   # standalone copy: open it in a browser
    return fmap           # returned in case it is needed in a notebook cell