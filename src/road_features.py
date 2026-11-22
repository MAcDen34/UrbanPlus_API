from pathlib import Path

import pandas as pd
from pyrosm import OSM

from pipeline import load_districts, CENSUS_2022

ROOT = Path(__file__).parent.parent
OUT_PATH = ROOT / "data/processed/road_density.csv"
PBF_PATH = ROOT / "data/raw/osm/rwanda.osm.pbf"


def collect(districts):
    """Read the whole country's road network once, then clip it per district.

    Overpass rate-limits hard enough that 30 sequential requests never finish
    cleanly. The Geofabrik extract is a single download and everything after
    it is local, so this also means anyone can reproduce the feature without
    depending on a public API being in a good mood.
    """
    if not PBF_PATH.exists():
        raise FileNotFoundError(
            f"OSM extract not found at {PBF_PATH}. Download it with:\n"
            f"  curl -o {PBF_PATH} https://download.geofabrik.de/africa/rwanda-latest.osm.pbf"
        )

    print("Reading the national road network (one pass, takes a minute)")
    roads = OSM(str(PBF_PATH)).get_network(network_type="driving")
    roads = roads.to_crs(epsg=32736)

    print(f"  {len(roads)} road segments loaded\n")

    rows = []
    for r in districts.to_crs(epsg=32736).itertuples():
        inside = roads.clip(r.geometry)
        rows.append({
            "district": r.ADM2_EN,
            "road_km": inside.geometry.length.sum() / 1000,
            "segments": len(inside),
        })
        print(f"  {r.ADM2_EN:<14} {rows[-1]['road_km']:8.1f} km")

    return pd.DataFrame(rows)


def main():
    districts = load_districts(list(CENSUS_2022))

    # Area needs a projected CRS; UTM 36S covers Rwanda.
    areas = districts.to_crs(epsg=32736).geometry.area / 1e6

    print(f"\nMeasuring road networks for {len(districts)} districts\n")

    df = collect(districts)

    df = df.merge(
        pd.DataFrame({"district": districts["ADM2_EN"].values, "area_km2": areas.values}),
        on="district",
    )
    df["road_density"] = df["road_km"] / df["area_km2"]
    df["segment_density"] = df["segments"] / df["area_km2"]

    df.round(3).to_csv(OUT_PATH, index=False)

    print(f"\n{len(df)} of 30 districts measured")
    print("\nDensest road networks")
    print("-" * 58)
    top = df.sort_values("road_density", ascending=False)
    print(top[["district", "road_km", "area_km2", "road_density"]].head(6).round(2).to_string(index=False))
    print("\nSparsest")
    print(top[["district", "road_km", "area_km2", "road_density"]].tail(4).round(2).to_string(index=False))
    print(f"\nWritten to {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
