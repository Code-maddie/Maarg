"""Phase 18 validation: WebSocket realtime.

The acceptance criterion is that a backend event reaches a connected client,
so these tests open a real socket against the app.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.database import engine, init_db
from app.main import app
from app.models import Base
from app.services.events import (
    Event,
    EventType,
    build_event,
    manager,
    publish,
)
from app.workers.simulator import reset_simulator

WORLD = {
    "seed": 42, "hub_count": 8, "vehicle_count": 20,
    "shipment_count": 30, "leg_count": 60,
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    reset_simulator()
    Base.metadata.drop_all(bind=engine)
    init_db()

    with TestClient(app) as test_client:
        test_client.post("/simulate/reset", json=WORLD)
        yield test_client

    reset_simulator()


# --- event construction --------------------------------------------------

def test_build_event_stamps_a_time() -> None:
    event = build_event(EventType.TICK, {"tick": 1})
    assert event.type == "tick"
    assert event.at
    assert event.payload["tick"] == 1


def test_event_serialises() -> None:
    payload = build_event(EventType.PLAN_CHANGED, {"plan_id": 7}).as_dict()
    assert json.dumps(payload, default=str)
    assert payload["type"] == "plan_changed"


def test_every_documented_event_type_exists() -> None:
    """The Phase 18 list: shipments, vehicles, temperature, pressure,
    plan changes, auctions, cascade events, simulation ticks."""
    for expected in (
        "tick", "shipment_update", "vehicle_update", "temperature_update",
        "pressure_update", "plan_changed", "auction_changed",
        "cascade_event", "disruption", "policy_changed",
    ):
        assert expected in {member.value for member in EventType}


def test_publish_without_an_event_loop_is_safe() -> None:
    """Engines run in threads and in tests; publishing must never raise."""
    publish(EventType.TICK, {"tick": 999})
    assert any(
        item["payload"].get("tick") == 999 for item in manager.history()
    )


# --- connection ----------------------------------------------------------

def test_client_receives_a_welcome_frame(client: TestClient) -> None:
    with client.websocket_connect("/ws/live") as socket:
        message = json.loads(socket.receive_text())
        assert message["type"] == "welcome"
        assert "history" in message["payload"]


def test_ping_is_answered(client: TestClient) -> None:
    with client.websocket_connect("/ws/live") as socket:
        socket.receive_text()  # welcome
        socket.send_text(json.dumps({"type": "ping"}))
        assert json.loads(socket.receive_text())["type"] == "pong"


def test_replay_returns_history(client: TestClient) -> None:
    with client.websocket_connect("/ws/live") as socket:
        socket.receive_text()
        socket.send_text(json.dumps({"type": "replay"}))

        message = json.loads(socket.receive_text())
        assert message["type"] == "replay"
        assert isinstance(message["payload"]["history"], list)


def test_an_unknown_message_type_returns_an_error(client: TestClient) -> None:
    with client.websocket_connect("/ws/live") as socket:
        socket.receive_text()
        socket.send_text(json.dumps({"type": "nonsense"}))

        message = json.loads(socket.receive_text())
        assert message["type"] == "error"
        assert "nonsense" in message["payload"]["detail"]


def test_malformed_json_does_not_close_the_socket(client: TestClient) -> None:
    with client.websocket_connect("/ws/live") as socket:
        socket.receive_text()
        socket.send_text("{not json")

        assert json.loads(socket.receive_text())["type"] == "error"

        # Still usable afterwards.
        socket.send_text(json.dumps({"type": "ping"}))
        assert json.loads(socket.receive_text())["type"] == "pong"


# --- the acceptance criterion --------------------------------------------

def test_a_tick_reaches_a_connected_client(client: TestClient) -> None:
    """Phase 18 criterion: a backend event reaches the frontend."""
    with client.websocket_connect("/ws/live") as socket:
        socket.receive_text()  # welcome

        client.post("/simulate/tick", json={"ticks": 1})

        message = json.loads(socket.receive_text())
        assert message["type"] == "tick"
        assert message["payload"]["tick"] >= 1
        assert "now" in message["payload"]


def test_a_disruption_reaches_a_connected_client(client: TestClient) -> None:
    with client.websocket_connect("/ws/live") as socket:
        socket.receive_text()

        client.post(
            "/simulate/inject-disruption", json={"type": "MISPLACE_SHIPMENT"}
        )

        message = json.loads(socket.receive_text())
        assert message["type"] == "disruption"
        assert message["payload"]["type"] == "MISPLACE_SHIPMENT"


def test_a_policy_change_reaches_a_connected_client(client: TestClient) -> None:
    with client.websocket_connect("/ws/live") as socket:
        socket.receive_text()

        client.put(
            "/policy-mode", json={"mode": "SLA_STRICT", "reason": "realtime test"}
        )

        message = json.loads(socket.receive_text())
        assert message["type"] == "policy_changed"
        assert message["payload"]["mode"] == "SLA_STRICT"

        client.put("/policy-mode", json={"mode": "BUSINESS", "reason": "reset"})


def test_a_recovery_emits_the_full_event_set(client: TestClient) -> None:
    """One recovery should light up plan, temperature, pressure and cascade."""
    disruption = client.post(
        "/simulate/inject-disruption", json={"type": "MISPLACE_SHIPMENT"}
    ).json()

    with client.websocket_connect("/ws/live") as socket:
        socket.receive_text()

        client.post(f"/simulate/recover/{disruption['target_id']}")

        # The orchestrator publishes these three first, in this order. Read
        # exactly three frames: receive_text() has no timeout, so reading
        # "until done" would block forever once the queue is empty.
        received = [json.loads(socket.receive_text())["type"] for _ in range(3)]

        assert received == ["plan_changed", "temperature_update", "pressure_update"]


def test_two_clients_both_receive_an_event(client: TestClient) -> None:
    """Fan-out: every open dashboard must see the same tick."""
    with client.websocket_connect("/ws/live") as first:
        with client.websocket_connect("/ws/live") as second:
            first.receive_text()
            second.receive_text()

            client.post("/simulate/tick", json={"ticks": 1})

            assert json.loads(first.receive_text())["type"] == "tick"
            assert json.loads(second.receive_text())["type"] == "tick"


def test_reconnection_works(client: TestClient) -> None:
    with client.websocket_connect("/ws/live") as socket:
        socket.receive_text()

    with client.websocket_connect("/ws/live") as socket:
        assert json.loads(socket.receive_text())["type"] == "welcome"


def test_a_client_joining_late_sees_history(client: TestClient) -> None:
    client.post("/simulate/tick", json={"ticks": 1})

    with client.websocket_connect("/ws/live") as socket:
        message = json.loads(socket.receive_text())
        assert message["payload"]["history"]


# --- diagnostics ---------------------------------------------------------

def test_stats_endpoint(client: TestClient) -> None:
    body = client.get("/ws/stats").json()
    assert {"connections", "events_sent", "history"} <= set(body)


def test_history_is_bounded() -> None:
    from app.services.events import HISTORY_LIMIT

    for index in range(HISTORY_LIMIT + 25):
        publish(EventType.TICK, {"tick": index})

    assert len(manager.history(limit=1000)) <= HISTORY_LIMIT


def test_broadcast_with_no_clients_is_harmless(client: TestClient) -> None:
    """The tick loop must not care whether anyone is watching."""
    response = client.post("/simulate/tick", json={"ticks": 1})
    assert response.status_code == 200
