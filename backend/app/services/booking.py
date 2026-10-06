"""Turns a committed recovery plan into physical bookings (audit fix).

Before this, committing a plan wrote RecoveryPlan rows only: no leg was
booked and no capacity consumed. Two recoveries could therefore commit the
same last 85 kg of a truck, and a recovered shipment was never placed on
any vehicle, so it stayed RECOVERING forever and E9 never saw an outcome.

Rules
-----
* Committing a plan first releases every *not-yet-departed* booking the
  shipment holds (its original itinerary, or a previous recovery), then books
  each piggyback leg of the new plan, consuming residual capacity.
* A leg that has already departed is never touched: its capacity was handled
  by the simulator when the shipment boarded or was misplaced.
* Dedicated hops (no leg) consume no scheduled capacity.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Leg, RecoveryOutcome, RecoveryPlan, Shipment, ShipmentLeg
from app.models.enums import LegStatus, PlanStatus

logger = get_logger(__name__)

BOOKABLE = (LegStatus.SCHEDULED.value, LegStatus.DELAYED.value)


def release_pending_bookings(db: Session, shipment: Shipment) -> int:
    """Frees capacity on every booking the shipment has not boarded yet."""
    released = 0
    links = db.scalars(
        select(ShipmentLeg).where(
            ShipmentLeg.shipment_id == shipment.id,
            ShipmentLeg.boarded_at.is_(None),
        )
    ).all()
    for link in links:
        leg = db.get(Leg, link.leg_id)
        if leg is not None:
            leg.residual_kg = min(leg.capacity_kg, leg.residual_kg + shipment.weight_kg)
            leg.residual_m3 = min(leg.capacity_m3, leg.residual_m3 + shipment.volume_m3)
        db.delete(link)
        released += 1
    return released


def book_plan(db: Session, shipment: Shipment, plan: RecoveryPlan) -> List[int]:
    """Books the plan's legs for the shipment. Returns legs that could not be
    booked (gone, departed or full) so callers can record them as failed."""
    release_pending_bookings(db, shipment)
    db.flush()

    failed: List[int] = []
    for step in sorted(plan.paths, key=lambda p: p.seq):
        if step.leg_id is None:
            continue  # dedicated hop
        leg = db.get(Leg, step.leg_id)
        if (
            leg is None
            or leg.status not in BOOKABLE
            or not leg.can_fit(shipment.weight_kg, shipment.volume_m3)
        ):
            failed.append(step.leg_id)
            continue
        leg.residual_kg = round(leg.residual_kg - shipment.weight_kg, 3)
        leg.residual_m3 = round(leg.residual_m3 - shipment.volume_m3, 3)
        db.add(ShipmentLeg(shipment_id=shipment.id, leg_id=leg.id,
                           seq=step.seq, is_recovery=True))

    if failed:
        logger.warning("Plan %d for %s: legs %s could not be booked",
                       plan.id, shipment.code, failed)
    return failed


def complete_recovery(db: Session, shipment: Shipment, now: datetime) -> bool:
    """Called when a shipment with a committed recovery is delivered.

    Marks the plan COMPLETED and records the E9 outcome (predicted vs
    actual), closing the Predict -> Price -> Plan -> Prove loop. Never raises.
    """
    try:
        plan = db.scalar(
            select(RecoveryPlan).where(
                RecoveryPlan.shipment_id == shipment.id,
                RecoveryPlan.status == PlanStatus.COMMITTED.value,
            )
        )
        if plan is None:
            return False

        already = db.scalar(
            select(RecoveryOutcome).where(RecoveryOutcome.plan_id == plan.id)
        )
        plan.status = PlanStatus.COMPLETED.value
        if already is not None:
            return True

        from app.engines.e9_learning.outcomes import ActualResult, PredictionSnapshot, record_outcome

        recovery_seconds = 0.0
        if shipment.misplaced_at is not None:
            recovery_seconds = max(0.0, (now - shipment.misplaced_at).total_seconds())

        record_outcome(
            db, shipment,
            predicted=PredictionSnapshot(
                cost=plan.total_cost, arrival=plan.eta,
                p_misplace=shipment.p_misplace, temperature=shipment.temperature,
                lam=shipment.lam, strategy=plan.strategy, plan_id=plan.id,
            ),
            actual=ActualResult(
                # The simulation has no cost variance; timing variance (delays)
                # is real, so the ETA error is the meaningful signal.
                cost=plan.total_cost, arrival=now, succeeded=True,
                misplaced=shipment.misplaced_at is not None,
                recovery_seconds=recovery_seconds,
            ),
            notes="Recorded automatically on delivery",
        )
        return True
    except Exception:  # noqa: BLE001 - must never break a tick
        logger.exception("Recording the recovery outcome for %s failed", shipment.code)
        return False
