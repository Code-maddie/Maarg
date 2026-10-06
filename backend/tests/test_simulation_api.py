"""Phase 4 validation: the simulation-control endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workers.simulator import reset_simulator

SMALL_WORLD = {
    "seed": 42,
    "hub_count": 8,
    "vehicle_count": 12,
    "shipment_count": 40,
    "leg_count": 30,
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    reset_simulator()
    with TestClient(app) as test_client:
        yield test_client
    reset_simulator()


@pytest.fixture()
def world(client: TestClient) -> dict:
    """Rebuilds a small world before each test that needs one."""
    return client.post("/simulate/reset", json=SMALL_WORLD).json()


def test_reset_builds_the_requested_world(world: dict) -> None:
    assert world["hubs"] == 8
    assert world["vehicles"] == 12
    assert world["shipments"] == 40
    assert world["legs"] == 30
    assert world["seed"] == 42


def test_state_reports_the_world(client: TestClient, world: dict) -> None:
    body = client.get("/simulate/state").json()
    assert body["shipments"] == 40
    assert body["tick"] == 0
    assert body["shipment_status"]["PENDING"] == 40


def test_tick_advances_the_clock(client: TestClient, world: dict) -> None:
    first = client.post("/simulate/tick", json={"ticks": 1}).json()
    assert first["tick"] == 1

    second = client.post("/simulate/tick", json={"ticks": 3}).json()
    assert second["tick"] == 4
    assert second["now"] > first["now"]


def test_tick_changes_state(client: TestClient, world: dict) -> None:
    before = client.get("/simulate/state").json()
    client.post("/simulate/tick", json={"ticks": 80})
    after = client.get("/simulate/state").json()

    assert after["tick"] > before["tick"]
    assert after["leg_status"] != before["leg_status"]


def test_tick_rejects_an_out_of_range_count(client: TestClient) -> None:
    assert client.post("/simulate/tick", json={"ticks": 0}).status_code == 422
    assert client.post("/simulate/tick", json={"ticks": 9999}).status_code == 422


def test_inject_misplacement_changes_shipment_state(
    client: TestClient, world: dict
) -> None:
    response = client.post(
        "/simulate/inject-disruption", json={"type": "MISPLACE_SHIPMENT"}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["type"] == "MISPLACE_SHIPMENT"
    assert len(body["affected_shipments"]) == 1

    state = client.get("/simulate/state").json()
    assert state["shipment_status"]["MISPLACED"] == 1


def test_inject_vehicle_delay(client: TestClient, world: dict) -> None:
    body = client.post(
        "/simulate/inject-disruption",
        json={"type": "DELAY_VEHICLE", "delay_hours": 6},
    ).json()

    assert body["type"] == "DELAY_VEHICLE"
    assert "delayed" in body["detail"]


def test_inject_hub_closure(client: TestClient, world: dict) -> None:
    body = client.post(
        "/simulate/inject-disruption", json={"type": "CLOSE_HUB"}
    ).json()

    assert body["type"] == "CLOSE_HUB"
    assert "closed" in body["detail"]


def test_inject_rejects_an_unknown_type(client: TestClient) -> None:
    response = client.post(
        "/simulate/inject-disruption", json={"type": "ALIEN_ABDUCTION"}
    )
    assert response.status_code == 422


def test_inject_with_a_bad_target_returns_400(
    client: TestClient, world: dict
) -> None:
    response = client.post(
        "/simulate/inject-disruption",
        json={"type": "MISPLACE_SHIPMENT", "target_id": 999999},
    )
    assert response.status_code == 400


def test_same_seed_reproduces_the_world(client: TestClient) -> None:
    client.post("/simulate/reset", json=SMALL_WORLD)
    first = client.get("/simulate/state").json()

    client.post("/simulate/reset", json=SMALL_WORLD)
    second = client.get("/simulate/state").json()

    assert first["shipments"] == second["shipments"]
    assert first["shipment_status"] == second["shipment_status"]


def test_endpoints_exist_under_the_version_prefix(client: TestClient) -> None:
    assert client.get("/api/v1/simulate/state").status_code == 200
