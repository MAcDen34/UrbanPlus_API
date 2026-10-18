from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi import Response
from fastapi.responses import FileResponse
from pipeline import load_districts, DISTRICTS
from pathlib import Path
from model import PopulationModel
import joblib
import pandas as pd 

app = FastAPI()

ROOT = Path(__file__).parent.parent
model = joblib.load(ROOT / "models/population_model.joblib")
HISTORY = pd.read_csv(ROOT / "data/processed/population.csv")

_gdf = load_districts(DISTRICTS).to_crs(epsg=4326)
_gdf["geometry"] = _gdf.geometry.simplify(0.001)
GEOJSON = _gdf[["ADM2_EN", "geometry"]].to_json()

class PopulationResponse(BaseModel):
    district: str
    year: int
    predicted_population: int
    estimated_error_pct: float
    range: dict
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
    rows = HISTORY[HISTORY["district"] == district]

    if rows.empty:
        raise HTTPException(status_code=404, detail=f"District '{district}' not found")

    return {
        "district": district,
        "source": "WorldPop gridded population estimate",
        "observations": [
            {"year": int(r.year), "population": int(r.population)}
            for r in rows.sort_values("year").itertuples()
        ],
    }


@app.get("/health")
def health():
    return {"status": "OK"}
