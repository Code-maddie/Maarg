"""E9 — Recovery Outcome Learning.

Closes the loop: every recovery attempt is compared against what the engines
predicted, and the discrepancy is recorded. Those records are the training
set a future E1 retraining run would use.

E9 is strictly an **observer**. It reads the outputs of E1–E8 and writes to
its own table; it never alters an engine's behaviour, which is what keeps it
an extension rather than a change to the documented architecture.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import RecoveryOutcome, Shipment
from app.models.enums import ShipmentStatus

logger = get_logger(__name__)


@dataclass
class PredictionSnapshot:
    """What the engines believed at the moment a plan was committed."""

    cost: float
    arrival: Optional[datetime]
    p_misplace: Optional[float]
    temperature: float
    lam: float
    strategy: str
    plan_id: Optional[int] = None


@dataclass
class ActualResult:
    """What actually happened."""

    cost: float
    arrival: Optional[datetime]
    succeeded: bool
    misplaced: bool = False
    failure_reason: Optional[str] = None
    recovery_seconds: float = 0.0


@dataclass
class ErrorSummary:
    """Aggregate accuracy across many recorded outcomes."""

    count: int
    success_rate: float
    mean_cost_error: float
    mean_abs_cost_error: float
    mean_eta_error_hours: float
    mean_abs_eta_error_hours: float
    deadline_hit_rate: float
    brier_score: Optional[float]
    cost_bias: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def brier_contribution(
    predicted: Optional[float], happened: bool
) -> Optional[float]:
    """(p - outcome)^2 for one observation.

    Averaged over many rows this is the Brier score, which is how E1's
    *calibration* is measured live — the property SH.docx §10.2 stresses and
    the bundled artifact scores poorly on (Brier 0.243).
    """
    if predicted is None:
        return None
    outcome = 1.0 if happened else 0.0
    return round((predicted - outcome) ** 2, 6)


def record_outcome(
    db: Session,
    shipment: Shipment,
    *,
    predicted: PredictionSnapshot,
    actual: ActualResult,
    deadline: Optional[datetime] = None,
    notes: Optional[str] = None,
) -> RecoveryOutcome:
    """Writes one outcome record. This is the E9 write path."""
    due = deadline or shipment.deadline_at

    cost_error = round(actual.cost - predicted.cost, 2)

    eta_error = 0.0
    if predicted.arrival is not None and actual.arrival is not None:
        eta_error = round(
            (actual.arrival - predicted.arrival).total_seconds() / 3600.0, 4
        )

    met_deadline = bool(
        actual.succeeded and actual.arrival is not None and due is not None
        and actual.arrival <= due
    )

    outcome = RecoveryOutcome(
        shipment_id=shipment.id,
        plan_id=predicted.plan_id,
        strategy=predicted.strategy,
        succeeded=actual.succeeded,
        predicted_cost=round(predicted.cost, 2),
        predicted_arrival=predicted.arrival,
        predicted_p_misplace=predicted.p_misplace,
        predicted_temperature=round(predicted.temperature, 3),
        predicted_lambda=round(predicted.lam, 2),
        actual_cost=round(actual.cost, 2),
        actual_arrival=actual.arrival,
        actually_misplaced=actual.misplaced,
        cost_error=cost_error,
        eta_error_hours=eta_error,
        risk_brier=brier_contribution(predicted.p_misplace, actual.misplaced),
        met_deadline=met_deadline,
        recovery_seconds=round(actual.recovery_seconds, 3),
        failure_reason=actual.failure_reason,
        notes=notes,
    )

    db.add(outcome)
    db.commit()

    logger.info(
        "E9 recorded outcome for %s: %s, cost error %.2f, ETA error %.2fh",
        shipment.code,
        "succeeded" if actual.succeeded else "failed",
        cost_error, eta_error,
    )
    return outcome


def record_from_shipment(
    db: Session,
    shipment: Shipment,
    *,
    predicted: PredictionSnapshot,
    now: datetime,
    actual_cost: Optional[float] = None,
) -> RecoveryOutcome:
    """Derives the actual result from the shipment's current state.

    Used by the orchestrator when a recovery completes without the caller
    tracking the outcome separately.
    """
    succeeded = shipment.status == ShipmentStatus.DELIVERED.value
    arrival = shipment.delivered_at if succeeded else None

    recovery_seconds = 0.0
    if shipment.misplaced_at is not None:
        end = arrival or now
        recovery_seconds = max(0.0, (end - shipment.misplaced_at).total_seconds())

    return record_outcome(
        db,
        shipment,
        predicted=predicted,
        actual=ActualResult(
            cost=actual_cost if actual_cost is not None else predicted.cost,
            arrival=arrival,
            succeeded=succeeded,
            misplaced=shipment.misplaced_at is not None,
            failure_reason=(
                None if succeeded else f"Shipment ended in state {shipment.status}"
            ),
            recovery_seconds=recovery_seconds,
        ),
    )


def summarise_errors(
    db: Session, *, strategy: Optional[str] = None
) -> ErrorSummary:
    """Aggregate accuracy over recorded outcomes.

    This is what an admin sees when asking "is the engine actually any good?",
    and what would justify a retraining run.
    """
    query = select(RecoveryOutcome)
    if strategy is not None:
        query = query.where(RecoveryOutcome.strategy == strategy)

    rows: Sequence[RecoveryOutcome] = db.scalars(query).all()

    if not rows:
        return ErrorSummary(
            count=0, success_rate=0.0, mean_cost_error=0.0,
            mean_abs_cost_error=0.0, mean_eta_error_hours=0.0,
            mean_abs_eta_error_hours=0.0, deadline_hit_rate=0.0,
            brier_score=None, cost_bias="no data",
        )

    count = len(rows)
    mean_cost_error = sum(row.cost_error for row in rows) / count
    briers = [row.risk_brier for row in rows if row.risk_brier is not None]

    if mean_cost_error > 1.0:
        bias = "under-estimating cost"
    elif mean_cost_error < -1.0:
        bias = "over-estimating cost"
    else:
        bias = "well calibrated on cost"

    return ErrorSummary(
        count=count,
        success_rate=round(sum(1 for r in rows if r.succeeded) / count, 4),
        mean_cost_error=round(mean_cost_error, 2),
        mean_abs_cost_error=round(
            sum(abs(r.cost_error) for r in rows) / count, 2
        ),
        mean_eta_error_hours=round(
            sum(r.eta_error_hours for r in rows) / count, 4
        ),
        mean_abs_eta_error_hours=round(
            sum(abs(r.eta_error_hours) for r in rows) / count, 4
        ),
        deadline_hit_rate=round(
            sum(1 for r in rows if r.met_deadline) / count, 4
        ),
        brier_score=round(sum(briers) / len(briers), 6) if briers else None,
        cost_bias=bias,
    )


def training_records(
    db: Session, *, limit: int = 1000
) -> List[Dict[str, Any]]:
    """Exports outcomes as rows a retraining notebook can consume.

    Deliberately plain dicts: SH.docx §10.1 keeps Colab decoupled from the
    backend, so the handoff is data, not objects.
    """
    rows = db.scalars(
        select(RecoveryOutcome).order_by(RecoveryOutcome.id.desc()).limit(limit)
    ).all()

    return [
        {
            "shipment_id": row.shipment_id,
            "strategy": row.strategy,
            "predicted_p_misplace": row.predicted_p_misplace,
            "actually_misplaced": int(row.actually_misplaced),
            "predicted_cost": row.predicted_cost,
            "actual_cost": row.actual_cost,
            "cost_error": row.cost_error,
            "eta_error_hours": row.eta_error_hours,
            "predicted_temperature": row.predicted_temperature,
            "predicted_lambda": row.predicted_lambda,
            "succeeded": int(row.succeeded),
            "met_deadline": int(row.met_deadline),
            "recovery_seconds": row.recovery_seconds,
        }
        for row in rows
    ]
