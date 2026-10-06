"""Phase 1 validation: the app boots, health responds, CORS is configured."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    # The context manager form runs the lifespan hooks, so this also proves
    # startup and shutdown complete without error.
    with TestClient(app) as test_client:
        yield test_client


def test_root_banner(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == settings.app_name


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == settings.app_version
    assert body["environment"] == settings.environment
    assert body["uptime_seconds"] >= 0


def test_health_available_under_version_prefix(client: TestClient) -> None:
    response = client.get(f"{settings.api_v1_prefix}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_returns_ready(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ready"
    # Phase 2 registered the database as the first real dependency.
    assert body["checks"]["database"] == "ok"


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/health" in response.json()["paths"]


def test_cors_allows_configured_origin(client: TestClient) -> None:
    origin = settings.cors_origins[0]
    response = client.get("/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_preflight_is_answered(client: TestClient) -> None:
    origin = settings.cors_origins[0]
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_unknown_route_returns_404(client: TestClient) -> None:
    assert client.get("/does-not-exist").status_code == 404
