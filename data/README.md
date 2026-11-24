# Data folder

The files in this folder are **not** tracked by git (see `.gitignore`). Download them with:

```bash
python download_data.py
```

| File | Content | Source |
| --- | --- | --- |
| `actes-criminels.csv` | One row per incident reported to the SPVM, 2015 to the present | [Actes criminels](https://donnees.montreal.ca/dataset/actes-criminels) (CC-BY 4.0) |
| `montreal_boundary.geojson` | Boundary of the Montreal agglomeration (WGS 84), used to check coordinates | [Limites administratives de l'agglomération de Montréal](https://donnees.montreal.ca/dataset/limites-administratives-agglomeration) |
| `DOWNLOAD_INFO.json` | Source link, download date, size and SHA-256 of each file (written by the script) | |

## Columns of `actes-criminels.csv` used here

| Column | Official description | Used as |
| --- | --- | --- |
| `CATEGORIE` | Nature of the event | `CATEGORY` (6 values, translated in `crime_utils.CATEGORY_MAP`) |
| `DATE` | Date the event was **reported** to the SPVM (YYYY-MM-DD) | `DATE`, `YEAR`, `MONTH`, `WEEKDAY` |
| `QUART` | Time of day (day / evening / night) of the **report** | `TIME_OF_DAY` |
| `PDQ` | Number of the neighbourhood police station covering the area | `PDQ` |
| `LATITUDE`, `LONGITUDE` | Position moved to an intersection (WGS 84) | `LAT`, `LON` |
| `X`, `Y` | Same position in the MTM zone 8 projection (SRID 2950) | not read; recomputed from latitude/longitude |

`DATE` and `QUART` describe the report, not necessarily the event, so weekday and time-of-day
results are reporting patterns. Wording quoted from the official data dictionary.

## Expected size

About 365,000 rows (≈ 33 MB) for January 2015 to mid-November 2026. The portal updates the file daily.
