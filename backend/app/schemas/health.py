"""Response models for the health endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness payload — the process is up and serving requests."""

    status: Literal["ok"] = "ok"
    app: str = Field(..., description="Application name.")
    version: str = Field(..., description="Application version.")
    environment: str = Field(..., description="Deployment environment.")
    uptime_seconds: float = Field(..., ge=0, description="Seconds since startup.")


class ReadinessResponse(BaseModel):
    """Readiness payload — the process can serve dependent traffic.

    ``degraded`` means a dependency the service cannot work without is
    unavailable. The E1 model is reported in ``checks`` but does not gate
    readiness: the service stays useful while the artifact loads, and if it
    fails to load at all.
    """

    status: Literal["ready", "degraded"] = "ready"
    checks: dict[str, str] = Field(
        default_factory=dict,
        description="Dependency name -> status, e.g. {'database': 'ok'}.",
    )
