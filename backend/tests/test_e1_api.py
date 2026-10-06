"""Phase 3 validation: the model registry endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.slow

VALID_ROW = {
    "route": "R000",
    "hub": "F000",
    "carrier": "air",
    "congestion_index": 0.42,
    "num_handoffs": 3,
    "weather_flag": 0,
    "hour_of_day": 17,
    "sorting_method": "unknown",
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        # Startup kicks off a background load; block until it finishes so
        # the endpoint assertions are deterministic.
        from app.engines.e1_misplacement.registry import get_registry

        registry = get_registry()
        if registry._thread is not None:  # noqa: SLF001
            registry._thread.join(timeout=180)  # noqa: SLF001
        yield test_client


def test_model_status_reports_loaded(client: TestClient) -> None:
    response = client.get("/model/status")
    assert response.status_code == 200

    body = response.json()
    assert body["model_loaded"] is True
    assert body["state"] == "loaded"
    assert body["name"] == "misplacement_classifier"
    assert body["version"] == settings.e1_model_version
    assert body["model_class"] == "RandomForestClassifier"


def test_model_status_lists_the_feature_contract(client: TestClient) -> None:
    body = client.get("/model/status").json()
    assert body["feature_names"] == [
        "route", "hub", "carrier", "congestion_index",
        "num_handoffs", "sorting_method", "weather_flag", "hour_of_day",
    ]


def test_model_status_does_not_leak_filesystem_paths(client: TestClient) -> None:
    assert "artifact_dir" not in client.get("/model/status").json()


def test_model_status_under_version_prefix(client: TestClient) -> None:
    assert client.get("/api/v1/model/status").json()["model_loaded"] is True


def test_predict_returns_a_bounded_probability(client: TestClient) -> None:
    response = client.post("/model/predict", json=VALID_ROW)
    assert response.status_code == 200

    body = response.json()
    assert 0.0 <= body["p_misplace"] <= 1.0
    assert body["model_version"] == settings.e1_model_version


def test_predict_rejects_a_missing_field(client: TestClient) -> None:
    payload = {k: v for k, v in VALID_ROW.items() if k != "carrier"}
    assert client.post("/model/predict", json=payload).status_code == 422


def test_predict_rejects_an_out_of_range_hour(client: TestClient) -> None:
    assert client.post(
        "/model/predict", json={**VALID_ROW, "hour_of_day": 25}
    ).status_code == 422


def test_predict_rejects_a_bad_weather_flag(client: TestClient) -> None:
    assert client.post(
        "/model/predict", json={**VALID_ROW, "weather_flag": 7}
    ).status_code == 422


def test_batch_predict_returns_one_probability_per_row(client: TestClient) -> None:
    rows = [{**VALID_ROW, "hour_of_day": h} for h in (0, 8, 17)]
    response = client.post("/model/predict/batch", json={"rows": rows})
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 3
    assert len(body["probabilities"]) == 3
    assert all(0.0 <= p <= 1.0 for p in body["probabilities"])


def test_batch_predict_rejects_an_empty_list(client: TestClient) -> None:
    assert client.post("/model/predict/batch", json={"rows": []}).status_code == 422


def test_reload_succeeds_and_keeps_the_model_loaded(client: TestClient) -> None:
    response = client.post("/model/reload")
    assert response.status_code == 200
    assert response.json()["model_loaded"] is True


def test_ready_reports_the_model_state(client: TestClient) -> None:
    body = client.get("/ready").json()
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["e1_model"] == "loaded"
    assert body["status"] == "ready"


def test_model_artifact_row_was_registered(client: TestClient) -> None:
    """Startup should have written an active ModelArtifact row."""
    from app.core.database import SessionLocal
    from app.services.model_artifacts import get_active_artifact

    with SessionLocal() as db:
        artifact = get_active_artifact(db)

    assert artifact is not None
    assert artifact.name == "misplacement_classifier"
    assert artifact.version == settings.e1_model_version
    assert artifact.is_active is True
