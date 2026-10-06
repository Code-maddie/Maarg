"""Phase 20 validation: map geometry and map-layer payloads.

The frontend renders these payloads with its existing Google Maps / Leaflet
code, so the key assertion is that every payload has exactly the fields the
existing `data.js` arrays have.
"""

import random
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import engine, init_db
from app.main import app
from app.models import Base, Leg
from app.services.geometry import (
    CURVE_SEGMENTS,
    backfill_leg_polylines,
    decode_polyline,
    encode_polyline,
    leg_curve,
    point_along,
)
from app.workers.simulator import reset_simulator

# Google's published reference example for the polyline algorithm.
GOOGLE_POINTS = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
GOOGLE_ENCODED = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"

# Field sets of the existing frontend arrays in data.js.
DATA_JS_HUB_FIELDS = {"id", "name", "lon", "lat", "base", "dx", "dy", "a"}
DATA_JS_LEG_FIELDS = {"id", "veh", "type", "from", "to", "dep", "arr",
                      "tot", "res", "rel", "aboard", "auction"}
DATA_JS_CAND_FIELDS = {"id", "name", "lon", "lat", "usage", "risk",
                       "cost", "save", "status", "score"}
DATA_JS_HEAT_FIELDS = {"lat", "lng", "w", "km"}


# --- polyline codec ------------------------------------------------------

def test_encoder_matches_googles_reference_example() -> None:
    assert encode_polyline(GOOGLE_POINTS) == GOOGLE_ENCODED


def test_decoder_matches_googles_reference_example() -> None:
    decoded = decode_polyline(GOOGLE_ENCODED)
    for (lat, lng), (elat, elng) in zip(decoded, GOOGLE_POINTS):
        assert lat == pytest.approx(elat, abs=1e-5)
        assert lng == pytest.approx(elng, abs=1e-5)


def test_round_trip_on_indian_coordinates() -> None:
    rng = random.Random(7)
    points = [(rng.uniform(8, 35), rng.uniform(68, 97)) for _ in range(40)]
    for (lat, lng), (dlat, dlng) in zip(decode_polyline(encode_polyline(points)), points):
        assert lat == pytest.approx(dlat, abs=1e-5)
        assert lng == pytest.approx(dlng, abs=1e-5)


def test_empty_polyline() -> None:
    assert encode_polyline([]) == ""
    assert decode_polyline("") == []


# --- curve ---------------------------------------------------------------

def test_curve_starts_and_ends_at_the_hubs() -> None:
    a, b = (28.61, 77.21), (19.08, 72.88)
    curve = leg_curve(a, b)
    assert curve[0] == pytest.approx(a)
    assert curve[-1] == pytest.approx(b)


def test_curve_has_the_same_resolution_as_map_js() -> None:
    assert len(leg_curve((0, 0), (1, 1))) == CURVE_SEGMENTS + 1 == 29


def test_curve_bends_off_the_straight_line() -> None:
    """map.js draws a gentle arc, not a straight segment."""
    a, b = (28.61, 77.21), (19.08, 72.88)
    mid = leg_curve(a, b)[CURVE_SEGMENTS // 2]
    straight_mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    assert mid != pytest.approx(straight_mid, abs=0.05)


def test_curve_matches_the_javascript_formula_exactly() -> None:
    """Re-derives map.js legPoints() by hand for one interior point."""
    a, b, k, n, i = (10.0, 70.0), (20.0, 80.0), 0.13, 28, 7
    control = ((a[0] + b[0]) / 2 - (b[1] - a[1]) * k,
               (a[1] + b[1]) / 2 + (b[0] - a[0]) * k)
    t = i / n
    u = 1 - t
    expected = (u * u * a[0] + 2 * u * t * control[0] + t * t * b[0],
                u * u * a[1] + 2 * u * t * control[1] + t * t * b[1])
    assert leg_curve(a, b)[i] == pytest.approx(expected)


def test_point_along_endpoints_and_clamping() -> None:
    pts = [(0.0, 0.0), (10.0, 10.0)]
    assert point_along(pts, 0) == pytest.approx((0, 0))
    assert point_along(pts, 1) == pytest.approx((10, 10))
    assert point_along(pts, 0.5) == pytest.approx((5, 5))
    assert point_along(pts, -3) == pytest.approx((0, 0))
    assert point_along(pts, 9) == pytest.approx((10, 10))


# --- persistence ---------------------------------------------------------

def test_world_build_stores_a_polyline_on_every_leg(db) -> None:
    from app.workers.world import WorldSpec, build_world

    build_world(db, WorldSpec(seed=3, hub_count=6, vehicle_count=8,
                              shipment_count=10, leg_count=25))
    legs = db.scalars(select(Leg)).all()
    assert legs and all(leg.polyline for leg in legs)


def test_backfill_is_idempotent(db) -> None:
    from app.workers.world import WorldSpec, build_world

    build_world(db, WorldSpec(seed=3, hub_count=6, vehicle_count=8,
                              shipment_count=10, leg_count=25))
    assert backfill_leg_polylines(db) == 0          # already filled
    assert backfill_leg_polylines(db, overwrite=True) == 25


# --- API -----------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    reset_simulator()
    Base.metadata.drop_all(bind=engine)
    init_db()
    original = settings.e1_eager_load
    settings.e1_eager_load = False          # heat fallback path tested first
    with TestClient(app) as test_client:
        test_client.post("/simulate/reset", json={
            "seed": 42, "hub_count": 12, "vehicle_count": 40,
            "shipment_count": 120, "leg_count": 150})
        test_client.post("/simulate/tick", json={"ticks": 8})
        yield test_client
    settings.e1_eager_load = original
    reset_simulator()


def test_network_payload_has_every_layer(client) -> None:
    body = client.get("/map/network", params={"hour": 17}).json()
    assert {"hubs", "legs", "candidates", "heat", "hour", "now", "tick"} <= set(body)
    assert body["hour"] == 17
    assert len(body["hubs"]) == 12
    assert body["legs"]


def test_hubs_have_the_data_js_shape(client) -> None:
    for hub in client.get("/map/network").json()["hubs"]:
        assert DATA_JS_HUB_FIELDS <= set(hub)
        assert hub["a"] in {"start", "end", "middle"}
        assert 0.0 <= hub["base"] <= 1.0


def test_legs_have_the_data_js_shape(client) -> None:
    for leg in client.get("/map/network").json()["legs"]:
        assert DATA_JS_LEG_FIELDS <= set(leg)
        assert leg["id"].startswith("L")
        assert leg["type"] in {"Owned", "Third-party"}
        assert len(leg["dep"]) == 5 and leg["dep"][2] == ":"
        assert 0 <= leg["res"] <= leg["tot"]
        for entry in leg["aboard"]:
            assert len(entry) == 3        # [code, temperature, lambda]


def test_legs_reference_hubs_that_exist(client) -> None:
    body = client.get("/map/network").json()
    codes = {hub["id"] for hub in body["hubs"]}
    for leg in body["legs"]:
        assert leg["from"] in codes and leg["to"] in codes


def test_leg_geometry_matches_its_polyline(client) -> None:
    for leg in client.get("/map/network").json()["legs"][:10]:
        decoded = decode_polyline(leg["polyline"])
        assert len(decoded) == len(leg["path"]) == CURVE_SEGMENTS + 1
        assert decoded[0] == pytest.approx(tuple(leg["path"][0]), abs=1e-4)


def test_moving_legs_are_listed_first(client) -> None:
    statuses = [leg["status"] for leg in client.get("/map/network").json()["legs"]]
    if "DEPARTED" in statuses and "SCHEDULED" in statuses:
        assert statuses.index("DEPARTED") < statuses.index("SCHEDULED")


def test_leg_limit_is_respected(client) -> None:
    assert len(client.get("/map/network", params={"leg_limit": 5}).json()["legs"]) <= 5


def test_route_click_panel_carries_geometry(client) -> None:
    """Phase 20 criterion: route click works — /legs/{id} has the polyline."""
    leg = client.get("/map/network").json()["legs"][0]
    body = client.get(f"/legs/{leg['leg_id']}").json()
    assert body["polyline"] == leg["polyline"]
    assert len(body["path"]) == CURVE_SEGMENTS + 1
    assert body["vehicle_code"] == leg["veh"]


def test_candidates_have_the_data_js_shape(client) -> None:
    client.get("/hub-emergence/candidates", params={"regenerate": True})
    for cand in client.get("/map/network").json()["candidates"]:
        assert DATA_JS_CAND_FIELDS <= set(cand)
        assert cand["status"] != "REJECTED"


def test_heat_falls_back_honestly_without_e1(client, monkeypatch, tmp_path) -> None:
    """Phase 20 criterion: fallback works when a dependency is unavailable.

    Uses an unloaded registry explicitly: other suites may have loaded the
    shared one, and the fallback must be tested regardless of run order.
    """
    from app.engines.e1_misplacement.registry import ModelRegistry
    from app.services import mapdata

    monkeypatch.setattr(mapdata, "get_registry", lambda: ModelRegistry(artifact_dir=tmp_path))
    mapdata._risk_cache.clear()

    body = client.get("/map/heat", params={"hour": 17}).json()
    assert body["hour"] == 17
    assert "E1 not loaded" in body["source"]
    for point in body["points"]:
        assert DATA_JS_HEAT_FIELDS <= set(point)


def test_heat_rejects_a_bad_hour(client) -> None:
    assert client.get("/map/heat", params={"hour": 24}).status_code == 422


def test_pickup_route_requires_a_winner(client) -> None:
    from app.core.database import SessionLocal
    from app.models import Auction, Shipment

    with SessionLocal() as db:
        shipment = db.scalars(select(Shipment)).first()
        auction = Auction(shipment_id=shipment.id, max_bounty=100.0,
                          opened_at=datetime(2026, 5, 1), closes_at=datetime(2026, 5, 1, 1))
        db.add(auction)
        db.commit()
        auction_id = auction.id

    assert client.get(f"/map/pickup-route/{auction_id}").status_code == 409
    assert client.get("/map/pickup-route/999999").status_code == 404


def test_pickup_route_after_a_recovery(client) -> None:
    """SH.docx §6.3: [driver, pickup, destination] waypoints."""
    disruption = client.post("/simulate/inject-disruption",
                             json={"type": "MISPLACE_SHIPMENT"}).json()
    client.post(f"/simulate/recover/{disruption['target_id']}")

    awarded = [a for a in client.get("/auctions").json() if a["winning_vehicle_id"]]
    if not awarded:
        pytest.skip("no awarded auction in this world")

    body = client.get(f"/map/pickup-route/{awarded[0]['id']}").json()
    assert [w["role"] for w in body["waypoints"]] == ["driver", "pickup", "destination"]
    assert body["detour_km"] >= 0
    assert decode_polyline(body["fallback_polyline"])


# --- real E1 heat (loads the 205 MB model) -------------------------------

@pytest.mark.slow
def test_heat_uses_e1_and_responds_to_the_hour(client) -> None:
    """The slider must show the model's real response to hour_of_day."""
    from app.engines.e1_misplacement.registry import get_registry

    get_registry().load()

    morning = client.get("/map/heat", params={"hour": 4}).json()
    evening = client.get("/map/heat", params={"hour": 17}).json()

    assert morning["source"].startswith("E1 model")
    assert morning["legs_scored"] > 0
    for point in morning["points"]:
        assert 0.0 <= point["w"] <= 1.0

    assert morning["hub_risk"] != evening["hub_risk"], \
        "E1 heat did not change with the hour"


def test_heat_cache_is_not_reused_across_different_worlds(client, monkeypatch) -> None:
    """Regression: SQLite reuses row ids after a rebuild, so an id-based cache
    key served the previous world's risk to a different-seed world."""
    from app.services import mapdata

    calls = []

    class CountingRegistry:
        is_loaded = True

        def predict_batch(self, rows):
            calls.append(len(rows))
            return [0.5 for _ in rows]

    monkeypatch.setattr(mapdata, "get_registry", lambda: CountingRegistry())
    mapdata._risk_cache.clear()

    spec = {"hub_count": 12, "vehicle_count": 40, "shipment_count": 120, "leg_count": 150}
    client.post("/simulate/reset", json={"seed": 11, **spec})
    client.get("/map/heat", params={"hour": 9})
    client.post("/simulate/reset", json={"seed": 12, **spec})
    client.get("/map/heat", params={"hour": 9})

    assert len(calls) == 2, "second world was served the first world's cached risk"


def test_heat_cache_is_reused_for_an_unchanged_world(client, monkeypatch) -> None:
    from app.services import mapdata

    calls = []

    class CountingRegistry:
        is_loaded = True

        def predict_batch(self, rows):
            calls.append(len(rows))
            return [0.5 for _ in rows]

    monkeypatch.setattr(mapdata, "get_registry", lambda: CountingRegistry())
    mapdata._risk_cache.clear()

    client.get("/map/heat", params={"hour": 10})
    client.get("/map/heat", params={"hour": 10})
    assert len(calls) == 1
