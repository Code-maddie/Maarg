"""Phase 21 validation (backend side): the contract the existing frontend needs."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, engine, init_db
from app.main import app
from app.models import Base, Hub, Shipment
from app.workers.simulator import get_simulator, reset_simulator


@pytest.fixture(scope="module")
def client() -> TestClient:
    reset_simulator()
    Base.metadata.drop_all(bind=engine)
    init_db()
    original = settings.e1_eager_load
    settings.e1_eager_load = False
    with TestClient(app) as test_client:
        test_client.post("/simulate/reset", json={
            "seed": 42, "hub_count": 10, "vehicle_count": 30,
            "shipment_count": 80, "leg_count": 120})
        test_client.post("/simulate/tick", json={"ticks": 30})
        yield test_client
    settings.e1_eager_load = original
    reset_simulator()


# --- Firebase web config (existing frontend/.env, public fields only) ------

def test_web_config_is_public_and_configured(client) -> None:
    body = client.get("/auth/web-config").json()
    assert body["configured"] is True
    assert {"apiKey", "projectId"} <= set(body["firebase"])
    assert body["firebase"]["projectId"] == "maarg-36842"


def test_web_config_never_serves_service_account_material(client) -> None:
    serialised = json.dumps(client.get("/auth/web-config").json())
    for forbidden in ("private_key", "BEGIN PRIVATE KEY", "client_email", "MEASUREMENT", "SENDER"):
        assert forbidden not in serialised


def test_web_config_only_serves_the_whitelisted_keys(client) -> None:
    assert set(client.get("/auth/web-config").json()["firebase"]) <= {
        "apiKey", "authDomain", "projectId", "appId"}


# --- dispatcher queue: comma-separated status filter -----------------------

def test_status_filter_accepts_a_list(client) -> None:
    client.post("/simulate/inject-disruption", json={"type": "MISPLACE_SHIPMENT"})
    body = client.get("/shipments", params={"status": "MISPLACED,RECOVERING"}).json()
    assert body["total"] >= 1
    assert {i["status"] for i in body["items"]} <= {"MISPLACED", "RECOVERING"}


def test_single_status_still_works(client) -> None:
    body = client.get("/shipments", params={"status": "PENDING"}).json()
    assert all(i["status"] == "PENDING" for i in body["items"])


# --- data.js shapes the pages depend on -----------------------------------

def test_aboard_entries_carry_sla_not_lambda(client) -> None:
    """legPanelHTML computes λ = a[2] * (1 + a[1]/50); a[2] must be the SLA rate."""
    with SessionLocal() as db:
        sla = {s.code: round(s.sla_penalty_per_hour) for s in db.scalars(select(Shipment))}
    for leg in client.get("/map/network").json()["legs"]:
        for code, _t, third in leg["aboard"]:
            assert third == sla[code]


def test_every_hub_is_listed_including_closed_ones(client) -> None:
    """Pages resolve hub(code) for any shipment; a closed hub must not vanish."""
    with SessionLocal() as db:
        closed = db.scalars(select(Hub)).first()
        closed.is_active = False
        db.commit()
        code = closed.code

    hubs = {h["id"]: h for h in client.get("/map/network").json()["hubs"]}
    assert code in hubs and hubs[code]["active"] is False

    with SessionLocal() as db:
        db.scalar(select(Hub).where(Hub.code == code)).is_active = True
        db.commit()


def test_legs_carry_the_vehicle_id(client) -> None:
    for leg in client.get("/map/network").json()["legs"]:
        assert isinstance(leg["vehicle_id"], int)


def test_cors_allows_the_static_frontend_origin(client) -> None:
    for origin in ("http://localhost:5500", "http://127.0.0.1:5500"):
        r = client.options("/shipments", headers={
            "Origin": origin, "Access-Control-Request-Method": "GET"})
        assert r.headers.get("access-control-allow-origin") == origin


# --- E1 scores shipments as they go in flight (Phase 4 dependency fix) ----

def test_tick_scores_departing_shipments_when_e1_is_loaded(client, monkeypatch) -> None:
    from app.engines.e1_misplacement import registry as reg

    class FakeRegistry:
        is_loaded = True

        def predict_batch(self, rows):
            return [0.42 for _ in rows]

    monkeypatch.setattr(reg, "get_registry", lambda: FakeRegistry())
    client.post("/simulate/tick", json={"ticks": 40})

    with SessionLocal() as db:
        scored = db.scalars(select(Shipment).where(Shipment.p_misplace == 0.42)).all()
    assert scored, "no departing shipment was scored by E1"


def test_tick_is_unaffected_when_e1_is_not_loaded(client, monkeypatch) -> None:
    from app.engines.e1_misplacement import registry as reg

    class Unloaded:
        is_loaded = False

    monkeypatch.setattr(reg, "get_registry", lambda: Unloaded())
    assert client.post("/simulate/tick", json={"ticks": 5}).status_code == 200


def test_a_failing_e1_never_breaks_a_tick(client, monkeypatch) -> None:
    from app.engines.e1_misplacement import registry as reg

    class Broken:
        is_loaded = True

        def predict_batch(self, rows):
            raise RuntimeError("model exploded")

    monkeypatch.setattr(reg, "get_registry", lambda: Broken())
    assert client.post("/simulate/tick", json={"ticks": 40}).status_code == 200
