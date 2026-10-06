"""Phase 19 validation: Firebase authentication, roles and notifications.

Token verification is substituted with a deterministic fake, so these tests
never contact the live Firebase project. Everything *around* verification —
header parsing, role mapping, guards, auditing, WebSocket auth, degradation —
runs for real.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import security
from app.core.config import Settings, settings
from app.core.database import SessionLocal, engine, init_db
from app.main import app
from app.models import AuditLog, Base, User
from app.models.enums import AuditAction, UserRole
from app.services import notifications
from app.workers.simulator import reset_simulator


class InvalidIdTokenError(Exception):
    """Mimics firebase_admin.auth.InvalidIdTokenError by name."""


class ExpiredIdTokenError(Exception):
    """Mimics firebase_admin.auth.ExpiredIdTokenError by name."""


TOKENS = {
    "admin-token": {"uid": "u-admin", "email": "admin@test.local", "role": "admin"},
    "dispatcher-token": {"uid": "u-disp", "email": "disp@test.local", "role": "dispatcher"},
    "driver-token": {"uid": "u-driver", "email": "driver@test.local", "role": "driver"},
    "customer-token": {"uid": "u-cust", "email": "cust@test.local", "role": "customer"},
    "norole-token": {"uid": "u-norole", "email": "norole@test.local"},
    "escalate-token": {"uid": "u-esc", "email": "esc@test.local", "role": "superuser"},
}


def fake_verify(token: str) -> dict:
    if token == "expired-token":
        raise ExpiredIdTokenError("expired")
    if token not in TOKENS:
        raise InvalidIdTokenError("bad signature")
    return dict(TOKENS[token])


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    """App with auth ENFORCED and a fake verifier."""
    monkeypatch.setattr(settings, "auth_mode", "firebase")
    monkeypatch.setattr(settings, "e1_eager_load", False)
    monkeypatch.setattr(security, "_firebase_app", SimpleNamespace(project_id="test-project"))
    monkeypatch.setattr(security, "_init_error", None)
    monkeypatch.setattr(security, "_verify_id_token", fake_verify)

    reset_simulator()
    Base.metadata.drop_all(bind=engine)
    init_db()

    with TestClient(app) as test_client:
        test_client.post(
            "/simulate/reset",
            json={"seed": 42, "hub_count": 6, "vehicle_count": 10,
                  "shipment_count": 15, "leg_count": 30},
            headers=bearer("admin-token"),
        )
        yield test_client

    reset_simulator()


# --- public routes -------------------------------------------------------

@pytest.mark.parametrize("path", ["/health", "/ready", "/auth/status", "/"])
def test_probes_and_auth_status_are_public(client, path) -> None:
    assert client.get(path).status_code == 200


def test_auth_status_reports_mode_without_secrets(client) -> None:
    body = client.get("/auth/status").json()

    assert body["auth_mode"] == "firebase"
    assert body["initialised"] is True
    serialised = json.dumps(body)
    assert "private_key" not in serialised
    assert "BEGIN PRIVATE KEY" not in serialised


# --- token handling ------------------------------------------------------

def test_missing_token_is_rejected(client) -> None:
    response = client.get("/shipments")
    assert response.status_code == 401
    assert "Missing Authorization" in response.json()["detail"]


@pytest.mark.parametrize("header", ["Token abc", "Bearer", "Bearer   ", "abc"])
def test_malformed_header_is_rejected(client, header) -> None:
    response = client.get("/shipments", headers={"Authorization": header})
    assert response.status_code == 401


def test_invalid_token_is_rejected(client) -> None:
    """Phase 19 criterion: an invalid token is rejected."""
    response = client.get("/shipments", headers=bearer("forged-token"))
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"]


def test_expired_token_is_rejected_with_the_reason(client) -> None:
    response = client.get("/shipments", headers=bearer("expired-token"))
    assert response.status_code == 401
    assert "expired" in response.json()["detail"]


def test_valid_token_is_accepted(client) -> None:
    """Phase 19 criterion: a valid token is accepted."""
    assert client.get("/shipments", headers=bearer("customer-token")).status_code == 200


def test_401_carries_www_authenticate(client) -> None:
    assert client.get("/shipments").headers.get("www-authenticate") == "Bearer"


@pytest.mark.parametrize(
    "path",
    ["/shipments", "/vehicles", "/legs", "/hubs", "/heatmap", "/metrics",
     "/policy-mode", "/auctions", "/reservations", "/model/status",
     "/simulate/state", "/hub-emergence/candidates", "/auth/me"],
)
def test_every_data_route_requires_a_token(client, path) -> None:
    """SH.docx §9: 'All routes require a verified Firebase ID token.'"""
    assert client.get(path).status_code == 401


# --- identity and role mapping -------------------------------------------

def test_me_reports_the_verified_role(client) -> None:
    body = client.get("/auth/me", headers=bearer("dispatcher-token")).json()
    assert body["uid"] == "u-disp"
    assert body["role"] == "DISPATCHER"
    assert body["dev_bypass"] is False


def test_a_token_with_no_role_gets_least_privilege(client) -> None:
    assert client.get("/auth/me", headers=bearer("norole-token")).json()["role"] == "CUSTOMER"


def test_an_unknown_role_claim_is_never_escalated(client) -> None:
    """A 'superuser' claim must not become admin."""
    body = client.get("/auth/me", headers=bearer("escalate-token")).json()
    assert body["role"] == "CUSTOMER"

    response = client.put(
        "/policy-mode", json={"mode": "SLA_STRICT"}, headers=bearer("escalate-token")
    )
    assert response.status_code == 403


def test_a_user_row_is_synced_on_first_request(client) -> None:
    client.get("/auth/me", headers=bearer("driver-token"))

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.firebase_uid == "u-driver"))
    assert user is not None
    assert user.role == "DRIVER"
    assert user.email == "driver@test.local"


# --- role gate (acceptance criterion) ------------------------------------

@pytest.mark.parametrize(
    ("token", "allowed"),
    [("admin-token", True), ("dispatcher-token", False),
     ("driver-token", False), ("customer-token", False)],
)
def test_policy_mode_is_admin_only(client, token, allowed) -> None:
    """Phase 19 criterion: role gate enforced."""
    response = client.put(
        "/policy-mode", json={"mode": "BUSINESS", "reason": "t"}, headers=bearer(token)
    )
    assert (response.status_code == 200) is allowed
    if not allowed:
        assert response.status_code == 403
        assert "not permitted" in response.json()["detail"]


@pytest.mark.parametrize(
    ("token", "allowed"),
    [("admin-token", True), ("dispatcher-token", True),
     ("driver-token", False), ("customer-token", False)],
)
def test_override_requires_dispatcher(client, token, allowed) -> None:
    response = client.post(
        "/shipments/1/override",
        json={"chosen_plan_id": 999999, "reason": "role test"},
        headers=bearer(token),
    )
    # An allowed caller gets past the guard and hits the 404 for the bogus
    # plan; a forbidden caller is stopped at 403 before any lookup.
    assert response.status_code == (404 if allowed else 403)


@pytest.mark.parametrize(
    ("token", "allowed"),
    [("admin-token", True), ("driver-token", True),
     ("dispatcher-token", False), ("customer-token", False)],
)
def test_bidding_requires_driver(client, token, allowed) -> None:
    response = client.post(
        "/auctions/999999/bid", json={"vehicle_id": 1, "amount": 100.0},
        headers=bearer(token),
    )
    assert response.status_code == (404 if allowed else 403)


@pytest.mark.parametrize(
    ("token", "expected"),
    [("admin-token", 200), ("dispatcher-token", 403), ("driver-token", 403)],
)
def test_world_reset_is_admin_only(client, token, expected) -> None:
    response = client.post(
        "/simulate/reset",
        json={"seed": 1, "hub_count": 4, "vehicle_count": 5,
              "shipment_count": 5, "leg_count": 10},
        headers=bearer(token),
    )
    assert response.status_code == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [("dispatcher-token", 200), ("admin-token", 200),
     ("driver-token", 403), ("customer-token", 403)],
)
def test_demo_controls_require_dispatcher(client, token, expected) -> None:
    response = client.post(
        "/simulate/tick", json={"ticks": 1}, headers=bearer(token)
    )
    assert response.status_code == expected


@pytest.mark.parametrize("token", ["dispatcher-token", "driver-token", "customer-token"])
def test_model_reload_is_admin_only(client, token) -> None:
    assert client.post("/model/reload", headers=bearer(token)).status_code == 403


@pytest.mark.parametrize("token", ["dispatcher-token", "driver-token"])
def test_hub_admin_routes_are_admin_only(client, token) -> None:
    assert client.post(
        "/hubs", json={"code": "ZZ1", "name": "Z", "lat": 1, "lng": 1},
        headers=bearer(token),
    ).status_code == 403
    assert client.post(
        "/hub-emergence/candidates/1/approve", json={"reason": "x"},
        headers=bearer(token),
    ).status_code == 403


def test_reads_are_open_to_every_authenticated_role(client) -> None:
    for token in ("admin-token", "dispatcher-token", "driver-token", "customer-token"):
        assert client.get("/shipments", headers=bearer(token)).status_code == 200


# --- auditing names the real actor ---------------------------------------

def test_audit_entries_record_the_actor(client) -> None:
    """SH.docx §12: overriding actions are attributable."""
    client.put(
        "/policy-mode", json={"mode": "FAIRNESS", "reason": "audit test"},
        headers=bearer("admin-token"),
    )

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.firebase_uid == "u-admin"))
        entry = db.scalars(
            select(AuditLog)
            .where(AuditLog.action == AuditAction.CHANGE_POLICY_MODE.value)
            .order_by(AuditLog.id.desc())
        ).first()

    assert entry is not None
    assert entry.actor_user_id == admin.id
    assert entry.reason_text == "audit test"


# --- role assignment -----------------------------------------------------

def test_admin_can_assign_a_role(client, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "firebase_admin.auth.set_custom_user_claims",
        lambda uid, claims, app=None: calls.append((uid, claims)),
    )

    response = client.post(
        "/users/some-uid/role", json={"role": "DRIVER", "reason": "onboarding"},
        headers=bearer("admin-token"),
    )

    assert response.status_code == 200
    assert calls == [("some-uid", {"role": "driver"})]

    with SessionLocal() as db:
        entry = db.scalar(
            select(AuditLog).where(AuditLog.action == AuditAction.SET_USER_ROLE.value)
        )
    assert entry is not None and "some-uid" in entry.reason_text


def test_non_admin_cannot_assign_roles(client) -> None:
    response = client.post(
        "/users/x/role", json={"role": "ADMIN"}, headers=bearer("dispatcher-token")
    )
    assert response.status_code == 403


def test_assigning_an_unknown_role_is_rejected(client) -> None:
    response = client.post(
        "/users/x/role", json={"role": "OVERLORD"}, headers=bearer("admin-token")
    )
    assert response.status_code == 422


# --- WebSocket auth ------------------------------------------------------

def test_websocket_without_token_is_refused(client) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/live") as socket:
            socket.receive_text()
    assert excinfo.value.code == 1008


def test_websocket_with_invalid_token_is_refused(client) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/live?token=forged") as socket:
            socket.receive_text()


def test_websocket_with_valid_token_is_accepted(client) -> None:
    with client.websocket_connect("/ws/live?token=dispatcher-token") as socket:
        assert json.loads(socket.receive_text())["type"] == "welcome"


# --- degradation ---------------------------------------------------------

def test_missing_credentials_degrade_to_503(client, monkeypatch) -> None:
    """A broken Firebase setup must answer clearly, not crash."""
    monkeypatch.setattr(security, "_firebase_app", None)
    monkeypatch.setattr(settings, "firebase_credentials_path", "does/not/exist.json")

    response = client.get("/shipments", headers=bearer("admin-token"))
    assert response.status_code == 503
    assert "Authentication unavailable" in response.json()["detail"]
    # Probes stay green, so the process is not restarted in a loop.
    assert client.get("/health").status_code == 200


# --- configuration safety ------------------------------------------------

def test_auth_bypass_is_refused_in_production() -> None:
    with pytest.raises(ValueError, match="not allowed in production"):
        Settings(environment="production", auth_mode="disabled")


def test_an_unknown_auth_mode_is_refused() -> None:
    with pytest.raises(ValueError, match="AUTH_MODE"):
        Settings(auth_mode="yolo")


def test_auth_mode_is_enforced_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert Settings(_env_file=None).auth_mode == "firebase"


def test_dev_bypass_identifies_itself(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "disabled")
    monkeypatch.setattr(settings, "e1_eager_load", False)
    with TestClient(app) as test_client:
        body = test_client.get("/auth/me").json()
    assert body["dev_bypass"] is True
    assert body["role"] == "ADMIN"


# --- Firestore notifications ---------------------------------------------

class FakeFirestore:
    """Records writes instead of calling the live project."""

    def __init__(self) -> None:
        self.writes = []

    def collection(self, name):
        return _Ref(self, [name])


class _Ref:
    def __init__(self, root, path):
        self.root, self.path = root, path

    def document(self, name):
        return _Ref(self.root, self.path + [name])

    def collection(self, name):
        return _Ref(self.root, self.path + [name])

    def add(self, data):
        self.root.writes.append(("add", "/".join(self.path), data))

    def set(self, data, merge=False):
        self.root.writes.append(("set", "/".join(self.path), data))


def test_notifications_are_noops_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "firestore_enabled", False)
    notifications.reset()
    assert notifications.notify_user("u1", "test", {}) is False
    assert notifications.publish_bounty_offer(
        1, status="OPEN", max_bounty=1.0, shipment_code="S1"
    ) is False


def test_notification_is_written_to_the_documented_path(monkeypatch) -> None:
    """Phase 19 criterion: a notification document is written."""
    fake = FakeFirestore()
    monkeypatch.setattr(notifications, "_firestore", lambda: fake)

    assert notifications.notify_user("u-driver", "bounty_offer", {"auction_id": 7})

    kind, path, data = fake.writes[0]
    assert kind == "add"
    assert path == "notifications/u-driver/items"
    assert data["kind"] == "bounty_offer"
    assert data["read"] is False


def test_bounty_offer_is_written_to_the_documented_path(monkeypatch) -> None:
    fake = FakeFirestore()
    monkeypatch.setattr(notifications, "_firestore", lambda: fake)

    notifications.publish_bounty_offer(
        42, status="AWARDED", max_bounty=8206.67, shipment_code="S00001",
        payment=288.14, winning_vehicle_id=17,
    )

    kind, path, data = fake.writes[0]
    assert (kind, path) == ("set", "bounty_offers/42")
    assert data["payment"] == 288.14


def test_a_failing_firestore_never_raises(monkeypatch) -> None:
    class Broken:
        def collection(self, name):
            raise RuntimeError("quota exceeded")

    monkeypatch.setattr(notifications, "_firestore", lambda: Broken())
    assert notifications.notify_user("u1", "x", {}) is False


# --- credential loading (production vs local) ----------------------------

def test_credentials_are_read_from_the_environment(monkeypatch) -> None:
    """Production supplies the service account as one env var, not a file."""
    seen = {}

    class FakeCredentials:
        @staticmethod
        def Certificate(value):  # noqa: N802 - mirrors the firebase_admin API
            seen["value"] = value
            return "certificate"

    monkeypatch.setattr(
        settings, "firebase_credentials_json", '{"type": "service_account"}'
    )
    assert security._load_certificate(FakeCredentials) == "certificate"
    # Parsed into a dict, never handed over as a raw string.
    assert seen["value"] == {"type": "service_account"}


def test_environment_credentials_take_precedence_over_the_file(monkeypatch) -> None:
    class FakeCredentials:
        @staticmethod
        def Certificate(value):  # noqa: N802
            return value

    monkeypatch.setattr(settings, "firebase_credentials_json", '{"type": "sa"}')
    monkeypatch.setattr(settings, "firebase_credentials_path", "does/not/exist.json")

    # The missing file would otherwise be fatal; the env var wins.
    assert security._load_certificate(FakeCredentials) == {"type": "sa"}


def test_malformed_credential_json_is_reported_not_raised(monkeypatch) -> None:
    """A bad secret must degrade auth, not prevent the service starting."""
    class FakeCredentials:
        @staticmethod
        def Certificate(value):  # noqa: N802
            raise AssertionError("should not be reached")

    monkeypatch.setattr(settings, "firebase_credentials_json", "not json at all")
    assert security._load_certificate(FakeCredentials) is None
    assert "not valid JSON" in security.firebase_status()["error"]


def test_missing_credentials_name_both_options(monkeypatch) -> None:
    class FakeCredentials:
        @staticmethod
        def Certificate(value):  # noqa: N802
            raise AssertionError("should not be reached")

    monkeypatch.setattr(settings, "firebase_credentials_json", "")
    monkeypatch.setattr(settings, "firebase_credentials_path", "does/not/exist.json")

    assert security._load_certificate(FakeCredentials) is None
    error = security.firebase_status()["error"]
    assert "FIREBASE_CREDENTIALS_JSON" in error
    # The path is named, but never the key material.
    assert "exist.json" in error


def test_web_config_prefers_environment_variables(monkeypatch, client) -> None:
    """In production there is no frontend/.env on the backend's disk."""
    monkeypatch.setattr(settings, "firebase_api_key", "env-key")
    monkeypatch.setattr(settings, "firebase_auth_domain", "env.firebaseapp.com")
    monkeypatch.setattr(settings, "firebase_project_id", "env-project")
    monkeypatch.setattr(settings, "firebase_app_id", "env-app")
    monkeypatch.setattr(settings, "frontend_env_path", "does/not/exist")

    body = client.get("/auth/web-config").json()
    assert body["configured"] is True
    assert body["firebase"] == {
        "apiKey": "env-key",
        "authDomain": "env.firebaseapp.com",
        "projectId": "env-project",
        "appId": "env-app",
    }


def test_web_config_never_exposes_service_account_material(monkeypatch, client) -> None:
    monkeypatch.setattr(
        settings,
        "firebase_credentials_json",
        '{"type": "service_account", "private_key": "-----BEGIN PRIVATE KEY-----"}',
    )
    body = client.get("/auth/web-config").text
    assert "private_key" not in body
    assert "BEGIN PRIVATE KEY" not in body
