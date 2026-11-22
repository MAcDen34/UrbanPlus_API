"""Compare candidate model forms against the 2022 census.

Baseline to beat (log-linear fitted on 2000-2020, all years weighted equally):
mean absolute error   9.81%
mean signed error    +6.25%
within 10%           20 / 30
corr(growth, error)   0.613

Run from the project root:
python src/compare_model_forms.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

ROOT = Path(__file__).parent.parent
TARGET_YEAR = 2022


# ----candidates--------
# Each candidate takes one district's history (a DataFrame with 'year' and
# 'population') and returns a predicted population for `year`.


def log_linear(d, year):
    """Baseline: straight line through log(population), all years equal."""
    m = LinearRegression().fit(d[["year"]], np.log(d["population"]))
    return float(np.exp(m.predict(pd.DataFrame({"year": [year]})))[0])


def recent_weighted(d, year, half_life=6):
    """Same form, but older years count less.

    Weight decays exponentially into the past, halving every `half_life`
    years. A district whose growth slowed after 2010 is therefore fitted
    mostly on its slower recent behaviour rather than its early boom.
    """
    age = d["year"].max() - d["year"]
    w = 0.5 ** (age / half_life)
    m = LinearRegression().fit(d[["year"]], np.log(d["population"]), sample_weight=w)
    return float(np.exp(m.predict(pd.DataFrame({"year": [year]})))[0])


def recent_window(d, year, since=2010):
    """Crude floor to beat: ignore everything before `since` entirely."""
    recent = d[d["year"] >= since]
    m = LinearRegression().fit(recent[["year"]], np.log(recent["population"]))
    return float(np.exp(m.predict(pd.DataFrame({"year": [year]})))[0])


def log_quadratic(d, year):
    """Adds a year-squared term so the growth rate itself can change.

    Can bend downward, which is what we want, but can also bend so far
    that it predicts decline. check_turning_points() below reports where
    each district's curve peaks.
    """
    X = pd.DataFrame({"year": d["year"], "year_sq": d["year"] ** 2})
    m = LinearRegression().fit(X, np.log(d["population"]))
    q = pd.DataFrame({"year": [year], "year_sq": [year ** 2]})
    return float(np.exp(m.predict(q))[0])


CANDIDATES = {
    "log-linear (baseline)": log_linear,
    "recent-weighted": recent_weighted,
    "recent-window 2010+": recent_window,
    "log-quadratic": log_quadratic,
}


# ------------------------------------------------------------------ scoring


def evaluate(fn, history, census):
    """Score one candidate across all districts."""
    rows = []
    for district, actual in census.items():
        d = history[history["district"] == district]
        pred = fn(d, TARGET_YEAR)
        rows.append(
            {
                "district": district,
                "predicted": round(pred),
                "census": actual,
                "error_pct": (pred - actual) / actual * 100,
            }
        )
    return pd.DataFrame(rows)


def summarise(name, result, growth):
    merged = result.merge(growth, on="district")
    return {
        "model": name,
        "mean_abs_err": round(result["error_pct"].abs().mean(), 2),
        "mean_signed_err": round(result["error_pct"].mean(), 2),
        "within_10pct": int((result["error_pct"].abs() <= 10).sum()),
        "worst_err": round(result["error_pct"].abs().max(), 1),
        "corr_growth_err": round(merged["growth_pct"].corr(merged["error_pct"]), 3),
    }


def check_turning_points(history, census):
    """Where does each quadratic fit stop rising? Decline before 2040 is a red flag."""
    flagged = []
    for district in census:
        d = history[history["district"] == district]
        X = pd.DataFrame({"year": d["year"], "year_sq": d["year"] ** 2})
        m = LinearRegression().fit(X, np.log(d["population"]))
        b, c = m.coef_[0], m.coef_[1]
        if c < 0:
            peak = -b / (2 * c)
            if peak < 2040:
                flagged.append((district, round(peak)))
    return sorted(flagged, key=lambda t: t[1])


# --------------------------------------------------------------------- main


def main():
    history = pd.read_csv(ROOT / "data/processed/population.csv")
    census = (
        pd.read_csv(ROOT / "data/processed/validation.csv")
        .set_index("district")["census"]
        .to_dict()
    )

    first_last = history.groupby("district")["population"].agg(["first", "last"])
    growth = (
        ((first_last["last"] / first_last["first"] - 1) * 100)
        .rename("growth_pct")
        .reset_index()
    )

    summaries, results = [], {}
    for name, fn in CANDIDATES.items():
        res = evaluate(fn, history, census)
        results[name] = res
        summaries.append(summarise(name, res, growth))

    table = pd.DataFrame(summaries)
    print("\nAll four candidates, scored against the 2022 census")
    print("=" * 78)
    print(table.to_string(index=False))

    best = table.loc[table["mean_abs_err"].idxmin(), "model"]
    print(f"\nLowest mean absolute error: {best}")

    print("\nWorst five districts under the baseline vs the best candidate")
    print("-" * 78)
    comp = results["log-linear (baseline)"][["district", "error_pct"]].rename(
        columns={"error_pct": "baseline"}
    )
    comp = comp.merge(
        results[best][["district", "error_pct"]].rename(columns={"error_pct": best}),
        on="district",
    )
    comp["improvement"] = comp["baseline"].abs() - comp[best].abs()
    print(
        comp.reindex(comp["baseline"].abs().sort_values(ascending=False).index)
        .head(5)
        .round(1)
        .to_string(index=False)
    )

    flagged = check_turning_points(history, census)
    print("\nQuadratic sanity check")
    print("-" * 78)
    if flagged:
        print(f"{len(flagged)} districts peak then decline before 2040:")
        for district, peak in flagged[:8]:
            print(f"  {district:<14} peaks {peak}")
        print("A model that forecasts decline for a growing district is wrong,")
        print("however good its 2022 number looks.")
    else:
        print("No district turns over before 2040.")

    out = ROOT / "data/processed/model_form_comparison.csv"
    table.to_csv(out, index=False)
    print(f"\nSummary written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
