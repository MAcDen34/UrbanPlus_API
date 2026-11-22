import sqlite3
from pathlib import Path

import geopandas as gpd
import numpy as np 
import pandas as pd 
import os
from rasterstats import zonal_stats
from sklearn.linear_model import LinearRegression


ROOT = Path(__file__).parent.parent
CENSUS_2022 = {
    # Kigali City
    "Gasabo": 879505, "Kicukiro": 491731, "Nyarugenge": 374319,
    # Eastern
    "Bugesera": 551103, "Gatsibo": 551164, "Kayonza": 457156,
    "Kirehe": 460860, "Ngoma": 404048, "Nyagatare": 653861,
    "Rwamagana": 484953,
    # Northern
    "Burera": 387729, "Gakenke": 365292, "Gicumbi": 448824,
    "Musanze": 476522, "Rulindo": 360144,
    # Western
    "Karongi": 373869, "Ngororero": 367955, "Nyabihu": 319047,
    "Nyamasheke": 434221, "Rubavu": 546683, "Rusizi": 485529,
    "Rutsiro": 369180,
    # Southern
    "Gisagara": 397051, "Huye": 381900, "Kamonyi": 450849,
    "Muhanga": 358433, "Nyamagabe": 371501, "Nyanza": 365718,
    "Nyaruguru": 318126, "Ruhango": 359121,
}
DISTRICTS = list(CENSUS_2022)
YEARS = range(2000, 2021)

def load_districts(names):
    """Load the districts boundaries and keep the ones we want."""
    shp_path = ROOT/ "data/raw/boundaries/rwa_adm2_2006_NISR_WGS1984_20181002.shp"
    if not os.path.exists(shp_path):
        raise FileNotFoundError(f"Shapefile not found at {shp_path}")
    districts = gpd.read_file(shp_path)
    return districts[districts["ADM2_EN"].isin(names)]

def build_population_table(districts):
    """Sum the population of each district for each year and return a DataFrame."""
    rows = []
    for year in YEARS:
        raster_path = ROOT / f"data/raw/worldpop/rwa_ppp_{year}.tif"
        if not os.path.exists(raster_path):
            raise FileNotFoundError(f"Population raster not found for year {year}")
        stats = zonal_stats(districts, str(raster_path), stats=["sum"])
        for district, stat in zip(districts["ADM2_EN"], stats):
            rows.append({"district" : district, "year" : year, "population" : round(stat["sum"])})
    return pd.DataFrame(rows)

def validate_against_census(df):
    """
       Train a log-linear model on all years of data, predict the 2022 population, 
    and compare to the 2022 census data.

    The log-linear model is used because population growth is often exponential.
    By taking the log of the population data, we can fit a linear model to the 
    log-transformed data, which is equivalent to fitting an exponential model 
    to the original data.

    Returns a DataFrame with the predicted 2022 population, actual 2022 census
    population, and percent error for each district."""

    rows = []
    for name in DISTRICTS:
        d = df[df["district"] == name]
        model = fit_log_linear_model(d)
        pred = predict_population(model, 2022)
        actual = CENSUS_2022[name]
        rows.append({"district": name, "predicted_2022": round(pred), "census": actual,
                     "error_%": round((pred-actual) / actual * 100, 2)})

    return pd.DataFrame(rows)

def save_results(df, path):
    """Save the results to a CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)

def save_to_database(population_df, validation_df, db_path):
    """Store the results in a SQLite database for the API to query."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        population_df.to_sql("population", conn, if_exists="replace", index=False)
        validation_df.to_sql("validation", conn, if_exists="replace", index=False)

def fit_log_linear_model(data):
    """Fit a log-linear model to the given data."""
    model = LinearRegression().fit(data[["year"]], np.log(data["population"]))
    return model

def predict_population(model,year):
    """Predict the population for the given year using the fitted model."""
    return np.exp(model.predict(pd.DataFrame({"year": [year]})))[0]

def main():
    districts = load_districts(DISTRICTS)
    population_df = build_population_table(districts)
    validation_df = validate_against_census(population_df)

    save_results(population_df, ROOT / "data/processed/population.csv")
    save_results(validation_df, ROOT / "data/processed/validation.csv")
    save_to_database(population_df, validation_df, ROOT / "data/processed/database.db")
    print("Pipeline completed successfully. Results saved to data/processed/.")

if __name__ == "__main__":
    main()
