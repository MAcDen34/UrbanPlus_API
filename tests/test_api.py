import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from api import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "OK"}


def test_districts_lists_both():
    r = client.get("/districts")
    assert r.status_code == 200
    districts = r.json()["districts"]
    assert "Gasabo" in districts
    assert "Musanze" in districts


def test_predict_returns_expected_shape():
    r = client.get("/predict/Gasabo?year=2020")
    assert r.status_code == 200

    body = r.json()
    assert body["district"] == "Gasabo"
    assert body["year"] == 2020
    for field in ("predicted_population", "estimated_error_pct", "range", "model", "note"):
        assert field in body
    assert body["range"]["low"] < body["predicted_population"] < body["range"]["high"]


def test_predict_is_in_a_plausible_range():
    """Gasabo 2020 should land near the WorldPop figure (~883k), not wildly off."""
    r = client.get("/predict/Gasabo?year=2020")
    pop = r.json()["predicted_population"]
    assert 750_000 < pop < 1_000_000


def test_districts_get_different_predictions():
    """Regression test: both districts once shared one fitted model."""
    gasabo = client.get("/predict/Gasabo?year=2020").json()["predicted_population"]
    musanze = client.get("/predict/Musanze?year=2020").json()["predicted_population"]
    assert gasabo != musanze
    assert gasabo > musanze


def test_unknown_district_returns_404():
    r = client.get("/predict/Atlantis?year=2020")
    assert r.status_code == 404


def test_year_before_training_range_returns_400():
    r = client.get("/predict/Gasabo?year=1990")
    assert r.status_code == 400


def test_non_integer_year_returns_422():
    r = client.get("/predict/Gasabo?year=banana")
    assert r.status_code == 422


def test_compare_returns_both_districts_and_ratio():
    r = client.get("/compare?district1=Gasabo&district2=Musanze&year=2020")
    assert r.status_code == 200

    body = r.json()
    assert "Gasabo" in body["districts"]
    assert "Musanze" in body["districts"]
    assert body["difference"] > 0           # Gasabo is larger
    assert 0 < body["ratio"] < 10           # a ratio, not a subtraction


def test_compare_unknown_district_returns_404():
    r = client.get("/compare?district1=Gasabo&district2=Atlantis&year=2020")
    assert r.status_code == 404
