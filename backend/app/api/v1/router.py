"""Aggregates every v1 route module into a single router.

Authentication (SH.docx §9: "All routes require a verified Firebase ID
token") is applied here, once, at router level:

  * public      — health/readiness probes and /auth/status
  * everything else requires a verified user; individual write endpoints
    add a role requirement on top via ``require_role``.

The WebSocket authenticates itself from a ``?token=`` query parameter,
because browsers cannot set headers on a WebSocket handshake.
"""

from fastapi import APIRouter, Depends

from app.api.v1.routes import (
    auth,
    fleet,
    health,
    hubs,
    map as map_routes,
    market,
    model,
    realtime,
    shipments,
    simulation,
)
from app.core.security import get_current_user

_AUTHENTICATED = [Depends(get_current_user)]

api_router = APIRouter()

# --- public ---------------------------------------------------------------
api_router.include_router(health.router)
api_router.include_router(auth.public)

# --- authenticated --------------------------------------------------------
for protected in (
    auth.protected,
    model.router,
    simulation.router,
    shipments.router,
    fleet.router,
    hubs.router,
    hubs.emergence,
    hubs.heatmap_router,
    market.router,
    market.policy_router,
    market.metrics_router,
    map_routes.router,
):
    api_router.include_router(protected, dependencies=_AUTHENTICATED)

# --- realtime (authenticates via ?token=) --------------------------------
api_router.include_router(realtime.router)
