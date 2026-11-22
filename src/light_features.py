# light_features.py
# nighttime lights growth per district, 2012 -> 2020
# the global VIIRS files are huge, so I crop Rwanda out once, cache it,
# and do the zonal stats on the small cropped copy

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window
from rasterstats import zonal_stats

from pipeline import load_districts, DISTRICTS

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw" / "viirs"
OUT = ROOT / "data" / "processed"

YEARS = [2012, 2020]
NAME_COL = "ADM2_EN"

def crop_rwanda(year, bounds):
    """Cut Rwanda's box out of the global file and cache it as a small tif."""
    cached = OUT / f"viirs_rwanda_{year}.tif"
    if cached.exists():
        return cached

    print(f"cropping {year} (slow the first time, gzip has to be read from the top)...")
    gz_path = RAW / f"viirs_{year}.tif.gz"

    # /vsigzip/ lets GDAL read straight from the .gz without unzipping 11 GB
    with rasterio.open(f"/vsigzip/{gz_path}") as src:
        minx, miny, maxx, maxy = bounds
        row_top, col_left = src.index(minx, maxy)
        row_bottom, col_right = src.index(maxx, miny)
        window = Window.from_slices((row_top, row_bottom + 1), (col_left, col_right + 1))

        data = src.read(1, window=window)
        transform = src.window_transform(window)

        # masked file uses negative / nan for "no data", treat those as zero light
        data = np.nan_to_num(data, nan=0.0)
        data[data < 0] = 0

        with rasterio.open(
            cached, "w", driver="GTiff",
            height=data.shape[0], width=data.shape[1],
            count=1, dtype="float32", crs=src.crs, transform=transform,
        ) as dst:
            dst.write(data.astype("float32"), 1)

    return cached


def main():
    gdf = load_districts(DISTRICTS).to_crs(4326)  # VIIRS is in lat/lon

    # small buffer so edge districts aren't clipped
    minx, miny, maxx, maxy = gdf.total_bounds
    bounds = (minx - 0.05, miny - 0.05, maxx + 0.05, maxy + 0.05)

    table = pd.DataFrame({"district": gdf[NAME_COL]})

    for year in YEARS:
        tif = crop_rwanda(year, bounds)
        stats = zonal_stats(gdf, str(tif), stats=["sum"])
        table[f"light_sum_{year}"] = [s["sum"] or 0.0 for s in stats]

    # +1 so a district with zero light in 2012 doesn't blow up the log
    table["light_growth"] = np.log(
        (table["light_sum_2020"] + 1) / (table["light_sum_2012"] + 1)
    )

    OUT.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT / "light_features.csv", index=False)

    print(table.sort_values("light_sum_2020", ascending=False).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
