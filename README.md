# Montreal Crime After COVID

Did crime in Montreal go back to its pre-pandemic level, and where did it change? An analysis of the open data of the Service de police de la Ville de Montréal (SPVM), 2015 to 2026, with exact confidence intervals, an interrupted time series and a spatial hotspot analysis.

![Incidents by crime type, 2019 = 100](images/index_2019.png)

**Interactive results:** [HTML report](docs/report.html) · [hotspot map](docs/map_hotspots.html)
(open the files from a clone of the repository, or enable GitHub Pages on the `docs/` folder)

## Key findings

All figures are computed by the notebook from the data.

- **Volume:** 29,832 incidents reported in 2025 against 27,155 in 2019 (+9.9%).
- **Vehicle theft is the category that moves differently:** 4,170 in 2019, a peak of 11,528 in 2023 (+176%), then 6,579 in 2025 (+58% vs 2019, 95% interval +52% to +64%).
- **COVID:** no clear level change in total monthly incidents in March 2020 (-1.5%, 95% CI -17.5% to +17.7%); categories differ.
- **Where:** the largest increase in vehicle theft is in the cell centred on 45.504, -73.555. Top cells stay mostly the same with 500 m cells (80% overlap) and less with 2 km cells (53%).
- **Concentration:** the busiest 1% of intersections hold 9.8% of located incidents in 2025 (7.8% in 2019).
- **2026 (January to October, data up to 22 November 2026):** -2.8% vs 2025, +8.6% vs 2019. These figures change when the data is downloaded again, because the portal updates the file daily.

## Method

- Counts with exact Poisson (Garwood) 95% intervals; change between years with a rate-ratio interval.
- Interrupted time series on log monthly counts (trend, level and slope change, month dummies, Newey-West errors).
- Square grid in metres (EPSG:2950) with a sensitivity check on cell size; Getis-Ord Gi* hotspots with Benjamini-Hochberg correction; Gini and HHI concentration.
- Data quality report: duplicates, missing and out-of-territory positions, and how unevenly positions are missing.

## Limitations

- The data counts incidents **reported** to the police; date and time are those of the report, not of the offence.
- About 17% of incidents have no usable position, unevenly by crime type and police station (7% for burglary to 22% for vehicle contents theft in 2025). Maps understate the real counts.
- A single break in March 2020 is a crude description of some series (vehicle theft surges later). Residuals are strongly autocorrelated (Durbin-Watson 0.47).
- Rates per 100,000 residents need the population file (see below).

## Project structure

```
Montreal-Crime-After-COVID.ipynb   the analysis (run top to bottom)
crime_utils.py                     tested functions used by the notebook
download_data.py                   downloads the data from the open data portal
reference/population_montreal.csv  population by year (to complete)
tests/                             pytest tests
data/                              downloaded data (not versioned)
docs/                              HTML report and map
images/                            figures used in this README
```

## Reproduce

```powershell
pip install -r requirements.txt
python download_data.py
jupyter notebook Montreal-Crime-After-COVID.ipynb   # Restart & Run All
```

Tests: `pip install -r requirements-dev.txt` then `pytest`. CI runs them on Python 3.11 to 3.13. Developed with Python 3.14, pandas 3, numpy 2.

Plotly is pinned below version 7 in `requirements.txt`: in the exported HTML report, Plotly 7 does not draw the circles of the maps over the map tiles.

To export the report (the charts and maps load Plotly and the map tiles from the internet, so open it online): `jupyter nbconvert --to html --execute --ExecutePreprocessor.timeout=900 --output-dir docs --output report Montreal-Crime-After-COVID.ipynb`. Without `--execute` the charts are missing.

**Population:** fill 2015-2020 in `reference/population_montreal.csv` (Institut de la statistique du Québec, Montréal agglomeration). Without it, rates are shown from 2021 only.

## Technologies

Python, pandas, numpy, scipy, statsmodels, pyproj, shapely, plotly, folium, pytest, GitHub Actions.

## Sources

- SPVM, *Actes criminels*, Ville de Montréal open data portal (CC-BY 4.0): https://donnees.montreal.ca/dataset/actes-criminels
- Ville de Montréal, *Limites administratives de l'agglomération*.
- Institut de la statistique du Québec, population estimates.