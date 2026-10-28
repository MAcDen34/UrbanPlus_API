from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi import Response
from fastapi.responses import FileResponse
from pipeline import load_districts, DISTRICTS
from pathlib import Path
from model import PopulationModel, RELIABLE_PCT, MODERATE_PCT
from fastapi.staticfiles import StaticFiles
import joblib
import sqlite3
import csv
import io

app = FastAPI()

ROOT = Path(__file__).parent.parent
app.mount("/static", StaticFiles(directory=ROOT / "src/static"), name="static")
DB_PATH = ROOT / "data/processed/database.db"

def query(sql, params=()):
    """Read from the store the pipeline writes, and Rows back to the dicts."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

BASELINE = {
    r["district"]: r["population"]
    for r in query("SELECT district, population FROM population "
                   "WHERE year = (SELECT MAX(year) FROM population)")
}

model = joblib.load(ROOT / "models/population_model.joblib")

_gdf = load_districts(DISTRICTS).to_crs(epsg=4326)
_gdf["geometry"] = _gdf.geometry.simplify(0.001)
GEOJSON = _gdf[["ADM2_EN", "geometry"]].to_json()

class PopulationResponse(BaseModel):
    district: str
    year: int
    predicted_population: int
    estimated_error_pct: float
    range: dict
    reliability: dict
    model: dict
    note: str

@app.get("/dashboard")
def dashboard():
    return FileResponse(ROOT / "src/static/dashboard.html")

@app.get("/geojson")
def geojson():
    return Response(content=GEOJSON, media_type="application/json")

@app.get("/districts")
def get_districts():
    return {"districts": model.metadata["districts"]}

@app.get("/predict/{district}")
def predict(district: str, year: int):
    try:
        prediction = model.predict(district, year)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"District '{district}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    error_pct = model.error_pct_for(year)

    return PopulationResponse(
        district=district,
        year=year,
        predicted_population=int(prediction),
        estimated_error_pct=error_pct,
        range={
            "low": int(prediction * (1 - error_pct / 100)),
            "high": int(prediction * (1 + error_pct / 100))
        },
        reliability=model.reliability_for(district),
        model={
            "type": model.metadata["model_type"],
            "trained_on": f"{model.metadata['train_years'][0]}-{model.metadata['train_years'][1]}",
            "validated_against": model.metadata["validated_against"],
            "baseline_error_pct": model.metadata["test_error_pct"]
        },
        note="Indicative estimate; error widens over time"
    )

@app.get("/compare")
def compare(district1: str, district2: str, year: int):
    try:
        prediction1 = model.predict(district1, year)
        prediction2 = model.predict(district2, year)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    error_pct = model.error_pct_for(year)

    return {
        "year": year,
        "districts": {
            district1: {
                "predicted_population": int(prediction1),
                "range": {
                    "low": int(prediction1 * (1 - error_pct / 100)),
                    "high": int(prediction1 * (1 + error_pct / 100)),
                },
            },
            district2: {
                "predicted_population": int(prediction2),
                "range": {
                    "low": int(prediction2 * (1 - error_pct / 100)),
                    "high": int(prediction2 * (1 + error_pct / 100)),
                },
            },
        },
        "difference": int(prediction1 - prediction2),
        "ratio": round(prediction1 / prediction2, 2),
        "estimated_error_pct": error_pct,
        "note": "Indicative estimate; error widens over time",
    }

@app.get("/history/{district}")
def history(district: str):
    rows = query("SELECT year, population FROM population "
                 "WHERE district = ? ORDER BY year ",(district,))

    if not rows:
        raise HTTPException(status_code =404 , detail=f"District '{district}' not found ")

    return {
        "district": district,
        "source": "WorldPop gridded population estimate",
        "observations": rows,
    }
@app.get("/reliability")
def reliability():
    return {
        "basis": "WorldPop 2020 observation compared against 2022 census",
        "thresholds": {"reliable_within_pct": RELIABLE_PCT, "moderate_within_pct": MODERATE_PCT},
        "districts": model.metadata["reliability"],
    }

@app.get("/forecast")
def forecast(year: int):
    """All districts for one year - one call instead of thirty."""
    try:
        error_pct = model.error_pct_for(year)
        rows = {}
        for d in model.metadata["districts"]:
            p = model.predict(d, year)
            rows[d] = {
                "predicted_population": int(p),
                "baseline": int(BASELINE[d]),
                "range": {"low": int(p * (1 - error_pct /100)),
                          "high": int(p * (1 + error_pct / 100))},
                "reliability": model.reliability_for(d),
            }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"year": year,"estimated_error_pct": error_pct, "districts": rows}


@app.get("/export")
def export(year: int):
    """Forecasts for all districts as CSV, for use outside the dashboard."""
    try:
        error_pct = model.error_pct_for(year)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "district", "year", "predicted_population", "baseline_2020",
        "growth_multiple", "range_low", "range_high",
        "estimated_error_pct", "data_quality", "data_error_pct", "caveat",
    ])

    for d in model.metadata["districts"]:
        p = model.predict(d, year)
        r = model.reliability_for(d)
        writer.writerow([
            d, year, int(p), BASELINE[d], round(p / BASELINE[d], 3),
            int(p * (1 - error_pct / 100)), int(p * (1 + error_pct / 100)),
            error_pct, r["band"], r["data_error_pct"], r["note"],
        ])

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="urbanplus_forecast_{year}.csv"'},
    )


@app.get("/health")
def health():
    return {"status": "OK"}
