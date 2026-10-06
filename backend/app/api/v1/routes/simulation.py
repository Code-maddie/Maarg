"""Simulation control routes — SH.docx §9 "Simulation control (prototype-only)".

These are demo controls, not production endpoints. Mutations require the
DISPATCHER role (admins always pass); rebuilding the world requires ADMIN.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_role
from app.models.enums import UserRole
from app.engines.e4_temperature.cascade import CascadeEngine
from app.engines.e4_temperature.engine import TemperatureEngine
from app.engines.e4_temperature.pressure import apply_pressure
from app.engines.e6_piggy_router.router import route_shipment
from app.models import Shipment
from app.services.orchestrator import RecoveryOrchestrator
from app.schemas.simulation import (
    DisruptionRequest,
    DisruptionResponse,
    RoutePreviewResponse,
    SimulationStateResponse,
    TickRequest,
    TickResponse,
    WorldResetRequest,
    WorldResetResponse,
)
from app.workers.simulator import get_simulator
from app.workers.world import WorldSpec

router = APIRouter(prefix="/simulate", tags=["simulation"])

# Demo controls. Admins and dispatchers drive the live demo (SH.docx §15);
# rebuilding the whole world is admin-only.
_DISPATCH = [Depends(require_role(UserRole.DISPATCHER))]
_ADMIN = [Depends(require_role(UserRole.ADMIN))]


@router.get("/state", response_model=SimulationStateResponse, summary="World state")
def simulation_state(db: Session = Depends(get_db)) -> SimulationStateResponse:
    """Current tick, simulated time and counts by status."""
    return SimulationStateResponse(**get_simulator().state(db))


@router.post(
    "/reset", response_model=WorldResetResponse, summary="Rebuild world",
    dependencies=_ADMIN,
)
def reset_world(
    payload: WorldResetRequest, db: Session = Depends(get_db)
) -> WorldResetResponse:
    """Destroys and regenerates the world from a fixed seed.

    Users, policy modes and model artifacts survive — they are configuration,
    not simulation output.
    """
    spec = WorldSpec(
        seed=payload.seed,
        hub_count=payload.hub_count,
        vehicle_count=payload.vehicle_count,
        shipment_count=payload.shipment_count,
        leg_count=payload.leg_count,
    )
    return WorldResetResponse(**get_simulator().reset(db, spec))


@router.post(
    "/tick", response_model=TickResponse, summary="Advance the clock",
    dependencies=_DISPATCH,
)
def simulate_tick(
    payload: TickRequest | None = None, db: Session = Depends(get_db)
) -> TickResponse:
    """Advances simulated time, returning what the final tick changed."""
    simulator = get_simulator()
    ticks = payload.ticks if payload else 1

    result = None
    for _ in range(ticks):
        result = simulator.tick(db)

    assert result is not None  # ticks >= 1 is enforced by the schema
    return TickResponse(**result.as_dict())


@router.get(
    "/route/{shipment_id}",
    response_model=RoutePreviewResponse,
    summary="Preview E6 recovery plans",
    dependencies=_DISPATCH,
)
def preview_route(
    shipment_id: int, k: int = 5, db: Session = Depends(get_db)
) -> RoutePreviewResponse:
    """Runs E4, Pressure and E6 for one shipment without committing anything.

    A read-only inspection hook for operators and demos. The committing
    equivalent is POST /shipments/{id}/recovery-plan.
    """
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment {shipment_id} not found",
        )

    simulator = get_simulator()
    now = simulator.clock.now

    temperature = TemperatureEngine.from_db(db).apply(shipment)
    pressure = apply_pressure(shipment)
    db.commit()

    result = route_shipment(db, shipment, now=now, k=k)

    return RoutePreviewResponse(
        shipment_id=shipment.id,
        shipment_code=shipment.code,
        temperature=temperature.as_dict(),
        pressure=pressure.as_dict(),
        compute_ms=result.compute_ms,
        labels_explored=result.labels_explored,
        edges_considered=result.edges_considered,
        plans=[
            {
                "strategy": plan.strategy,
                "total_cost": plan.total_cost,
                "transfers": plan.transfers,
                "score": plan.score,
                "arrival_at": plan.arrival_at.isoformat() if plan.arrival_at else None,
                "legs": [
                    {
                        "leg_id": leg.leg_id,
                        "from_hub_id": leg.from_hub_id,
                        "to_hub_id": leg.to_hub_id,
                        "departure_at": leg.departure_at.isoformat(),
                        "arrival_at": leg.arrival_at.isoformat(),
                        "edge_cost": leg.edge_cost,
                        "is_dedicated": leg.is_dedicated,
                    }
                    for leg in plan.legs
                ],
            }
            for plan in result.plans
        ],
        rejected=[
            {
                "strategy": plan.strategy,
                "total_cost": plan.total_cost,
                "transfers": plan.transfers,
                "reason": plan.rejection_reason,
            }
            for plan in result.rejected
        ],
    )


@router.post(
    "/recover/{shipment_id}", summary="Run the full recovery pipeline",
    dependencies=_DISPATCH,
)
def run_recovery(
    shipment_id: int, k: int = 5, db: Session = Depends(get_db)
) -> dict:
    """Executes E1 → Pressure → E4 → Cascade → E2 → E5 → E6 → E7 → plan → E8.

    Drives the whole pipeline for one shipment in a single call, for demos
    and manual inspection. The per-resource routes do the same work
    incrementally.
    """
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment {shipment_id} not found",
        )

    now = get_simulator().clock.now
    return RecoveryOrchestrator(db).recover(shipment, now=now, k=k).as_dict()


@router.post(
    "/cascade/{origin_type}/{origin_id}",
    summary="Propagate a recovery cascade",
    dependencies=_DISPATCH,
)
def run_cascade(
    origin_type: str, origin_id: int, max_depth: int = 4,
    db: Session = Depends(get_db),
) -> dict:
    """Walks the dependency graph from a disruption and applies its effects.

    Prototype-only, like the other `/simulate` controls.
    """
    if origin_type not in {"vehicle", "shipment", "hub"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="origin_type must be vehicle, shipment or hub",
        )

    now = get_simulator().clock.now
    engine = CascadeEngine(db, max_depth=max_depth)
    result = engine.propagate(
        origin_type=origin_type, origin_id=origin_id, now=now
    )
    touched = engine.apply(result, now=now)

    payload = result.as_dict()
    payload["shipments_updated"] = len(touched)
    return payload


@router.post(
    "/inject-disruption",
    response_model=DisruptionResponse,
    summary="Inject a disruption",
    dependencies=_DISPATCH,
)
def inject_disruption(
    payload: DisruptionRequest, db: Session = Depends(get_db)
) -> DisruptionResponse:
    """Triggers the recovery scenario used throughout the demo."""
    try:
        result = get_simulator().inject_disruption(
            db,
            payload.type,
            payload.target_id,
            delay_hours=payload.delay_hours,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return DisruptionResponse(**result.as_dict())
