# Montreal Crime After COVID: Trends, Recovery and Hotspots (2015 - 2025)

Analysis of crime reported to the Montreal Police Department (SPVM), by **Nada Afiri**.

## Question

What happened to crime in Montreal after the COVID-19 shock, and has it returned to its 2019 level?

1. Compared with 2019, which crime types are higher or lower in 2025?
2. How large is the vehicle theft surge, when did it start, and when do these thefts happen?
3. Which parts of the island account for the largest increases in vehicle theft?
4. Do crimes follow different weekly and night-time patterns, and have they shifted?
5. Are incidents concentrated in a few locations, and is that changing?
6. How does 2026 so far compare with the same months of earlier years?

## Data

[Montreal Open Data Portal - Actes criminels](https://donnees.montreal.ca/dataset/actes-criminels) (SPVM).
Save the csv as `data/actes-criminels.csv` (the `data/` folder is git-ignored). The file used here covers 2015-01-01 to mid-November 2026; 2015 - 2025 are the complete years analysed.

## Run

```bash
pip install -r requirements.txt
jupyter notebook Montreal-Crime-After-COVID.ipynb
```

Requires Python 3.9 or newer.

## Files

| File | Content |
| --- | --- |
| `Montreal-Crime-After-COVID.ipynb` | Analysis and charts |
| `crime_utils.py` | Loading, cleaning and calculation helpers |
| `requirements.txt` | Python dependencies |
| `map_hotspots.html` | Standalone interactive map of the vehicle theft hotspots ([open the map](https://nadaaf25.github.io/montreal-crime-after-covid/map_hotspots.html)) |

## Key findings

* 2025 has 29,832 reported incidents, **9.9% more than 2019** (27,155). The lowest year is 2020 (25,460) and the highest is 2015 (35,609).
* **Vehicle theft** is the category furthest above its 2019 level in 2025 (**+57.8%**). It peaked in 2023 (11,528 incidents, +176% vs 2019) and has fallen since (8,661 in 2024, 6,579 in 2025).
* Robbery is +15.7% vs 2019; burglary is −4.7%; misdemeanor +4.0%; vehicle contents or parts theft +0.7%.
* The largest vehicle theft increases are in a few grid cells in the east-centre of the island and in the west (near Pointe-Claire).
* The busiest 1% of locations account for 9.8% of incidents in 2025, against 7.8% in 2019 and 11.1% in 2023.
* January to October 2026: **−3.0% vs 2025, +8.4% vs 2019** (vehicle theft −7.1% vs 2025, +50.7% vs 2019).
* Vehicle theft used to fall at the weekend (11.4% on Saturday and 10.2% on Sunday in 2015–2019); in 2022–2025 it is spread almost evenly over the week (13.3% and 14.3%).

## Limitations

* Counts incidents *reported to the police*, not rates per inhabitant.
* About 17% of rows have no usable location; locations are moved to intersections.
* PDQ boundaries changed over the period, so the geographic analysis uses a regular grid instead.
* "Offenses causing death" includes manslaughter and criminal negligence, not only murder.
* The "date" is the date of the report, which may differ from the date of the event.
