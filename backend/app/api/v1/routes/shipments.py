"""Shipment routes — SH.docx §9 "Shipments"."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import CurrentUser, require_role
from app.engines.e8_explainer.explainer import MISSING_REASON
from app.models import AuditLog, Hub, RecoveryPlan, Shipment
from app.models.enums import AuditAction, PlanStatus, PlanStrategy, UserRole
from app.schemas.api import (
    ExplainerResponse,
    OverrideRequest,
    OverrideResponse,
    RecoveryPlanBundle,
    ShipmentDetail,
    ShipmentList,
)
from app.services.presentation import (
    hub_code_map,
    hub_name_map,
    plan_out,
    shipment_detail,
    shipment_summary,
)
from app.workers.simulator import get_simulator

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.get("", response_model=ShipmentList, summary="List shipments")
def list_shipments(
    db: Session = Depends(get_db),
    status_filter: Optional[str] = Query(
        default=None, alias="status", description="Exact shipment status."
    ),
    min_temperature: Optional[float] = Query(default=None, ge=0, le=100),
    max_temperature: Optional[float] = Query(default=None, ge=0, le=100),
    emergency_only: bool = False,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> ShipmentList:
    """Filterable list, hottest first — the dispatcher queue (SH.docx §5.2)."""
    query = select(Shipment)
    count_query = select(func.count()).select_from(Shipment)

    if status_filter:
        # Comma-separated, e.g. "MISPLACED,RECOVERING" for the dispatcher
        # queue. A single value behaves exactly as before.
        wanted = [part.strip() for part in status_filter.split(",") if part.strip()]
        query = query.where(Shipment.status.in_(wanted))
        count_query = count_query.where(Shipment.status.in_(wanted))
    if min_temperature is not None:
        query = query.where(Shipment.temperature >= min_temperature)
        count_query = count_query.where(Shipment.temperature >= min_temperature)
    if max_temperature is not None:
        query = query.where(Shipment.temperature <= max_temperature)
        count_query = count_query.where(Shipment.temperature <= max_temperature)
    if emergency_only:
        from app.engines.e4_temperature.pressure import EMERGENCY_THRESHOLD

        query = query.where(Shipment.pressure >= EMERGENCY_THRESHOLD)
        count_query = count_query.where(Shipment.pressure >= EMERGENCY_THRESHOLD)

    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.order_by(Shipment.temperature.desc(), Shipment.id)
        .offset(offset)
        .limit(limit)
    ).all()

    codes = hub_code_map(db)
    return ShipmentList(
        total=total, items=[shipment_summary(row, codes) for row in rows]
    )


def _get_shipment(db: Session, shipment_id: int) -> Shipment:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment {shipment_id} not found",
        )
    return shipment


@router.get("/{shipment_id}", response_model=ShipmentDetail, summary="Shipment detail")
def get_shipment(shipment_id: int, db: Session = Depends(get_db)) -> ShipmentDetail:
    shipment = _get_shipment(db, shipment_id)
    return shipment_detail(shipment, hub_code_map(db), get_simulator().clock.now)


@router.get(
    "/{shipment_id}/recovery-plan",
    response_model=RecoveryPlanBundle,
    summary="Committed plan and alternatives",
)
def get_recovery_plan(
    shipment_id: int, db: Session = Depends(get_db)
) -> RecoveryPlanBundle:
    """The plan panel: what was committed, what else was available."""
    shipment = _get_shipment(db, shipment_id)
    codes = hub_code_map(db)

    plans = db.scalars(
        select(RecoveryPlan)
        .where(RecoveryPlan.shipment_id == shipment.id)
        .order_by(RecoveryPlan.rank, RecoveryPlan.id)
    ).all()

    committed = next(
        (p for p in plans if p.status == PlanStatus.COMMITTED.value), None
    )

    return RecoveryPlanBundle(
        shipment_id=shipment.id,
        shipment_code=shipment.code,
        committed=plan_out(committed, codes) if committed else None,
        alternatives=[
            plan_out(p, codes)
            for p in plans
            if p.status == PlanStatus.PROPOSED.value
        ],
        rejected=[
            plan_out(p, codes)
            for p in plans
            if p.status == PlanStatus.REJECTED.value
        ],
    )


@router.get(
    "/{shipment_id}/explainer",
    response_model=ExplainerResponse,
    summary="Counterfactual explanation",
)
def get_explainer(
    shipment_id: int, db: Session = Depends(get_db)
) -> ExplainerResponse:
    """Rebuilds the E8 card from persisted plans.

    Reconstructed from the database rather than cached, so the explanation
    survives a restart and always matches what is actually committed.
    """
    shipment = _get_shipment(db, shipment_id)
    names = hub_name_map(db)

    plans = db.scalars(
        select(RecoveryPlan).where(RecoveryPlan.shipment_id == shipment.id)
    ).all()

    committed = next(
        (p for p in plans if p.status == PlanStatus.COMMITTED.value), None
    )
    if committed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment {shipment.code} has no committed recovery plan",
        )

    dedicated = [
        p for p in plans if p.strategy == PlanStrategy.DEDICATED.value
        and p.id != committed.id
    ]

    why: list[str] = []
    if committed.strategy == PlanStrategy.PIGGYBACK.value:
        why.append(
            "Rides capacity already scheduled on this corridor, so no "
            "additional vehicle was dispatched."
        )
    elif committed.strategy == PlanStrategy.DEDICATED.value:
        why.append(
            "No existing capacity could meet the deadline, so a dedicated "
            "vehicle was required."
        )

    if dedicated:
        saving = dedicated[0].total_cost - committed.total_cost
        if saving > 0:
            pct = 100.0 * saving / dedicated[0].total_cost
            why.append(
                f"Costs {committed.total_cost:.2f} against "
                f"{dedicated[0].total_cost:.2f} for dedicated recovery, a "
                f"saving of {saving:.2f} ({pct:.1f}%)."
            )

    slack = None
    if committed.eta and shipment.deadline_at:
        slack = round(
            (shipment.deadline_at - committed.eta).total_seconds() / 3600.0, 2
        )
        if slack >= 0:
            why.append(
                f"Arrives {committed.eta.isoformat(timespec='minutes')}, "
                f"{slack:.1f} hours inside the deadline."
            )
        else:
            why.append(
                f"Arrives {committed.eta.isoformat(timespec='minutes')}, "
                f"{abs(slack):.1f} hours past the deadline — this was the "
                "best available option."
            )

    why.append(
        f"Priced at lambda = {shipment.lam:.2f}/hour from a temperature of "
        f"{shipment.temperature:.1f}."
    )

    transfers = max(0, len(committed.paths) - 1)

    alternatives = []
    for plan in plans:
        if plan.id == committed.id:
            continue
        if plan.status == PlanStatus.REJECTED.value:
            reason = plan.rejection_reason or MISSING_REASON
        else:
            delta = plan.total_cost - committed.total_cost
            reason = (
                f"Feasible but {delta:.2f} more expensive than the selected "
                f"plan ({plan.total_cost:.2f} vs {committed.total_cost:.2f})"
                if delta > 0
                else f"Scored {plan.score:.3f} against the selected plan's "
                     f"{committed.score:.3f}"
            )
        alternatives.append(
            {
                "plan_id": plan.id,
                "strategy": plan.strategy,
                "total_cost": plan.total_cost,
                "transfers": max(0, len(plan.paths) - 1),
                "arrival_at": plan.eta.isoformat() if plan.eta else None,
                "reason": reason,
                "cost_delta": round(plan.total_cost - committed.total_cost, 2),
            }
        )

    return ExplainerResponse(
        shipment_id=shipment.id,
        shipment_code=shipment.code,
        headline=(
            f"{shipment.code}: {committed.strategy} recovery at "
            f"{committed.total_cost:.2f}"
        ),
        strategy=committed.strategy,
        total_cost=committed.total_cost,
        arrival_at=committed.eta.isoformat() if committed.eta else None,
        deadline_at=(
            shipment.deadline_at.isoformat() if shipment.deadline_at else None
        ),
        transfers=transfers,
        slack_hours=slack,
        why_chosen=why,
        route=[
            {
                "leg_id": step.leg_id,
                "from_hub": names.get(step.from_hub_id, str(step.from_hub_id)),
                "to_hub": names.get(step.to_hub_id, str(step.to_hub_id)),
                "departure_at": (
                    step.departure_at.isoformat() if step.departure_at else None
                ),
                "arrival_at": (
                    step.arrival_at.isoformat() if step.arrival_at else None
                ),
                "cost": step.edge_cost,
                "is_dedicated": step.leg_id is None,
            }
            for step in committed.paths
        ],
        alternatives=alternatives,
        urgency={
            "temperature": shipment.temperature,
            "lambda_per_hour": shipment.lam,
            "pressure": shipment.pressure,
            "cascade_depth": shipment.cascade_depth,
        },
    )


@router.post(
    "/{shipment_id}/override",
    response_model=OverrideResponse,
    summary="Override the engine's plan",
)
def override_plan(
    shipment_id: int,
    payload: OverrideRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.DISPATCHER)),
) -> OverrideResponse:
    """Dispatcher picks a different plan. Always audited (SH.docx §12)."""
    shipment = _get_shipment(db, shipment_id)

    chosen = db.get(RecoveryPlan, payload.chosen_plan_id)
    if chosen is None or chosen.shipment_id != shipment.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Plan {payload.chosen_plan_id} does not belong to "
                f"shipment {shipment.code}"
            ),
        )

    if chosen.status == PlanStatus.REJECTED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot commit a rejected plan: "
                f"{chosen.rejection_reason or 'no reason recorded'}"
            ),
        )

    previous = next(
        (
            p
            for p in db.scalars(
                select(RecoveryPlan).where(
                    RecoveryPlan.shipment_id == shipment.id,
                    RecoveryPlan.status == PlanStatus.COMMITTED.value,
                )
            ).all()
        ),
        None,
    )

    previous_id = None
    if previous is not None and previous.id != chosen.id:
        previous_id = previous.id
        previous.status = PlanStatus.OVERRIDDEN.value
        previous.rejection_reason = (
            f"Overridden by dispatcher: {payload.reason}"
        )

    chosen.status = PlanStatus.COMMITTED.value

    # Move the physical booking to the chosen plan (releases the old one).
    from app.services.booking import book_plan

    failed = book_plan(db, shipment, chosen)
    if failed:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Plan {chosen.id} is no longer bookable: legs {failed} are gone, departed or full",
        )

    entry = AuditLog(
        actor_user_id=user.db_user_id,
        action=AuditAction.OVERRIDE_PLAN.value,
        target_type="RecoveryPlan",
        target_id=chosen.id,
        reason_text=payload.reason,
    )
    db.add(entry)
    db.commit()

    # Every open dashboard must converge on the new commitment.
    from app.services.events import EventType, publish

    publish(EventType.PLAN_CHANGED, {
        "shipment_id": shipment.id, "shipment_code": shipment.code,
        "plan_id": chosen.id, "strategy": chosen.strategy,
        "total_cost": chosen.total_cost, "override": True,
    })

    return OverrideResponse(
        shipment_id=shipment.id,
        previous_plan_id=previous_id,
        chosen_plan_id=chosen.id,
        audit_log_id=entry.id,
    )
