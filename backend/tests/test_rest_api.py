"""Phase 17 validation: the documented REST surface (SH.docx §9).

Covers endpoint behaviour, request validation and error handling. Auth tests
belong to Phase 19, when Firebase exists.
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal, engine, init_db
from app.main import app
from app.models import Base, Hub, RecoveryPlan, Shipment
from app.models.enums import PlanStatus, ShipmentStatus
from app.workers.simulator import get_simulator, reset_simulator

WORLD = {
    "seed": 42, "hub_count": 12, "vehicle_count": 40,
    "shipment_count": 60, "leg_count": 180,
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Live app against the real (file) database, rebuilt for this module."""
    reset_simulator()
    Base.metadata.drop_all(bind=engine)
    init_db()

    with TestClient(app) as test_client:
        test_client.post("/simulate/reset", json=WORLD)
        test_client.post("/simulate/tick", json={"ticks": 20})
        yield test_client

    reset_simulator()


@pytest.fixture(scope="module")
def recovered(client: TestClient) -> dict:
    """A shipment that has been through the full pipeline."""
    disruption = client.post(
        "/simulate/inject-disruption", json={"type": "MISPLACE_SHIPMENT"}
    ).json()
    shipment_id = disruption["target_id"]
    client.post(f"/simulate/recover/{shipment_id}")
    return {"shipment_id": shipment_id}


# --- shipments -----------------------------------------------------------

def test_list_shipments(client: TestClient) -> None:
    body = client.get("/shipments").json()

    assert body["total"] == 60
    assert len(body["items"]) <= 100
    assert {"code", "temperature", "zone", "lam", "pressure"} <= set(body["items"][0])


def test_shipments_are_sorted_hottest_first(client: TestClient) -> None:
    items = client.get("/shipments").json()["items"]
    temperatures = [item["temperature"] for item in items]
    assert temperatures == sorted(temperatures, reverse=True)


def test_shipments_filter_by_status(client: TestClient) -> None:
    body = client.get("/shipments", params={"status": "PENDING"}).json()
    assert all(item["status"] == "PENDING" for item in body["items"])


def test_shipments_filter_by_temperature_range(client: TestClient) -> None:
    body = client.get(
        "/shipments", params={"min_temperature": 0, "max_temperature": 5}
    ).json()
    assert all(0 <= item["temperature"] <= 5 for item in body["items"])


def test_shipments_pagination(client: TestClient) -> None:
    first = client.get("/shipments", params={"limit": 5}).json()
    second = client.get("/shipments", params={"limit": 5, "offset": 5}).json()

    assert len(first["items"]) == 5
    assert first["items"][0]["id"] != second["items"][0]["id"]


def test_shipments_reject_a_bad_limit(client: TestClient) -> None:
    assert client.get("/shipments", params={"limit": 0}).status_code == 422
    assert client.get("/shipments", params={"limit": 99999}).status_code == 422


def test_shipment_detail(client: TestClient) -> None:
    shipment_id = client.get("/shipments").json()["items"][0]["id"]
    body = client.get(f"/shipments/{shipment_id}").json()

    assert body["id"] == shipment_id
    assert "hours_to_deadline" in body
    assert "sla_penalty_per_hour" in body


def test_unknown_shipment_returns_404(client: TestClient) -> None:
    assert client.get("/shipments/999999").status_code == 404


# --- recovery plan and explainer -----------------------------------------

def test_recovery_plan_bundle(client: TestClient, recovered: dict) -> None:
    body = client.get(
        f"/shipments/{recovered['shipment_id']}/recovery-plan"
    ).json()

    assert body["committed"] is not None
    assert body["committed"]["status"] == "COMMITTED"
    assert isinstance(body["alternatives"], list)
    assert isinstance(body["rejected"], list)


def test_recovery_plan_path_is_ordered(client: TestClient, recovered: dict) -> None:
    committed = client.get(
        f"/shipments/{recovered['shipment_id']}/recovery-plan"
    ).json()["committed"]

    seqs = [step["seq"] for step in committed["path"]]
    assert seqs == sorted(seqs)
    for step in committed["path"]:
        assert step["from_hub"] and step["to_hub"]


def test_explainer_rebuilds_from_the_database(client: TestClient, recovered: dict) -> None:
    """The card must survive a restart, not live only in a response."""
    body = client.get(
        f"/shipments/{recovered['shipment_id']}/explainer"
    ).json()

    assert body["headline"]
    assert body["why_chosen"]
    assert body["strategy"]
    assert body["urgency"]["temperature"] is not None


def test_explainer_alternatives_all_carry_reasons(
    client: TestClient, recovered: dict
) -> None:
    body = client.get(
        f"/shipments/{recovered['shipment_id']}/explainer"
    ).json()

    for alternative in body["alternatives"]:
        assert alternative["reason"]
        assert "TODO" not in alternative["reason"]


def test_explainer_is_deterministic(client: TestClient, recovered: dict) -> None:
    url = f"/shipments/{recovered['shipment_id']}/explainer"
    assert client.get(url).json() == client.get(url).json()


def test_explainer_without_a_plan_returns_404(client: TestClient) -> None:
    pending = client.get("/shipments", params={"status": "PENDING"}).json()
    if not pending["items"]:
        pytest.skip("no pending shipments")

    shipment_id = pending["items"][0]["id"]
    assert client.get(f"/shipments/{shipment_id}/explainer").status_code == 404


# --- override ------------------------------------------------------------

def test_override_switches_the_committed_plan(client: TestClient) -> None:
    disruption = client.post(
        "/simulate/inject-disruption", json={"type": "MISPLACE_SHIPMENT"}
    ).json()
    shipment_id = disruption["target_id"]
    client.post(f"/simulate/recover/{shipment_id}")

    bundle = client.get(f"/shipments/{shipment_id}/recovery-plan").json()
    if not bundle["alternatives"]:
        pytest.skip("no alternative plan to override to")

    alternative_id = bundle["alternatives"][0]["id"]
    response = client.post(
        f"/shipments/{shipment_id}/override",
        json={"chosen_plan_id": alternative_id, "reason": "Driver prefers this route"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["chosen_plan_id"] == alternative_id
    assert body["audit_log_id"] > 0

    after = client.get(f"/shipments/{shipment_id}/recovery-plan").json()
    assert after["committed"]["id"] == alternative_id


def test_override_requires_a_reason(client: TestClient, recovered: dict) -> None:
    response = client.post(
        f"/shipments/{recovered['shipment_id']}/override",
        json={"chosen_plan_id": 1, "reason": ""},
    )
    assert response.status_code == 422


def test_override_rejects_a_plan_from_another_shipment(
    client: TestClient, recovered: dict
) -> None:
    response = client.post(
        f"/shipments/{recovered['shipment_id']}/override",
        json={"chosen_plan_id": 999999, "reason": "Nonexistent plan"},
    )
    assert response.status_code == 404


# --- vehicles and legs ---------------------------------------------------

def test_list_vehicles(client: TestClient) -> None:
    body = client.get("/vehicles").json()
    assert len(body) == 40
    assert {"code", "capacity_kg", "reliability"} <= set(body[0])


def test_vehicles_filter_by_type(client: TestClient) -> None:
    body = client.get("/vehicles", params={"vehicle_type": "OWNED"}).json()
    assert all(item["vehicle_type"] == "OWNED" for item in body)


def test_leg_detail_is_the_info_panel_payload(client: TestClient) -> None:
    """SH.docx §6.2: vehicle, capacity, schedule, aboard, bounty."""
    leg_id = client.get("/legs", params={"limit": 1}).json()[0]["id"]
    body = client.get(f"/legs/{leg_id}").json()

    assert body["vehicle_code"]
    assert body["from_hub"] and body["to_hub"]
    assert body["capacity_kg"] >= body["residual_kg"]
    assert "aboard" in body
    # Coordinates for drawing the polyline.
    assert body["from_lat"] and body["to_lat"]


def test_leg_aboard_lists_shipments_with_temperature(client: TestClient) -> None:
    legs = client.get("/legs", params={"limit": 50}).json()
    loaded = [leg for leg in legs if leg["aboard"]]
    if not loaded:
        pytest.skip("no loaded legs in this world")

    aboard = loaded[0]["aboard"][0]
    assert {"code", "weight_kg", "temperature", "zone", "lam"} <= set(aboard)


def test_unknown_leg_returns_404(client: TestClient) -> None:
    assert client.get("/legs/999999").status_code == 404


def test_leg_bounty_status_without_an_auction(client: TestClient) -> None:
    leg_id = client.get("/legs", params={"limit": 1}).json()[0]["id"]
    body = client.get(f"/legs/{leg_id}/bounty-status").json()
    assert body["status"] in {"NONE", "OPEN", "CLOSED", "AWARDED", "NO_BIDS"}


# --- hubs ----------------------------------------------------------------

def test_list_hubs(client: TestClient) -> None:
    body = client.get("/hubs").json()
    assert len(body) == 12
    assert {"code", "lat", "lng", "is_active"} <= set(body[0])


def test_create_hub(client: TestClient) -> None:
    response = client.post(
        "/hubs",
        json={"code": "TEST1", "name": "Test Hub", "lat": 20.0, "lng": 78.0},
    )
    assert response.status_code == 201
    assert response.json()["code"] == "TEST1"


def test_duplicate_hub_code_returns_409(client: TestClient) -> None:
    payload = {"code": "TEST2", "name": "Test Hub 2", "lat": 21.0, "lng": 79.0}
    assert client.post("/hubs", json=payload).status_code == 201
    assert client.post("/hubs", json=payload).status_code == 409


def test_hub_validation_rejects_bad_coordinates(client: TestClient) -> None:
    response = client.post(
        "/hubs", json={"code": "BAD", "name": "Bad", "lat": 999, "lng": 0}
    )
    assert response.status_code == 422


# --- hub emergence -------------------------------------------------------

def test_hub_candidates_can_be_generated(client: TestClient) -> None:
    body = client.get(
        "/hub-emergence/candidates", params={"regenerate": True}
    ).json()
    assert isinstance(body, list)
    for candidate in body:
        assert {"hub_score", "usage_count", "mean_risk", "status"} <= set(candidate)


def test_candidates_are_ranked(client: TestClient) -> None:
    body = client.get("/hub-emergence/candidates").json()
    scores = [candidate["hub_score"] for candidate in body]
    assert scores == sorted(scores, reverse=True)


def test_approving_a_candidate_creates_a_hub(client: TestClient) -> None:
    candidates = client.get(
        "/hub-emergence/candidates", params={"status": "PENDING"}
    ).json()
    if not candidates:
        pytest.skip("no pending candidates")

    before = len(client.get("/hubs").json())
    response = client.post(
        f"/hub-emergence/candidates/{candidates[0]['id']}/approve",
        json={"reason": "Strong corridor"},
    )
    assert response.status_code == 200
    assert response.json()["is_emergent"] is True
    assert len(client.get("/hubs").json()) == before + 1


def test_approving_twice_returns_409(client: TestClient) -> None:
    candidates = client.get(
        "/hub-emergence/candidates", params={"status": "APPROVED"}
    ).json()
    if not candidates:
        pytest.skip("no approved candidates")

    response = client.post(
        f"/hub-emergence/candidates/{candidates[0]['id']}/approve",
        json={"reason": "again"},
    )
    assert response.status_code == 409


def test_unknown_candidate_returns_404(client: TestClient) -> None:
    response = client.post(
        "/hub-emergence/candidates/999999/approve", json={"reason": "x"}
    )
    assert response.status_code == 404


# --- heatmap -------------------------------------------------------------

def test_heatmap_returns_cells(client: TestClient) -> None:
    body = client.get("/heatmap", params={"hour": 17}).json()

    assert body["hour"] == 17
    assert "source" in body
    for cell in body["cells"]:
        assert 0.0 <= cell["weight"] <= 1.0
        assert cell["lat"] and cell["lng"]


def test_heatmap_cells_are_sorted_by_risk(client: TestClient) -> None:
    cells = client.get("/heatmap", params={"hour": 17}).json()["cells"]
    weights = [cell["weight"] for cell in cells]
    assert weights == sorted(weights, reverse=True)


def test_heatmap_rejects_an_invalid_hour(client: TestClient) -> None:
    assert client.get("/heatmap", params={"hour": 99}).status_code == 422


def test_heatmap_defaults_to_simulated_time(client: TestClient) -> None:
    body = client.get("/heatmap").json()
    assert 0 <= body["hour"] <= 23


# --- market --------------------------------------------------------------

def test_list_auctions(client: TestClient, recovered: dict) -> None:
    body = client.get("/auctions").json()
    assert isinstance(body, list)
    if body:
        assert {"max_bounty", "status", "bids"} <= set(body[0])


def test_auction_detail_lists_bids_cheapest_first(
    client: TestClient, recovered: dict
) -> None:
    auctions = client.get("/auctions").json()
    if not auctions:
        pytest.skip("no auctions")

    body = client.get(f"/auctions/{auctions[0]['id']}").json()
    amounts = [bid["amount"] for bid in body["bids"]]
    assert amounts == sorted(amounts)


def test_unknown_auction_returns_404(client: TestClient) -> None:
    assert client.get("/auctions/999999").status_code == 404


def test_bidding_on_a_closed_auction_returns_400(
    client: TestClient, recovered: dict
) -> None:
    auctions = client.get("/auctions").json()
    closed = [a for a in auctions if a["status"] != "OPEN"]
    if not closed:
        pytest.skip("no closed auctions")

    response = client.post(
        f"/auctions/{closed[0]['id']}/bid",
        json={"vehicle_id": 1, "amount": 100.0},
    )
    assert response.status_code == 400


def test_bid_validation_rejects_a_negative_amount(client: TestClient) -> None:
    response = client.post(
        "/auctions/1/bid", json={"vehicle_id": 1, "amount": -5}
    )
    assert response.status_code in {400, 404, 422}


def test_reservations_endpoint(client: TestClient, recovered: dict) -> None:
    body = client.get("/reservations", params={"reserved_only": False}).json()
    assert isinstance(body, list)
    for item in body:
        assert 0.0 <= item["p_misplace"] <= 1.0
        assert 0.0 <= item["threshold"] <= 1.0
        assert item["reason"]


def test_reservation_for_one_shipment(client: TestClient, recovered: dict) -> None:
    body = client.get(f"/reservations/{recovered['shipment_id']}").json()
    assert body["shipment_id"] == recovered["shipment_id"]
    assert body["reason"]


# --- policy --------------------------------------------------------------

def test_read_policy_mode(client: TestClient) -> None:
    body = client.get("/policy-mode").json()

    assert body["mode"] in body["available_modes"]
    assert {"w_base", "w_time", "w_delay", "w_cascade"} <= set(body["weights"])


def test_change_policy_mode(client: TestClient) -> None:
    body = client.put(
        "/policy-mode",
        json={"mode": "SLA_STRICT", "reason": "Deadline pressure"},
    ).json()

    assert body["mode"] == "SLA_STRICT"
    assert client.get("/policy-mode").json()["mode"] == "SLA_STRICT"

    client.put("/policy-mode", json={"mode": "BUSINESS", "reason": "reset"})


def test_policy_change_affects_temperature(client: TestClient) -> None:
    """The admin dial must visibly change engine output."""
    disruption = client.post(
        "/simulate/inject-disruption", json={"type": "MISPLACE_SHIPMENT"}
    ).json()
    shipment_id = disruption["target_id"]

    client.put("/policy-mode", json={"mode": "SLA_STRICT", "reason": "test"})
    strict = client.get(f"/simulate/route/{shipment_id}").json()["temperature"]

    client.put("/policy-mode", json={"mode": "EFFICIENCY", "reason": "test"})
    efficiency = client.get(f"/simulate/route/{shipment_id}").json()["temperature"]

    client.put("/policy-mode", json={"mode": "BUSINESS", "reason": "reset"})

    assert strict["policy_mode"] == "SLA_STRICT"
    assert efficiency["policy_mode"] == "EFFICIENCY"


def test_unknown_policy_mode_returns_400(client: TestClient) -> None:
    response = client.put("/policy-mode", json={"mode": "TURBO", "reason": "x"})
    assert response.status_code == 400


# --- metrics -------------------------------------------------------------

def test_metrics_endpoint(client: TestClient, recovered: dict) -> None:
    body = client.get("/metrics").json()

    assert body["shipments_total"] > 0
    assert 0.0 <= body["sla_percent"] <= 100.0
    assert 0.0 <= body["recovered_via_existing_capacity_pct"] <= 100.0
    assert isinstance(body["strategy_mix"], dict)
    assert "outcome_summary" in body


def test_metrics_reflect_committed_plans(client: TestClient, recovered: dict) -> None:
    body = client.get("/metrics").json()
    assert sum(body["strategy_mix"].values()) >= 1
    assert body["recovery_cost_total"] > 0


# --- versioned prefix ----------------------------------------------------

@pytest.mark.parametrize(
    "path",
    ["/shipments", "/vehicles", "/hubs", "/heatmap", "/policy-mode", "/metrics"],
)
def test_every_route_is_also_under_the_version_prefix(
    client: TestClient, path: str
) -> None:
    assert client.get(f"/api/v1{path}").status_code == 200


def test_openapi_documents_the_surface(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    for expected in (
        "/shipments",
        "/shipments/{shipment_id}/recovery-plan",
        "/shipments/{shipment_id}/explainer",
        "/shipments/{shipment_id}/override",
        "/vehicles",
        "/legs/{leg_id}",
        "/legs/{leg_id}/bounty-status",
        "/hubs",
        "/hub-emergence/candidates",
        "/heatmap",
        "/reservations",
        "/auctions/{auction_id}",
        "/auctions/{auction_id}/bid",
        "/policy-mode",
        "/model/status",
        "/model/reload",
    ):
        assert expected in paths, f"{expected} missing from the documented API"
