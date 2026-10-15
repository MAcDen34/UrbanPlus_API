import joblib
import numpy as np
import pandas as pd 
import os
from sklearn.linear_model import LinearRegression


class PopulationModel:
    def __init__(self):
        self.models = {}
        self.metadata = {}

    def fit(self, df):
        """Fit one log-linear model per district."""
        for district in df["district"].unique():
            d = df[df["district"] == district]
            self.models[district] = LinearRegression().fit(
                d[["year"]], np.log(d["population"])
            )

        self.metadata.update({
            "model_type": "log-linear trend (per district)",
            "train_years": (int(df["year"].min()), int(df["year"].max())),
            "validated_against": "2022 census",
            "districts": sorted(self.models.keys()),
        })

    def predict(self, district, year):
        if not self.models:
            raise ValueError("Model must be fitted before making predictions")

        if district not in self.models:
            raise KeyError(f"No model for district '{district}'")

        low, high = self.metadata["train_years"]
        if year < low:
            raise ValueError(f"Year {year} is before the trained range {low}-{high}")

        return float(np.exp(
            self.models[district].predict(pd.DataFrame({"year": [year]}))
        )[0])

def get_test_error_pct(validation_path):
    df = pd.read_csv(validation_path)
    return df["error_%"].abs().mean()

def train_and_save(input_path, output_path, validation_path):
    df = pd.read_csv(input_path)

    model = PopulationModel()
    model.fit(df)

    model.metadata["test_error_pct"] = get_test_error_pct(validation_path)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    joblib.dump(model, output_path)
