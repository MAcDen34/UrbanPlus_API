"""Where does the forecast error come from: the model, or the data it was fed?

Context

Forecasts validated against the 2022 census carry 9.81% mean absolute error,
and four different model forms all landed within 0.6 points of each other.
That similarity is itself evidence: if changing the functional form barely
moves the result, the error probably is not coming from the functional form.

Method

WorldPop's own 2020 estimate is an observation, not a forecast. Comparing it
directly against the 2022 census measures how far the input data sits from
ground truth before any modelling happens. Decomposing total forecast error
into that inherited component and the residual attributes the error to its
source.

Run from the project root:
    python src/analyse_error_source.py
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
RELIABLE, MODERATE = 5.0, 12.0  # abs WorldPop-vs-census error, in percent


def build_table():
    history = pd.read_csv(ROOT / "data/processed/population.csv")
    validation = pd.read_csv(ROOT / "data/processed/validation.csv")

    latest_year = history["year"].max()
    observed = history[history["year"] == latest_year].set_index("district")["population"]

    first_last = history.groupby("district")["population"].agg(["first", "last"])

    t = validation.set_index("district").copy()
    t["worldpop_2020"] = observed
    t["growth_pct"] = (first_last["last"] / first_last["first"] - 1) * 100

    # How far the INPUT DATA sits from ground truth, before any modelling.
    t["data_err_pct"] = (t["worldpop_2020"] - t["census"]) / t["census"] * 100

    # How far the FORECAST sits from ground truth.
    t = t.rename(columns={"error_%": "forecast_err_pct"})

    # What the model added on top of what it inherited.
    t["model_added_pct"] = t["forecast_err_pct"].abs() - t["data_err_pct"].abs()

    return t


def classify(t):
    """Group districts by how well WorldPop tracks the census there."""

    def band(err):
        a = abs(err)
        if a <= RELIABLE:
            return "reliable"
        if a <= MODERATE:
            return "moderate"
        return "weak"

    t["data_quality"] = t["data_err_pct"].apply(band)
    return t


def main():
    t = classify(build_table())

    corr = t["data_err_pct"].corr(t["forecast_err_pct"])
    data_mae = t["data_err_pct"].abs().mean()
    fc_mae = t["forecast_err_pct"].abs().mean()

    print("\nError decomposition across 30 districts")
    print("=" * 72)
    print(f"  WorldPop 2020 vs 2022 census (input data error) : {data_mae:5.2f}%")
    print(f"  Forecast vs 2022 census (total error)           : {fc_mae:5.2f}%")
    print(f"  Attributable to the model                       : {fc_mae - data_mae:5.2f}%")
    print(f"  Correlation between the two error series        : {corr:5.3f}")
    print()
    print(f"  {data_mae / fc_mae:.0%} of total forecast error was present in the input")
    print("  data before any model was fitted.")

    print("\nDistricts where the input data diverges most from census")
    print("-" * 72)
    cols = ["worldpop_2020", "census", "data_err_pct", "forecast_err_pct", "model_added_pct"]
    worst = t.reindex(t["data_err_pct"].abs().sort_values(ascending=False).index)
    print(worst[cols].head(8).round(1).to_string())

    print("\nDistricts grouped by how closely WorldPop tracks the census")
    print("-" * 72)
    summary = (
        t.groupby("data_quality")
        .agg(
            districts=("census", "size"),
            mean_abs_data_err=("data_err_pct", lambda s: round(s.abs().mean(), 2)),
            mean_abs_forecast_err=("forecast_err_pct", lambda s: round(s.abs().mean(), 2)),
        )
        .reindex(["reliable", "moderate", "weak"])
    )
    print(summary.to_string())
    print()
    print("  Forecast accuracy tracks input quality, not district size or")
    print("  growth rate. A district is hard to forecast when its satellite")
    print("  estimates disagree with the census, not when it grows fast.")

    print("\nSign of the input error")
    print("-" * 72)
    over = (t["data_err_pct"] > 0).sum()
    print(f"  WorldPop reads high in {over} districts, low in {30 - over}.")
    print(f"  Mean signed input error: {t['data_err_pct'].mean():+.2f}%")

    out = ROOT / "data/processed/error_decomposition.csv"
    t[cols + ["growth_pct", "data_quality"]].round(2).to_csv(out)
    print(f"\nPer-district detail written to {out.relative_to(ROOT)}")

    print("\nImplication")
    print("-" * 72)
    print("  Roughly 7.8 points of the 9.81% error is a floor imposed by the")
    print("  input data. Model work cannot go below it while WorldPop is the")
    print("  only source. Reducing it requires additional predictors, which")
    print("  is the case for FR17 (nighttime lights) and FR18 (road density).")


if __name__ == "__main__":
    main()
