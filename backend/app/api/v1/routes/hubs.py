"""Hub, Hub-Emergence and heatmap routes — SH.docx §9 and §7."""

from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import CurrentUser, require_role
from app.engines.e3_hub_emergence.engine import (
    approve_candidate,
    generate_candidates,
    reject_candidate,
)
from app.models import Hub, HubCandidate, Leg, Shipment, ShipmentLeg
from app.models.enums import CandidateStatus, UserRole
from app.schemas.api import (
    CandidateDecision,
    HeatmapResponse,
    HubCandidateOut,
    HubCreate,
    HubOut,
    RiskCell,
)
from app.workers.simulator import get_simulator

router = APIRouter(tags=["hubs"])


@router.get("/hubs", response_model=List[HubOut], summary="List hubs")
def list_hubs(
    db: Session = Depends(get_db), active_only: bool = False
) -> List[HubOut]:
    query = select(Hub)
    if active_only:
        query = query.where(Hub.is_active.is_(True))
    return [
        HubOut.model_validate(hub)
        for hub in db.scalars(query.order_by(Hub.code)).all()
    ]


@router.post(
    "/hubs",
    response_model=HubOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a hub",
)
def create_hub(
    payload: HubCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
) -> HubOut:
    """Admin-only per SH.docx §9."""
    existing = db.scalar(select(Hub).where(Hub.code == payload.code))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Hub code {payload.code} already exists",
        )

    hub = Hub(
        code=payload.code,
        name=payload.name,
        lat=payload.lat,
        lng=payload.lng,
        capacity_kg=payload.capacity_kg,
        is_active=True,
    )
    db.add(hub)
    db.commit()
    return HubOut.model_validate(hub)


# --- Hub Emergence -------------------------------------------------------

emergence = APIRouter(prefix="/hub-emergence", tags=["hub-emergence"])


@emergence.get(
    "/candidates",
    response_model=List[HubCandidateOut],
    summary="Ranked hub candidates",
)
def list_candidates(
    db: Session = Depends(get_db),
    candidate_status: Optional[str] = Query(default=None, alias="status"),
    regenerate: bool = Query(
        default=False, description="Recompute from current traffic first."
    ),
) -> List[HubCandidateOut]:
    if regenerate:
        generate_candidates(db, now=get_simulator().clock.now, min_usage=1)

    query = select(HubCandidate)
    if candidate_status:
        query = query.where(HubCandidate.status == candidate_status)

    return [
        HubCandidateOut.model_validate(row)
        for row in db.scalars(
            query.order_by(HubCandidate.hub_score.desc())
        ).all()
    ]


def _get_candidate(db: Session, candidate_id: int) -> HubCandidate:
    candidate = db.get(HubCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hub candidate {candidate_id} not found",
        )
    return candidate


@emergence.post(
    "/candidates/{candidate_id}/approve",
    response_model=HubOut,
    summary="Approve a candidate",
)
def approve(
    candidate_id: int,
    payload: CandidateDecision,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
) -> HubOut:
    """Creates a real hub and writes an audit entry. Admin only."""
    candidate = _get_candidate(db, candidate_id)
    try:
        hub = approve_candidate(
            db, candidate, code=payload.code, name=payload.name,
            reason=payload.reason, actor_user_id=user.db_user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    return HubOut.model_validate(hub)


@emergence.post(
    "/candidates/{candidate_id}/reject",
    response_model=HubCandidateOut,
    summary="Reject a candidate",
)
def reject(
    candidate_id: int,
    payload: CandidateDecision,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
) -> HubCandidateOut:
    candidate = _get_candidate(db, candidate_id)
    reject_candidate(
        db, candidate, reason=payload.reason, actor_user_id=user.db_user_id
    )
    return HubCandidateOut.model_validate(candidate)


# --- heatmap -------------------------------------------------------------

heatmap_router = APIRouter(tags=["heatmap"])


@heatmap_router.get(
    "/heatmap", response_model=HeatmapResponse, summary="Risk heatmap cells"
)
def get_heatmap(
    hour: int = Query(default=-1, ge=-1, le=23, description="-1 uses sim time."),
    db: Session = Depends(get_db),
) -> HeatmapResponse:
    """P(misplace) aggregated by hub for a given hour (SH.docx §7).

    Cells are keyed on hub coordinates, which is what
    `visualization.HeatmapLayer` consumes directly.
    """
    simulator = get_simulator()
    resolved_hour = simulator.clock.now.hour if hour < 0 else hour

    hubs = {hub.id: hub for hub in db.scalars(select(Hub)).all()}
    legs = {leg.id: leg for leg in db.scalars(select(Leg)).all()}
    shipments = {s.id: s for s in db.scalars(select(Shipment)).all()}

    totals: dict[int, list[float]] = defaultdict(list)

    for link in db.scalars(select(ShipmentLeg)).all():
        leg = legs.get(link.leg_id)
        if leg is None or leg.departure_at.hour != resolved_hour:
            continue

        shipment = shipments.get(link.shipment_id)
        if shipment is None or shipment.p_misplace is None:
            continue

        totals[leg.to_hub_id].append(shipment.p_misplace)

    # Fall back to scored shipments resting at each hub, so the map is not
    # blank before any leg has departed in this hour.
    if not totals:
        for shipment in shipments.values():
            if shipment.p_misplace is None or shipment.current_hub_id is None:
                continue
            totals[shipment.current_hub_id].append(shipment.p_misplace)
        source = "resting shipments (no departures in this hour)"
    else:
        source = "shipment-legs departing in this hour"

    cells: List[RiskCell] = []
    for hub_id, values in totals.items():
        hub = hubs.get(hub_id)
        if hub is None or not values:
            continue
        cells.append(
            RiskCell(
                lat=hub.lat,
                lng=hub.lng,
                weight=round(min(1.0, max(0.0, sum(values) / len(values))), 4),
                hub_code=hub.code,
                sample_count=len(values),
            )
        )

    cells.sort(key=lambda cell: cell.weight, reverse=True)
    return HeatmapResponse(hour=resolved_hour, cells=cells, source=source)
