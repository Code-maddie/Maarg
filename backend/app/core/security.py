"""Authentication and authorisation — SH.docx §3 and §12.

Firebase Auth issues ID tokens; this module verifies them server-side on
every request and reads the role from a custom claim. The client's stated
role is never trusted.

Two modes (``AUTH_MODE``):

  * ``firebase``  — every protected route requires ``Authorization: Bearer
                    <Firebase ID token>``. The default.
  * ``disabled``  — local development bypass. Every request is treated as a
                    dev admin and a warning is logged. Refused outright in
                    production (see ``Settings``).

Admins pass every role check. That makes admin the superuser SH.docx §3
describes ("configure hubs/vehicles, set global policy, see full analytics").
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models import User
from app.models.enums import UserRole

logger = get_logger(__name__)

_init_lock = threading.Lock()
_firebase_app: Any = None
_init_error: Optional[str] = None

DEV_UID = "dev-bypass"
DEV_EMAIL = "dev@localhost"


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller."""

    uid: str
    email: Optional[str]
    role: str
    db_user_id: Optional[int] = None
    is_dev_bypass: bool = False

    def has_role(self, *roles: str) -> bool:
        return self.role == UserRole.ADMIN.value or self.role in roles


# --- Firebase Admin SDK ---------------------------------------------------

def _load_certificate(credentials: Any) -> Any:
    """Builds the Admin SDK certificate from the environment or from disk.

    ``FIREBASE_CREDENTIALS_JSON`` wins when set, because production hosts
    have no durable place to keep a secret file. Falls back to the file path
    for local development. Records the reason and returns ``None`` when
    neither is usable — the key material itself is never logged.
    """
    global _init_error

    raw = settings.firebase_credentials_json.strip()
    if raw:
        try:
            return credentials.Certificate(json.loads(raw))
        except json.JSONDecodeError as exc:
            _init_error = f"FIREBASE_CREDENTIALS_JSON is not valid JSON: {exc.msg}"
            logger.error(_init_error)
            return None
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            _init_error = f"FIREBASE_CREDENTIALS_JSON rejected: {type(exc).__name__}"
            logger.error(_init_error)
            return None

    path = settings.firebase_credentials_file
    if not path.exists():
        _init_error = (
            "No Firebase credentials: set FIREBASE_CREDENTIALS_JSON, or place "
            f"the service account at {path.name}"
        )
        logger.warning(_init_error)
        return None

    return credentials.Certificate(str(path))


def init_firebase() -> bool:
    """Initialises the Admin SDK once. Returns True when it is usable.

    Failure is recorded rather than raised: a missing credential file must
    not stop the backend starting. It only means token verification will
    reject every request with a clear error.
    """
    global _firebase_app, _init_error

    with _init_lock:
        if _firebase_app is not None:
            return True

        try:
            import firebase_admin
            from firebase_admin import credentials

            certificate = _load_certificate(credentials)
            if certificate is None:
                return False

            # Reuse an app another module already initialised.
            try:
                _firebase_app = firebase_admin.get_app()
            except ValueError:
                _firebase_app = firebase_admin.initialize_app(certificate)
            _init_error = None
            # Log the project, never the key.
            logger.info(
                "Firebase Admin initialised for project %s",
                _firebase_app.project_id,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            _init_error = f"{type(exc).__name__}: {exc}"
            logger.error("Firebase Admin initialisation failed: %s", _init_error)
            return False


def firebase_status() -> Dict[str, Any]:
    """Safe-to-expose initialisation state."""
    return {
        "auth_mode": settings.auth_mode,
        "initialised": _firebase_app is not None,
        "project_id": getattr(_firebase_app, "project_id", None),
        "firestore_enabled": settings.firestore_enabled,
        "error": _init_error,
    }


def _verify_id_token(token: str) -> Dict[str, Any]:
    """Verifies a Firebase ID token. Isolated so tests can substitute it."""
    from firebase_admin import auth

    return auth.verify_id_token(token, app=_firebase_app)


def _normalise_role(raw: Any) -> str:
    """Maps a custom-claim role onto UserRole, defaulting to least privilege.

    A token with no role claim, or an unrecognised one, is treated as a
    CUSTOMER — never escalated.
    """
    if isinstance(raw, str):
        candidate = raw.strip().upper()
        if candidate in {role.value for role in UserRole}:
            return candidate
    return UserRole.CUSTOMER.value


def verify_token(token: str) -> Dict[str, Any]:
    """Verifies a token, raising 401 with a precise reason on failure."""
    if not init_firebase():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Authentication unavailable: {_init_error}",
        )

    try:
        return _verify_id_token(token)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - every failure is a 401
        name = type(exc).__name__
        if "Expired" in name:
            reason = "token has expired"
        elif "Revoked" in name:
            reason = "token has been revoked"
        else:
            reason = "token is invalid"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {reason}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _extract_bearer(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


# --- user record ----------------------------------------------------------

def _sync_user(db: Session, uid: str, email: Optional[str], role: str) -> Optional[int]:
    """Upserts the User row so audit entries can name a real actor.

    The Firebase claim stays the source of truth for the role; this row
    only mirrors it for listing and auditing.
    """
    user = db.scalar(select(User).where(User.firebase_uid == uid))

    if user is None and email:
        user = db.scalar(select(User).where(User.email == email))

    if user is None:
        user = User(
            firebase_uid=uid,
            email=email or f"{uid}@firebase.local",
            role=role,
        )
        db.add(user)
    else:
        user.firebase_uid = uid
        user.role = role
        if email:
            user.email = email

    try:
        db.commit()
    except Exception:  # noqa: BLE001 - identity must not fail the request
        db.rollback()
        logger.exception("Could not sync user record for %s", uid)
        return None

    return user.id


# --- dependencies ---------------------------------------------------------

def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """FastAPI dependency: the verified caller, or 401."""
    if not settings.auth_enabled:
        logger.debug("AUTH_MODE=disabled: request treated as dev admin")
        return CurrentUser(
            uid=DEV_UID,
            email=DEV_EMAIL,
            role=UserRole.ADMIN.value,
            db_user_id=_sync_user(db, DEV_UID, DEV_EMAIL, UserRole.ADMIN.value),
            is_dev_bypass=True,
        )

    claims = verify_token(_extract_bearer(authorization))

    uid = claims.get("uid") or claims.get("user_id") or claims.get("sub")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: token carries no user id",
        )

    email = claims.get("email")
    role = _normalise_role(claims.get("role"))

    return CurrentUser(
        uid=uid,
        email=email,
        role=role,
        db_user_id=_sync_user(db, uid, email, role),
    )


def require_role(*roles: UserRole | str) -> Callable[..., CurrentUser]:
    """Dependency factory gating a route to specific roles (admin always passes).

    Usage::

        @router.put("/policy-mode")
        def update(user: CurrentUser = Depends(require_role(UserRole.ADMIN))): ...
    """
    allowed = tuple(str(role.value if isinstance(role, UserRole) else role).upper()
                    for role in roles)

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(*allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role {user.role} is not permitted here; requires one of: "
                    f"{', '.join(allowed)}"
                ),
            )
        return user

    return dependency


def verify_websocket_token(token: Optional[str]) -> Optional[CurrentUser]:
    """WebSocket auth: browsers cannot set headers on a WS handshake, so the
    token arrives as a query parameter. Returns None when rejected."""
    if not settings.auth_enabled:
        return CurrentUser(
            uid=DEV_UID, email=DEV_EMAIL, role=UserRole.ADMIN.value,
            is_dev_bypass=True,
        )
    if not token:
        return None
    try:
        claims = verify_token(token)
    except HTTPException:
        return None

    uid = claims.get("uid") or claims.get("user_id") or claims.get("sub")
    if not uid:
        return None
    return CurrentUser(
        uid=uid, email=claims.get("email"),
        role=_normalise_role(claims.get("role")),
    )


def set_user_role(uid: str, role: UserRole | str) -> Dict[str, Any]:
    """Sets the role custom claim on a Firebase user (SH.docx §12).

    This WRITES to the live Firebase project, so it is only reachable from
    an admin-gated endpoint or an explicit script.
    """
    normalised = _normalise_role(role.value if isinstance(role, UserRole) else role)
    if normalised == UserRole.CUSTOMER.value and str(role).upper() != "CUSTOMER":
        raise ValueError(f"Unknown role: {role}")

    if not init_firebase():
        raise RuntimeError(f"Firebase unavailable: {_init_error}")

    from firebase_admin import auth

    auth.set_custom_user_claims(uid, {"role": normalised.lower()}, app=_firebase_app)
    logger.info("Set role %s on Firebase user %s", normalised, uid)
    return {"uid": uid, "role": normalised}


def reset_firebase_state() -> None:
    """Test support only."""
    global _firebase_app, _init_error
    _firebase_app = None
    _init_error = None
