import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from pipeline import load_districts, CENSUS_2022

ROOT = Path(__file__).parent.parent
FEATURES = ["log_pop_2020", "growth_total", "deceleration", "density"]
SEEDS = [1, 7, 13, 42, 99]


def district_areas():
    """Square kilometres, from the same shapefile the pipeline uses."""
    gdf = load_districts(list(CENSUS_2022)).to_crs(epsg=32736)
    return dict(zip(gdf["ADM2_EN"], gdf.geometry.area / 1e6))


def naive_forecast(d, year):
    """What the system does today: fit a district's own history, extrapolate."""
    m = LinearRegression().fit(d[["year"]], np.log(d["population"]))
    return float(np.exp(m.predict(pd.DataFrame({"year": [year]})))[0])


def build_features(history):
    """One row per district, using only what we'd know without the census.

    The deceleration term is the one worth watching. Our error correlates with
    growth rate at r = 0.613, and the suspicion is that districts which boomed
    early and then slowed are the ones the trend line overshoots.
    """
    areas = district_areas()
    rows = []

    for name in CENSUS_2022:
        d = history[history["district"] == name].sort_values("year")
        pop = d.set_index("year")["population"]

        early_rate = (pop[2010] / pop[2000]) ** (1 / 10) - 1
        late_rate = (pop[2020] / pop[2010]) ** (1 / 10) - 1

        rows.append({
            "district": name,
            "log_pop_2020": np.log(pop[2020]),
            "growth_total": pop[2020] / pop[2000] - 1,
            "deceleration": early_rate - late_rate,
            "density": pop[2020] / areas[name],
            "naive_2022": naive_forecast(d, 2022),
            "census_2022": CENSUS_2022[name],
        })

    df = pd.DataFrame(rows)

    roads = pd.read_csv(ROOT / "data/processed/road_density.csv")
    df = df.merge(roads[["district", "road_density", "segment_density"]], on="district")


    # Work in log space so the correction is a multiplier, not an amount.
    df["correction"] = np.log(df["census_2022"] / df["naive_2022"])

    return df


def spatial_holdout(df, make_model, seed):
    """Hold out whole districts, not years.

    Each fold trains on 25 districts and predicts the correction for 5 it has
    never seen. This is the question per-district models cannot answer: does
    anything learned here transfer to a district we know nothing about?
    """
    X = df[FEATURES].to_numpy()
    y = df["correction"].to_numpy()
    predicted = np.zeros(len(df))

    splitter = KFold(n_splits=6, shuffle=True, random_state=seed)
    for train_idx, test_idx in splitter.split(X):
        model = make_model().fit(X[train_idx], y[train_idx])
        predicted[test_idx] = model.predict(X[test_idx])

    return predicted


def error_pct(predicted, actual):
    return (predicted - actual) / actual * 100


CANDIDATES = {
    "ridge": lambda: make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
    "random forest": lambda: RandomForestRegressor(
        n_estimators=300, min_samples_leaf=3, random_state=42
    ),
}


def main():
    history = pd.read_csv(ROOT / "data/processed/population.csv")
    df = build_features(history)

    baseline = error_pct(df["naive_2022"], df["census_2022"])
    baseline_mae = baseline.abs().mean()

    print("\nSpatial holdout: can one district's lesson correct another?")
    print("=" * 74)
    print(f"  30 districts, 6 folds, 5 held out per fold, {len(SEEDS)} seeds")
    print(f"  Features: {', '.join(FEATURES)}")
    print(f"\n  Uncorrected baseline: {baseline_mae:.2f}% mean absolute error")

    print("\nCorrected forecasts on districts the model never saw")
    print("-" * 74)

    results = {}
    for name, make_model in CANDIDATES.items():
        per_seed = []
        for seed in SEEDS:
            correction = spatial_holdout(df, make_model, seed)
            corrected = df["naive_2022"] * np.exp(correction)
            per_seed.append(error_pct(corrected, df["census_2022"]).abs().mean())

        results[name] = per_seed
        mean, spread = np.mean(per_seed), np.std(per_seed)
        verdict = "better" if mean < baseline_mae else "worse"
        print(f"  {name:<16} {mean:5.2f}% ± {spread:.2f}   ({verdict} than baseline)")

    # With 30 rows a single split can look convincing by luck, so the spread
    # across seeds matters as much as the mean.
    print("\n  Per-seed detail")
    for name, scores in results.items():
        print(f"    {name:<16} " + "  ".join(f"{s:5.2f}" for s in scores))

    best = min(results, key=lambda k: np.mean(results[k]))
    correction = spatial_holdout(df, CANDIDATES[best], SEEDS[0])
    corrected = df["naive_2022"] * np.exp(correction)
    df["baseline_err"] = baseline
    df["corrected_err"] = error_pct(corrected, df["census_2022"])
    df["improved"] = df["baseline_err"].abs() - df["corrected_err"].abs()

    improved = (df["improved"] > 0).sum()
    print(f"\n  Using {best}, {improved} of 30 districts improved, {30 - improved} got worse.")

    print("\nWhere the correction helped most, and where it backfired")
    print("-" * 74)
    cols = ["district", "baseline_err", "corrected_err", "improved"]
    ordered = df.reindex(df["improved"].sort_values(ascending=False).index)
    print(ordered[cols].head(5).round(1).to_string(index=False))
    print("  ...")
    print(ordered[cols].tail(5).round(1).to_string(index=False))

    ridge = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    ridge.fit(df[FEATURES], df["correction"])
    print("\nWhat the ridge model leans on (standardised coefficients)")
    print("-" * 74)
    for feature, coef in zip(FEATURES, ridge[-1].coef_):
        print(f"  {feature:<16} {coef:+.4f}")

    out = ROOT / "data/processed/spatial_holdout.csv"
    df[["district"] + FEATURES + cols[1:]].round(4).to_csv(out, index=False)
    print(f"\nPer-district detail written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
