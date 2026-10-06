"""Health and readiness routes."""

import time

from fastapi import APIRouter

from app.core.config import settings
from app.core.database import check_database
from app.engines.e1_misplacement.registry import get_registry
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])

_STARTED_AT = time.monotonic()


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Reports that the process is up. Never touches downstream services."""
    return HealthResponse(
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        uptime_seconds=round(time.monotonic() - _STARTED_AT, 3),
    )


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
def ready() -> ReadinessResponse:
    """Reports whether downstream dependencies are usable.

    Defined with ``def`` rather than ``async def`` so the blocking database
    check runs in FastAPI's threadpool instead of stalling the event loop.
    """
    checks: dict[str, str] = {
        "database": "ok" if check_database() else "unavailable",
        "e1_model": str(get_registry().status().state),
    }
    # The E1 model is reported but is deliberately NOT a readiness gate: the
    # backend must keep serving while the artifact loads, and must stay up if
    # it fails to load entirely.
    status = "degraded" if checks["database"] != "ok" else "ready"
    return ReadinessResponse(status=status, checks=checks)
