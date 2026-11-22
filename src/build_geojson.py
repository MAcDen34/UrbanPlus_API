# build_geojson.py
# the API only needs the district outlines, not the whole geo stack.
# so I simplify them once here and save a plain geojson file the API can just read.

from pathlib import Path

from pipeline import load_districts, DISTRICTS

ROOT = Path(__file__).parent.parent


def main():
    gdf = load_districts(DISTRICTS).to_crs(epsg=4326)
    gdf["geometry"] = gdf.geometry.simplify(0.001)

    out = ROOT / "data/processed/districts.geojson"
    out.write_text(gdf[["ADM2_EN", "geometry"]].to_json())
    print(f"written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
