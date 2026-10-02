import sqlite3
from pathlib import Path

import geopandas as gpd
import numpy as np 
import pandas as pd 
from rasterstats import zonal_stats
from sklearn.linear_model import LinearRegression


ROOT = Path(__file__).parent.parent
DISTRICTS = ["Gasabo", "Musanze"]
YEARS = range(2000, 2021)

def load_districts(names):
    """Load the districts boundaries and keep the ones we want."""
    shp_path = ROOT/ "data/raw/boundaries/rwa_adm2_2006_NISR_WGS1984_20181002.shp"
    districts = gpd.read_file(shp_path)
    return districts[districts["ADM2_EN"].isin(names)]

def build_population_table(districts):
    """Sum the population of each district for each year and return a DataFrame."""
    rows = []
    for year in YEARS:
        raster_path = ROOT / f"data/raw/worldpop/rwa_ppp_{year}.tif"
        stats = zonal_stats(districts, str(raster_path), stats=["sum"])
        for district, stat in zip(districts["ADM2_EN"], stats):
            rows.append({"district" : district, "year" : year, "population" : round(stat["sum"])})
    return pd.DataFrame(rows)

def validate_against_census(df):
    """Train log-linear on all years, predict 2022, and compare to the census."""
    census_2022 = {"Gasabo": 879505, "Musanze": 476522}

    rows = []
    for name in DISTRICTS:
        d = df[df["district"] == name]
        model = LinearRegression().fit(d[["year"]], np.log(d["population"]))

        pred = np.exp(model.predict(pd.DataFrame({"year": [2022]})))[0]
        actual = census_2022[name]

        rows.append({"district": name, "predicted_2022" : round(pred), "census" : actual, "error_%" : round((pred-actual)/actual * 100, 2)})

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
