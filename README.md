# UrbanPlus: District Population Growth Forecasting

## What it is

UrbanPlus estimates and forecasts population growth for districts in Rwanda using
satellite-based population data. It combines official district boundaries with
WorldPop population grids to build a yearly population history from 2000 to 2020,
then uses that history to forecast future growth and checks the forecast against
the 2022 national census.

## Why it exists

Africa's cities are growing faster than planning can keep up: more than 700 million
new urban residents are expected across the continent by 2050. In Rwanda, districts
like Gasabo (Kigali) are growing far faster than secondary cities like Musanze, and
planners need to know where population is heading to decide where to build schools,
roads, clinics, and housing. Censuses happen only once every ten years, so UrbanPlus
tests whether freely available satellite data can fill the gaps between them.

## Results

Trained on WorldPop estimates (2000 to 2020) and checked against the 2022 census:

| District | Predicted 2022 | Census 2022 | Error |
|---|---|---|---|
| Gasabo | 946,247 | 879,505 | +7.6% |
| Musanze | 449,337 | 476,522 | -5.7% |

- Log-linear regression was the best model for both districts (2020 test errors of
  -7.0% for Gasabo and -1.0% for Musanze), because it captures compounding growth.
- Random Forest failed (-28% for Gasabo by 2020) because tree models cannot predict
  beyond the range they were trained on.
- Between 2000 and 2020, Gasabo grew about 2.8x while Musanze grew about 1.4x.

## How it works

1. **Load districts:** reads Rwanda's district boundaries and keeps Gasabo and Musanze
2. **Build population table:** sums WorldPop population pixels inside each district
   for every year (zonal statistics)
3. **Validate:** trains a log-linear model on 2000 to 2020, predicts 2022, and
   compares the prediction to the census
4. **Save:** writes results to CSV files and a SQLite database

All steps live in `src/pipeline.py`. Exploration notebooks are in `notebooks/`.

## Project structure

```
UrbanPlus_API/
├── data/
│   ├── raw/              downloaded data (not in the repo)
│   └── processed/        pipeline outputs (CSV files)
├── notebooks/            day-by-day exploration
├── reports/              charts
├── src/
│   └── pipeline.py       the full pipeline
├── requirements.txt
└── README.md
```

## How to run it

```bash
git clone https://github.com/MAcDen34/UrbanPlus_API.git
cd UrbanPlus_API
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Download the data into `data/raw/` (not included in the repo, about 230 MB):

- District boundaries: [HDX COD-AB Rwanda](https://data.humdata.org/dataset/cod-ab-rwa),
  unzip into `data/raw/boundaries/`
- Population rasters: [WorldPop](https://hub.worldpop.org/geodata/listing?id=29),
  files `rwa_ppp_2000.tif` to `rwa_ppp_2020.tif` into `data/raw/worldpop/`

Then run:

```bash
python src/pipeline.py
```

Results appear in `data/processed/`, and the database in `data/processed/database.db`.

Example query:

```bash
sqlite3 data/processed/database.db "SELECT * FROM population WHERE district = 'Gasabo' AND year = 2015;"
```

## Limitations

- The main source of error is the input data, not the model: WorldPop runs high for
  Gasabo and low for Musanze compared to the census, and the model inherits that bias.
- Gasabo's growth rate is accelerating, so a constant-rate model still underestimates
  its most recent years.
- Only two districts so far.

## Calibration experiment (Sprint 3)

WorldPop estimates were calibrated against the 2012 census (RPHC4) by multiplying
each district's series by the ratio census_2012 / worldpop_2012, keeping the 2022
census untouched as the final test.

| District | 2022 error (original) | 2022 error (calibrated) |
|---|---|---|
| Gasabo | +7.6% | +2.3% |
| Musanze | -5.7% | -6.9% |

Calibration fixes WorldPop's **level** but not its **growth rate**. Comparing annual
growth rates shows WorldPop's speed is wrong in opposite directions:

| District | Census growth (2012-2022) | WorldPop growth (2012-2020) |
|---|---|---|
| Gasabo | 5.20% per year | 5.94% per year (too fast) |
| Musanze | 2.61% per year | 1.95% per year (too slow) |

Hypothesis: WorldPop overstates growth in urban districts and understates it in
rural ones. This needs testing across all 30 districts.

Correcting the growth rate requires a second census point before the test year.
The 2002 census exists, but no official figures by current district boundaries
were found (checked: NISR RPHC4 thematic report on population size). Using the
2022 census to correct growth would be data leakage. A data request has been
sent to NISR.

## Next steps

- Extend to all 30 districts
- Serve results through a FastAPI layer reading from the SQLite database

## Data sources

- District boundaries: NISR via [HDX COD-AB Rwanda](https://data.humdata.org/dataset/cod-ab-rwa)
- Population estimates: [WorldPop](https://hub.worldpop.org/geodata/listing?id=29)
- Census: National Institute of Statistics of Rwanda (NISR), 2022 Population and Housing Census
