"""Auction, reservation, policy and metrics routes — SH.docx §9 and §5.1."""

import json
import statistics
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import CurrentUser, require_role
from app.engines.e2_foresight.reservation import (
    evaluate_shipment as evaluate_reservation,
)
from app.engines.e4_temperature.policy import (
    POLICY_WEIGHTS,
    get_active_weights,
    get_policy,
    set_policy,
)
from app.engines.e5_bounty.market import close_auction, place_bid
from app.engines.e9_learning.outcomes import summarise_errors
from app.models import (
    Auction,
    AuditLog,
    RecoveryOutcome,
    RecoveryPlan,
    Shipment,
)
from app.models.enums import (
    AuctionStatus,
    AuditAction,
    PlanStatus,
    PlanStrategy,
    ShipmentStatus,
    UserRole,
)
from app.schemas.api import (
    AuctionOut,
    BidRequest,
    MetricsResponse,
    PolicyModeOut,
    PolicyModeUpdate,
    ReservationOut,
)
from app.services.events import EventType, publish
from app.services.presentation import auction_out
from app.workers.simulator import get_simulator

router = APIRouter(tags=["market"])


# --- auctions ------------------------------------------------------------

@router.get("/auctions", response_model=List[AuctionOut], summary="List auctions")
def list_auctions(
    db: Session = Depends(get_db),
    auction_status: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
) -> List[AuctionOut]:
    query = select(Auction)
    if auction_status:
        query = query.where(Auction.status == auction_status)

    rows = db.scalars(query.order_by(Auction.id.desc()).limit(limit)).all()
    return [auction_out(db, row) for row in rows]


def _get_auction(db: Session, auction_id: int) -> Auction:
    auction = db.get(Auction, auction_id)
    if auction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Auction {auction_id} not found",
        )
    return auction


@router.get(
    "/auctions/{auction_id}", response_model=AuctionOut, summary="Auction detail"
)
def get_auction(auction_id: int, db: Session = Depends(get_db)) -> AuctionOut:
    return auction_out(db, _get_auction(db, auction_id))


@router.post(
    "/auctions/{auction_id}/bid",
    response_model=AuctionOut,
    summary="Place a bid",
)
def submit_bid(
    auction_id: int,
    payload: BidRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.DRIVER)),
) -> AuctionOut:
    """Driver-side bid (SH.docx §9). Drivers only."""
    auction = _get_auction(db, auction_id)
    try:
        place_bid(
            db,
            auction,
            vehicle_id=payload.vehicle_id,
            amount=payload.amount,
            detour_km=payload.detour_km,
            now=get_simulator().clock.now,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    db.refresh(auction)
    return auction_out(db, auction)


@router.post(
    "/auctions/{auction_id}/close",
    response_model=AuctionOut,
    summary="Close and settle an auction",
)
def settle_auction(
    auction_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.DISPATCHER)),
) -> AuctionOut:
    """Settles under Vickrey rules: lowest bidder, second price."""
    auction = _get_auction(db, auction_id)
    if auction.status != AuctionStatus.OPEN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Auction {auction_id} is already {auction.status}",
        )

    close_auction(db, auction, now=get_simulator().clock.now)
    db.refresh(auction)
    return auction_out(db, auction)


# --- reservations --------------------------------------------------------

@router.get(
    "/reservations",
    response_model=List[ReservationOut],
    summary="Foresight option evaluations",
)
def list_reservations(
    db: Session = Depends(get_db),
    reserved_only: bool = True,
    limit: int = Query(default=50, ge=1, le=500),
) -> List[ReservationOut]:
    """Evaluates the critical-fractile rule across scored shipments.

    Computed on demand rather than stored: there is no Reservation table yet
    and the decision depends on current costs.
    """
    shipments = db.scalars(
        select(Shipment)
        .where(Shipment.p_misplace.is_not(None))
        .order_by(Shipment.p_misplace.desc())
        .limit(limit * 4)
    ).all()

    results: List[ReservationOut] = []
    for shipment in shipments:
        plans = db.scalars(
            select(RecoveryPlan).where(RecoveryPlan.shipment_id == shipment.id)
        ).all()

        dedicated = next(
            (p.total_cost for p in plans
             if p.strategy == PlanStrategy.DEDICATED.value),
            None,
        )
        committed = next(
            (p.total_cost for p in plans
             if p.status == PlanStatus.COMMITTED.value),
            None,
        )

        # Without real plans, fall back to a transparent estimate so the
        # panel is not empty before any recovery has run.
        dedicated_cost = dedicated or shipment.sla_penalty_per_hour * 200
        expected_bounty = committed or dedicated_cost * 0.45

        decision = evaluate_reservation(
            shipment,
            dedicated_cost=dedicated_cost,
            expected_bounty=expected_bounty,
        )

        if reserved_only and not decision.should_reserve:
            continue

        results.append(
            ReservationOut(
                shipment_id=shipment.id,
                shipment_code=shipment.code,
                should_reserve=decision.should_reserve,
                p_misplace=decision.p_misplace,
                threshold=decision.threshold,
                premium=decision.premium,
                dedicated_cost=decision.dedicated_cost,
                expected_bounty=decision.expected_bounty,
                expected_saving=decision.expected_saving,
                reason=decision.reason,
            )
        )
        if len(results) >= limit:
            break

    return results


@router.get(
    "/reservations/{shipment_id}",
    response_model=ReservationOut,
    summary="Foresight evaluation for one shipment",
)
def get_reservation(
    shipment_id: int, db: Session = Depends(get_db)
) -> ReservationOut:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment {shipment_id} not found",
        )

    plans = db.scalars(
        select(RecoveryPlan).where(RecoveryPlan.shipment_id == shipment.id)
    ).all()
    dedicated = next(
        (p.total_cost for p in plans
         if p.strategy == PlanStrategy.DEDICATED.value),
        shipment.sla_penalty_per_hour * 200,
    )
    committed = next(
        (p.total_cost for p in plans if p.status == PlanStatus.COMMITTED.value),
        dedicated * 0.45,
    )

    decision = evaluate_reservation(
        shipment, dedicated_cost=dedicated, expected_bounty=committed
    )
    return ReservationOut(
        shipment_id=shipment.id,
        shipment_code=shipment.code,
        should_reserve=decision.should_reserve,
        p_misplace=decision.p_misplace,
        threshold=decision.threshold,
        premium=decision.premium,
        dedicated_cost=decision.dedicated_cost,
        expected_bounty=decision.expected_bounty,
        expected_saving=decision.expected_saving,
        reason=decision.reason,
    )


# --- policy --------------------------------------------------------------

policy_router = APIRouter(tags=["policy"])


@policy_router.get(
    "/policy-mode", response_model=PolicyModeOut, summary="Active policy mode"
)
def read_policy(db: Session = Depends(get_db)) -> PolicyModeOut:
    policy = get_policy(db)
    return PolicyModeOut(
        mode=policy.mode,
        weights=get_active_weights(db).as_dict(),
        updated_at=policy.updated_at,
        available_modes=sorted(POLICY_WEIGHTS),
    )


@policy_router.put(
    "/policy-mode", response_model=PolicyModeOut, summary="Change policy mode"
)
def update_policy(
    payload: PolicyModeUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
) -> PolicyModeOut:
    """The admin dial (SH.docx §5.1). Admin only, audited."""
    try:
        policy = set_policy(
            db, payload.mode, weights=payload.weights,
            updated_by=user.db_user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    db.add(
        AuditLog(
            actor_user_id=user.db_user_id,
            action=AuditAction.CHANGE_POLICY_MODE.value,
            target_type="PolicyMode",
            target_id=policy.id,
            reason_text=payload.reason or f"Policy mode set to {payload.mode}",
        )
    )
    db.commit()

    publish(
        EventType.POLICY_CHANGED,
        {"mode": policy.mode, "weights": get_active_weights(db).as_dict()},
    )

    return PolicyModeOut(
        mode=policy.mode,
        weights=get_active_weights(db).as_dict(),
        updated_at=policy.updated_at,
        available_modes=sorted(POLICY_WEIGHTS),
    )


# --- metrics -------------------------------------------------------------

metrics_router = APIRouter(tags=["metrics"])


@metrics_router.get(
    "/metrics", response_model=MetricsResponse, summary="Admin metrics panel"
)
def get_metrics(db: Session = Depends(get_db)) -> MetricsResponse:
    """The numbers the admin dashboard charts (SH.docx §5.1)."""
    total = db.scalar(select(func.count()).select_from(Shipment)) or 0

    def count_status(value: str) -> int:
        return (
            db.scalar(
                select(func.count())
                .select_from(Shipment)
                .where(Shipment.status == value)
            )
            or 0
        )

    delivered = count_status(ShipmentStatus.DELIVERED.value)
    misplaced = count_status(ShipmentStatus.MISPLACED.value)
    recovering = count_status(ShipmentStatus.RECOVERING.value)

    committed = db.scalars(
        select(RecoveryPlan).where(
            RecoveryPlan.status == PlanStatus.COMMITTED.value
        )
    ).all()

    mix: dict[str, int] = {}
    for plan in committed:
        mix[plan.strategy] = mix.get(plan.strategy, 0) + 1

    costs = [plan.total_cost for plan in committed]
    latencies = [plan.compute_ms for plan in committed if plan.compute_ms > 0]

    piggyback_like = sum(
        count
        for strategy, count in mix.items()
        if strategy in {
            PlanStrategy.PIGGYBACK.value,
            PlanStrategy.HYBRID.value,
            PlanStrategy.PRE_RESERVED.value,
        }
    )

    # Vehicle-km avoided: what a dedicated plan would have cost in distance,
    # minus what the committed piggyback plan actually used.
    km_avoided = 0.0
    for plan in committed:
        if plan.strategy == PlanStrategy.DEDICATED.value:
            continue
        dedicated = db.scalar(
            select(RecoveryPlan).where(
                RecoveryPlan.shipment_id == plan.shipment_id,
                RecoveryPlan.strategy == PlanStrategy.DEDICATED.value,
            )
        )
        if dedicated is not None:
            km_avoided += max(0.0, dedicated.transit_hours - plan.transit_hours) * 45.0

    bounty_total = (
        db.scalar(
            select(func.sum(Auction.payment)).where(
                Auction.status == AuctionStatus.AWARDED.value
            )
        )
        or 0.0
    )

    outcomes = summarise_errors(db)
    recovery_seconds = [
        row.recovery_seconds
        for row in db.scalars(select(RecoveryOutcome)).all()
        if row.recovery_seconds > 0
    ]

    return MetricsResponse(
        shipments_total=total,
        delivered=delivered,
        misplaced=misplaced,
        recovering=recovering,
        sla_percent=round(100.0 * delivered / total, 2) if total else 0.0,
        recovery_cost_total=round(sum(costs), 2),
        mean_recovery_cost=round(statistics.fmean(costs), 2) if costs else 0.0,
        recovered_via_existing_capacity_pct=(
            round(100.0 * piggyback_like / len(committed), 2) if committed else 0.0
        ),
        vehicle_km_avoided=round(km_avoided, 2),
        median_replan_latency_ms=(
            round(statistics.median(latencies), 3) if latencies else 0.0
        ),
        mean_replan_latency_ms=(
            round(statistics.fmean(latencies), 3) if latencies else 0.0
        ),
        mean_recovery_seconds=(
            round(statistics.fmean(recovery_seconds), 2) if recovery_seconds else 0.0
        ),
        strategy_mix=mix,
        bounty_paid_total=round(float(bounty_total), 2),
        outcome_summary=outcomes.as_dict(),
    )
