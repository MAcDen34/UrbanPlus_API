# UrbanPlus API

Population forecasts for all 30 districts of Rwanda, served through a REST API and a browser dashboard. I built it solo over 13 weeks at ALU.

The forecasts are fitted on WorldPop gridded population estimates for 2000 to 2020 and checked against the 2022 census. Every prediction comes with an uncertainty range and a short note on how far the satellite data for that district can be trusted.

The most useful thing I found along the way wasn't a better model, it was where the error comes from. That's the first section below.

---

## The main finding

**About 79% of the forecast error comes from the input data, not from the model.**

I tested four model forms against the 2022 census. They all landed within 0.6 percentage points of each other:

| Model | Mean abs error | Mean signed error | Within 10% |
| --- | --- | --- | --- |
| log-linear (baseline) | **9.81%** | +6.25% | 20 / 30 |
| recent-weighted | 10.08% | +6.93% | 21 / 30 |
| recent-window 2010+ | 10.39% | +7.64% | 20 / 30 |
| log-quadratic | 9.85% | +6.33% | 20 / 30 |

That similarity was the clue. If changing the shape of the curve barely moves the result, the shape probably isn't the problem.

WorldPop's 2020 figure is an observation, not a forecast. Comparing it straight to the 2022 census shows how far the input is from the truth before any modelling happens:

| | Mean absolute error |
| --- | --- |
| WorldPop 2020 vs 2022 census (input data) | 7.76% |
| Forecast vs 2022 census (total) | 9.81% |
| Added by the model | 2.05% |

The two error series correlate at r = 0.979, so the forecast error is mostly the input error carried through.

This is why the other model forms didn't help. It also puts a floor under any model that is fitted to one district's own WorldPop history: none of them gets below roughly 7.76%. The only way under it is to learn the data's systematic bias from other districts, which is what the spatial correction further down does (7.07%).

One detail about the signed error. It averages only +1.75%, with WorldPop reading high in 18 districts and low in 12. So the national total is about right and the mistakes are in how population is split between districts. Eastern Province is overstated, Bugesera and Rwamagana are understated. That's what you'd expect from a gridded product that spreads a national projection out over space.

To reproduce:

```bash
python src/compare_model_forms.py
python src/analyse_error_source.py
```

---

## Reliability bands

Since the error follows input quality and not district size or growth rate, I band each district by how closely WorldPop's 2020 figure matches the 2022 census:

| Band | Districts | Mean input error | Mean forecast error |
| --- | --- | --- | --- |
| reliable (5% or less) | 13 | 2.22% | 3.97% |
| moderate (12% or less) | 10 | 8.55% | 9.18% |
| weak (over 12%) | 7 | 16.93% | 21.57% |

Each prediction returns a directional caveat instead of a bare label. "Low confidence" tells a planner to distrust a number but not which way it's wrong, and the direction is the useful part:

```json
"reliability": {
  "band": "weak",
  "data_error_pct": 25.4,
  "likely_skew": "overstates",
  "note": "Satellite estimates read 25.4% above the 2022 census here, so this forecast most likely overstates. Read it as an upper bound."
}
```

---

## Spatial correction

The system fits one model per district from that district's own history, so there's nothing to transfer between districts and a normal spatial holdout doesn't apply. The correction is different. Each training district shows how far its naive forecast lands from the census, and if that gap can be predicted from district characteristics, an unseen district can be corrected using only what the others taught us.

I predict the log of `census / naive forecast` from four features: log population in 2020, total growth 2000 to 2020, deceleration (early growth rate minus late growth rate) and population density. I hold out whole districts, not years: six folds, 25 districts for training and 5 held out each time, repeated over five random seeds.

| Model | Mean abs error | Spread across seeds |
| --- | --- | --- |
| uncorrected baseline | 9.81% | n/a |
| ridge | **7.07%** | ± 0.28 |
| random forest | 8.91% | ± 0.43 |

That's an improvement of 2.74 points against a seed spread of 0.28, so one lucky split isn't driving it.

The per-district tables below come from a single split (seed 1). The API serves corrections built from out-of-fold predictions averaged over all five seeds, which score 6.91% overall with 19 districts improved and 11 worse. The pattern is the same either way.

It works on districts the model never saw during their own fold:

| District | Uncorrected | Corrected |
| --- | --- | --- |
| Nyagatare | +37.1% | −1.3% |
| Kayonza | +24.9% | −1.1% |
| Gatsibo | +25.1% | +6.7% |

The standardised ridge coefficients show where the signal is:

```
log_pop_2020    +0.0080
growth_total    -0.0715
deceleration    +0.0105
density         +0.0448
```

`growth_total` is far ahead of the rest. I added deceleration because I suspected districts that boomed early and then slowed would be the ones the trend line overshoots, but it barely contributes. The link is with how much a district grew in total, not with the shape of that growth.

No census value goes into the features. All four come from WorldPop rasters and the shapefile geometry, and the census only appears as the target.

### Where it backfires

In the seed-1 run, twenty districts improved and ten got worse, and the ten aren't random:

| District | Uncorrected | Corrected |
| --- | --- | --- |
| Rwamagana | −7.9% | −17.8% |
| Bugesera | −10.2% | −19.4% |
| Kamonyi | −0.2% | −6.5% |

All of these were already underpredicting. The model learned "high growth means bring the forecast down" from the majority of districts, which overshoot, so it pushes a downward correction onto districts that needed the opposite. The mean error improves because a few huge errors get rescued, while many small errors get a bit worse.

So the correction knows how big the adjustment should be but not which direction. Splitting the districts by which way WorldPop is wrong shows it clearly. In the 18 districts where WorldPop reads at or above the 2022 census, the correction improved 17 and averaged +7.2 points (pulled up by a few large wins such as Nyagatare). In the 12 where it reads below the census, it made 10 worse and averaged −3.5 points. The correction pushes forecasts down whichever way the input was wrong, so it hurts exactly where WorldPop already under-reads. Rwamagana and Bugesera, the two worst cases, sit furthest below the census among the ten that got worse (−13.9% and −14.7%), and together they account for about 44% of the accuracy lost across the ten in the seed-1 run.

That split uses the census to decide which group a district is in, so it explains the pattern but can't be used to switch the correction on or off. Scoring a rule built on it against the same census would be circular. A real fix would need a feature that shows which way WorldPop errs in a district and doesn't need the census.

Because of this, the API doesn't swap the correction in. `/predict`, `/forecast` and `/export` return the plain forecast as the main figure with the corrected one beside it, and each district gets an `advice` field: `recommended` where WorldPop reads at or above the census, `use_with_caution` where it reads below. The corrections the API serves come from out-of-fold predictions averaged over the five seeds (`src/build_corrections.py`), so no district is corrected by a model that saw its own census figure.

To reproduce:

```bash
python src/spatial_holdout.py
python src/worse_districts.py
python src/build_corrections.py
```

---

## Things that didn't help

I tried a few more things that didn't work, and I'm keeping them here so I don't repeat them.

- **Other model forms.** Three alternatives to the log-linear fit (the table at the top). None of them beat it, because the error is in the data and not in the curve.
- **Road density** (OpenStreetMap through Geofabrik and pyrosm, `src/road_features.py`). Correlated 0.87 to 0.96 with population density, and adding it degraded the spatial holdout from 7.07% to 7.43%. It added noise instead of information.
- **Nighttime lights** (VIIRS annual v21, masked, 2012 and 2020, `src/light_features.py`). Adding lights growth and the 2020 lights level gave 7.22% ± 0.53, against 7.07% ± 0.28 without them. That gap is inside the seed spread, so lights add nothing the four existing features don't already cover. Lights growth is also tangled up with the 2012 starting level, since a dark rural district "grows" a lot from almost nothing. The 2012 composite only covers April to December.

---

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Data

Two sources go in `data/raw/`. Neither is committed to the repo.

- **WorldPop** annual population rasters for Rwanda, 2000 to 2020, saved as `data/raw/worldpop/rwa_ppp_<year>.tif`. From https://hub.worldpop.org
- **NISR / COD-AB** district boundaries, saved as `data/raw/boundaries/rwa_adm2_2006_NISR_WGS1984_20181002.shp`. From https://data.humdata.org/dataset/cod-ab-rwa

The 2022 census figures for all 30 districts are hardcoded in `src/pipeline.py`.

The two experiments that didn't help need extra downloads, also not committed:

- **OSM roads:** the Rwanda extract from Geofabrik, saved as `data/raw/osm/rwanda.osm.pbf`.
- **VIIRS lights:** the annual v21 `average_masked` files for 2012 and 2020 from the Earth Observation Group (free account), saved as `data/raw/viirs/viirs_2012.tif.gz` and `viirs_2020.tif.gz`. Use the masked files, not the 9 GB unmasked ones. The unmasked product includes background noise that would bias the comparison.

### Build and run

```bash
python src/pipeline.py           # zonal statistics -> CSV + SQLite (takes a few minutes)
python src/train.py              # fit 30 models -> models/population_model.joblib
python src/build_corrections.py  # out-of-fold corrections -> data/processed/corrections.csv
python src/build_geojson.py      # district outlines -> data/processed/districts.geojson
cd src && uvicorn api:app --reload
```

The dashboard is at http://127.0.0.1:8000/dashboard and the API docs are at `/docs`.

Before the pipeline runs, it checks that every district in the census reference matches the `ADM2_EN` field in the shapefile. If one doesn't, the run stops instead of quietly dropping a district.

---

## Dashboard

The dashboard has a year slider from 2000 to 2040, a map you can switch between growth and reliability, and a chart where the uncertainty range widens with distance and is coloured by reliability band. A caveat box explains what the satellite data means for the district you've selected. There's a sortable district list, a CSV download link, and a light and dark theme that follows your OS.

---

## Endpoints

| Endpoint | Returns |
| --- | --- |
| `GET /districts` | The 30 supported districts |
| `GET /predict/{district}?year=` | Forecast with range, reliability, model metadata and, after 2020, a corrected forecast with advice |
| `GET /forecast?year=` | All 30 districts for one year in one call, corrections included |
| `GET /compare?district1=&district2=&year=` | Two districts side by side, with difference and ratio |
| `GET /history/{district}` | Observed population 2000 to 2020 |
| `GET /geojson` | Simplified district polygons in WGS84, read from a prebuilt file |
| `GET /reliability` | Reliability band for every district |
| `GET /export?year=` | All forecasts as CSV, with caveats and corrected figures |
| `GET /dashboard` | The browser dashboard |
| `GET /health` | Service status |

The CSV export includes the caveat text next to the numbers. Someone working in a spreadsheet loses every visual warning the dashboard gives, so the warning has to travel with the data.

For years after 2020, `/predict` carries a `correction` block next to the plain forecast:

```json
"correction": {
  "predicted_population": 571751,
  "multiplier": 0.896,
  "advice": "use_with_caution",
  "cv_change_pts": -9.3,
  "note": "Satellite estimates read below the census here. In testing, the correction tended to push forecasts the wrong way in districts like this, so treat the plain forecast as the main figure. ..."
}
```

`cv_change_pts` is how many points the correction moved this district's error in cross-validation (negative means it made things worse). For 2020 and earlier the block is `null`, since those years are observations.

---

## Method

1. **Zonal statistics** add up the WorldPop raster values inside each district polygon. That gives 630 district-year records (30 districts × 21 years).
2. **One log-linear model per district.** A straight line through `log(population)`, which assumes a constant proportional growth rate.
3. **Validation** against the 2022 census, reported per district and not only as one aggregate number.
4. **Uncertainty** widens by 1.1 percentage points per year after 2020, based on the drift I measured on a 2016 to 2020 holdout.
5. **Correction.** A ridge model predicts how far a district's naive forecast will miss the census, trained on the other districts. It is served beside the plain forecast with an advice flag, not in place of it.

The processed records are stored in SQLite, and the API reads from that.

---

## Testing

```bash
pytest tests/ -v
```

22 tests covering every endpoint, all three documented error codes (404, 400, 422), the response contract, the correction block (absent for years inside the training range, advice following the data direction, extra export columns), and two regression guards: that districts receive distinct predictions, and that the uncertainty range widens with forecast distance.

---

## Limitations

**The model has no ceiling.** A log-linear fit keeps compounding the same growth rate forever, and real urban growth doesn't. Gasabo has *reliable* data and still projects to 1.43 million by 2030, against a 2022 census of 879,505. Read forecasts more than about ten years out as an upper bound. The reliability bands don't help here, because they're about data quality, not the shape of the curve.

**The uncertainty band is an estimate, not a prediction interval.** The 1.1 points per year comes from the drift in a single district over five holdout years. A properly grounded version would take its intervals from the regression itself.

**One census point anchors everything.** The reliability bands rest on a single 2022 observation per district. A district reading 25% high in 2022 is evidence it reads high in 2030, but not proof.

**Training data ends in 2020,** so every forecast from 2021 on is an extrapolation.

**A possible circularity.** Gasabo's 2020 WorldPop figure (883,424) is within half a percent of the 2022 census (879,505). If the raster series already includes census-adjusted estimates, then measuring error against that census is partly circular. I need to check this before I quote the accuracy figures as fully independent.

**The correction helps on average but hurts about a third of the districts.** It brings mean error down from 9.81% to about 7%, but it learned a one-direction rule from a majority of overshooting districts and pushes already-underpredicting districts further down (10 districts in the seed-1 run, 11 in the seed average). The API serves it beside the plain forecast with an advice flag instead of replacing it.

**Spatial generalisation is only tested inside Rwanda.** The correction is cross-validated on the same 30 districts it was built from, against one census. It says little about other countries or about a future census. Thirty rows is also small, and the seed spread (± 0.28) is the honest measure of how much the result moves with the split.

**The correction fixes the level, not the growth rate.** It applies one multiplier calibrated at 2022 to every year, so the corrected series grows at the same rate as the naive one. For fast-growing districts both forecasts get less trustworthy the further out you go, and the correction does not fix that.

---

## Repository layout

```
src/
  pipeline.py              zonal statistics, validation, persistence
  model.py                 PopulationModel, reliability banding
  train.py                 fit and save the models
  build_corrections.py     out-of-fold corrections the API serves
  build_geojson.py         prebuilt district outlines for the API
  api.py                   FastAPI service
  compare_model_forms.py   four model forms against the census
  analyse_error_source.py  error decomposition
  spatial_holdout.py       district-level holdout and correction
  worse_districts.py       checks which backfires come from the data
  road_features.py         OSM road density (experiment, no gain)
  light_features.py        VIIRS lights growth (experiment, no gain)
  static/                  dashboard HTML, CSS, JS
data/processed/            CSV, SQLite and GeoJSON outputs
models/                    saved model artifact
tests/                     pytest suite
notebooks/                 early exploratory work
Dockerfile                 runtime image for the API
docker-compose.yml         one-service compose file
requirements-api.txt       runtime-only dependencies
```

---

## Data sources

WorldPop. (2025). *Gridded population estimates for sub-Saharan Africa.* University of Southampton.

National Institute of Statistics of Rwanda. (2023). *Rwanda population and housing census 2022: Main indicators report.*
