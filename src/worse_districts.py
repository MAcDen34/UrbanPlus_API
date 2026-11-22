# worse_districts.py
# of the districts the correction made worse, which ones were handed bad data?
# if WorldPop's 2020 number was already far from the census, a correction
# learned from other districts can't know that, so that's the data's fault.
# if the input was fine and it still got worse, the model misfired.

from pathlib import Path

import pandas as pd

from pipeline import CENSUS_2022
from model import RELIABLE_PCT, MODERATE_PCT

ROOT = Path(__file__).parent.parent


def input_band(gap_pct):
    gap = abs(gap_pct)
    if gap <= RELIABLE_PCT:
        return "reliable"
    if gap <= MODERATE_PCT:
        return "moderate"
    return "weak"


def main():
    holdout = pd.read_csv(ROOT / "data/processed/spatial_holdout.csv")
    history = pd.read_csv(ROOT / "data/processed/population.csv")

    pop_2020 = history[history["year"] == 2020].set_index("district")["population"]
    holdout["input_gap_pct"] = [
        (pop_2020[d] - CENSUS_2022[d]) / CENSUS_2022[d] * 100
        for d in holdout["district"]
    ]
    holdout["input_band"] = holdout["input_gap_pct"].apply(input_band)
    holdout["got_worse"] = holdout["improved"] < 0

    # weak input = the data's fault, reliable input = the model's fault
    blame = {"weak": "data", "moderate": "mixed", "reliable": "model"}
    holdout["blame"] = holdout["input_band"].map(blame)
    holdout.loc[~holdout["got_worse"], "blame"] = ""

    cols = ["district", "input_gap_pct", "input_band", "baseline_err",
            "corrected_err", "improved", "blame"]
    worse = holdout[holdout["got_worse"]].sort_values("input_gap_pct", key=abs)

    print("\nDistricts the correction made worse")
    print("-" * 74)
    print(worse[cols].round(1).to_string(index=False))

    print("\nWhere the blame lands")
    print("-" * 74)
    print(worse["blame"].value_counts().to_string())

    print("\nAverage change in error, by input quality (all 30 districts)")
    print("-" * 74)
    print(holdout.groupby("input_band")["improved"].agg(["count", "mean"]).round(2))

    out = ROOT / "data/processed/correction_flags.csv"
    holdout[cols + ["got_worse"]].round(3).to_csv(out, index=False)
    print(f"\nFlags written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
