# build_corrections.py
# turns the spatial holdout into numbers the API can serve.
# each district's correction comes only from folds where it was held out,
# averaged over the five seeds, so nobody gets corrected by a model that
# saw their own census figure.

from pathlib import Path

import numpy as np
import pandas as pd

from spatial_holdout import build_features, spatial_holdout, CANDIDATES, SEEDS, error_pct

ROOT = Path(__file__).parent.parent


def main():
    history = pd.read_csv(ROOT / "data/processed/population.csv")
    df = build_features(history)

    # out-of-fold log correction for every district, averaged across seeds
    per_seed = [spatial_holdout(df, CANDIDATES["ridge"], seed) for seed in SEEDS]
    df["log_correction"] = np.mean(per_seed, axis=0)
    df["multiplier"] = np.exp(df["log_correction"])

    corrected_2022 = df["naive_2022"] * df["multiplier"]
    df["baseline_err_pct"] = error_pct(df["naive_2022"], df["census_2022"])
    df["corrected_err_pct"] = error_pct(corrected_2022, df["census_2022"])

    # positive = the correction would have helped this district in testing
    df["cv_change_pts"] = df["baseline_err_pct"].abs() - df["corrected_err_pct"].abs()

    improved = (df["cv_change_pts"] > 0).sum()
    print(f"baseline:  {df['baseline_err_pct'].abs().mean():.2f}% mean abs error")
    print(f"corrected: {df['corrected_err_pct'].abs().mean():.2f}% mean abs error")
    print(f"{improved} of 30 improved, {30 - improved} got worse")

    out = ROOT / "data/processed/corrections.csv"
    cols = ["district", "multiplier", "baseline_err_pct", "corrected_err_pct", "cv_change_pts"]
    df[cols].round(4).to_csv(out, index=False)
    print(f"written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
