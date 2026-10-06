"""Auth routes — SH.docx §12.

`GET /auth/status` is public so the frontend can discover whether it must
send a token. `POST /users/{uid}/role` writes a custom claim to the live
Firebase project and is therefore admin-only and audited.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (
    CurrentUser,
    firebase_status,
    get_current_user,
    require_role,
    set_user_role,
)
from app.models import AuditLog
from app.models.enums import AuditAction, UserRole

public = APIRouter(prefix="/auth", tags=["auth"])
protected = APIRouter(tags=["auth"])


class MeResponse(BaseModel):
    uid: str
    email: str | None = None
    role: str
    db_user_id: int | None = None
    dev_bypass: bool = False


class RoleUpdate(BaseModel):
    role: UserRole
    reason: str = Field(default="", max_length=500)


# Public by design in Firebase: these identify the project to the browser SDK
# and REST API. They are NOT credentials. Only these keys are ever served.
_WEB_CONFIG_KEYS = {
    "VITE_FIREBASE_API_KEY": "apiKey",
    "VITE_FIREBASE_AUTH_DOMAIN": "authDomain",
    "VITE_FIREBASE_PROJECT_ID": "projectId",
    "VITE_FIREBASE_APP_ID": "appId",
}


def _read_web_config() -> dict:
    """The Firebase web config, from the environment or the local .env file.

    Environment variables are authoritative: in production there is no
    frontend/.env on the backend's filesystem. The file is only consulted to
    fill gaps, so an existing local checkout keeps working untouched.
    """
    from app.core.config import PROJECT_ROOT, settings

    config = {
        "apiKey": settings.firebase_api_key,
        "authDomain": settings.firebase_auth_domain,
        "projectId": settings.firebase_project_id,
        "appId": settings.firebase_app_id,
    }
    config = {key: value for key, value in config.items() if value}
    if len(config) == len(_WEB_CONFIG_KEYS):
        return config

    path = PROJECT_ROOT / settings.frontend_env_path
    if not path.exists():
        return config

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        field = _WEB_CONFIG_KEYS.get(key.strip())
        if field and field not in config:
            config[field] = value.strip().strip('"').strip("'")
    return config


@public.get("/web-config", summary="Firebase web config for the browser")
def web_config() -> dict:
    """The existing frontend Firebase web config (from frontend/.env).

    Lets the static site sign in with Firebase Auth using the keys already
    provided, without a build step and without duplicating them. Returns
    only the public identification fields — never service-account material.
    """
    from app.core.config import settings

    config = _read_web_config()
    return {
        "auth_mode": settings.auth_mode,
        "configured": bool(config.get("apiKey") and config.get("projectId")),
        "firebase": config,
    }


@public.get("/status", summary="Authentication mode")
def auth_status() -> dict:
    """Whether auth is enforced, and whether Firebase initialised.

    Exposes the project id (already public in the frontend's config) but
    never any credential material.
    """
    return firebase_status()


@protected.get("/auth/me", response_model=MeResponse, summary="Current user")
def me(user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        uid=user.uid,
        email=user.email,
        role=user.role,
        db_user_id=user.db_user_id,
        dev_bypass=user.is_dev_bypass,
    )


@protected.post("/users/{uid}/role", summary="Assign a role (admin)")
def assign_role(
    uid: str,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Sets the Firebase custom claim. The user must sign in again (or
    refresh their token) before the new role takes effect."""
    try:
        result = set_user_role(uid, payload.role)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001 - Firebase errors surface as 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Firebase rejected the role update: {type(exc).__name__}",
        ) from exc

    db.add(
        AuditLog(
            actor_user_id=admin.db_user_id,
            action=AuditAction.SET_USER_ROLE.value,
            target_type="FirebaseUser",
            reason_text=f"{uid} -> {result['role']}. {payload.reason}".strip(),
        )
    )
    db.commit()
    return {**result, "note": "User must refresh their ID token to pick up the role."}
