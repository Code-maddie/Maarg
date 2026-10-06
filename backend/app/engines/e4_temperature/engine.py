"""E4 — Adaptive Recovery Temperature and lambda.

Implements the SH.docx §16 formula sheet verbatim:

    T(s) = clamp(0, 100, T_base + T_time + T_delay + T_cascade)
    lambda(s) = sla_penalty_per_hour * (1 + T(s) / 50)        [rupees/hour]

Temperature is how urgently a shipment needs recovering; lambda converts that
urgency into rupees per hour, which is what the router and the bounty market
actually price against.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.engines.e4_temperature.policy import PolicyWeights, get_active_weights
from app.models.base import utcnow
from app.models.enums import TemperatureZone

if TYPE_CHECKING:  # pragma: no cover
    from app.models import Shipment

TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 100.0

# Beyond this many hours to the deadline, time pressure is effectively zero.
TIME_HORIZON_HOURS = 24.0

# Lateness at or beyond this many hours saturates the delay term.
DELAY_SATURATION_HOURS = 12.0

# Cascade depth at or beyond this saturates the cascade term.
CASCADE_SATURATION_DEPTH = 5

# Priority at or above this saturates the base term.
PRIORITY_SATURATION = 2.0


@dataclass(frozen=True, slots=True)
class TemperatureBreakdown:
    """Every term that produced a temperature.

    Returned in full because E8 (Explainer) has to show *why* a shipment is
    hot, not merely how hot it is.
    """

    shipment_id: Optional[int]
    temperature: float
    lam: float
    zone: str
    t_base: float
    t_time: float
    t_delay: float
    t_cascade: float
    hours_to_deadline: float
    policy_mode: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalise(value: float, saturation: float) -> float:
    """Maps ``value`` onto [0, 1], saturating at ``saturation``."""
    if saturation <= 0:
        return 0.0
    return _clamp(value / saturation, 0.0, 1.0)


def compute_base_term(base_priority: float, weights: PolicyWeights) -> float:
    """T_base — the shipment's intrinsic importance."""
    return weights.w_base * _normalise(base_priority, PRIORITY_SATURATION)


def compute_time_term(hours_to_deadline: float, weights: PolicyWeights) -> float:
    """T_time — rises as the deadline approaches, maxes out once overdue.

    Deliberately non-linear: urgency should climb slowly a day out and
    steeply in the final hours.
    """
    if hours_to_deadline <= 0:
        return weights.w_time

    if hours_to_deadline >= TIME_HORIZON_HOURS:
        return 0.0

    # 1.0 at the deadline, 0.0 at the horizon; squared so it bites late.
    closeness = (TIME_HORIZON_HOURS - hours_to_deadline) / TIME_HORIZON_HOURS
    return weights.w_time * (closeness**2)


def compute_delay_term(hours_overdue: float, weights: PolicyWeights) -> float:
    """T_delay — accumulated lateness already incurred."""
    if hours_overdue <= 0:
        return 0.0
    return weights.w_delay * _normalise(hours_overdue, DELAY_SATURATION_HOURS)


def compute_cascade_term(cascade_depth: int, weights: PolicyWeights) -> float:
    """T_cascade — how much downstream disruption this shipment is causing."""
    if cascade_depth <= 0:
        return 0.0
    return weights.w_cascade * _normalise(
        float(cascade_depth), float(CASCADE_SATURATION_DEPTH)
    )


def compute_lambda(temperature: float, sla_penalty_per_hour: float) -> float:
    """lambda(s) = sla_penalty_per_hour * (1 + T/50)  — SH.docx §16.

    At T=0 lambda equals the base penalty; at T=50 it doubles; at T=100 it
    triples.
    """
    return sla_penalty_per_hour * (1.0 + temperature / 50.0)


def zone_for(temperature: float) -> TemperatureZone:
    """Cold / Warming / Hot banding used by the dispatcher queue."""
    if temperature >= 67:
        return TemperatureZone.HOT
    if temperature >= 34:
        return TemperatureZone.WARMING
    return TemperatureZone.COLD


def compute_temperature(
    *,
    base_priority: float,
    hours_to_deadline: float,
    hours_overdue: float,
    cascade_depth: int,
    sla_penalty_per_hour: float,
    weights: PolicyWeights,
    customer_premium: float = 0.0,
    shipment_id: Optional[int] = None,
    policy_mode: str = "BUSINESS",
) -> TemperatureBreakdown:
    """Pure function computing T(s) and lambda(s) with a full breakdown."""
    t_base = compute_base_term(base_priority, weights)
    t_time = compute_time_term(hours_to_deadline, weights)
    t_delay = compute_delay_term(hours_overdue, weights)
    t_cascade = compute_cascade_term(cascade_depth, weights)

    temperature = _clamp(
        t_base + t_time + t_delay + t_cascade, TEMPERATURE_MIN, TEMPERATURE_MAX
    )

    # A customer paying to expedite raises lambda, never the engine's decision
    # (SH.docx §4.4: "an input, not an override").
    lam = compute_lambda(temperature, sla_penalty_per_hour) + max(
        0.0, customer_premium
    )

    return TemperatureBreakdown(
        shipment_id=shipment_id,
        temperature=round(temperature, 3),
        lam=round(lam, 2),
        zone=str(zone_for(temperature)),
        t_base=round(t_base, 3),
        t_time=round(t_time, 3),
        t_delay=round(t_delay, 3),
        t_cascade=round(t_cascade, 3),
        hours_to_deadline=round(hours_to_deadline, 3),
        policy_mode=policy_mode,
    )


class TemperatureEngine:
    """E4 applied to persisted shipments."""

    def __init__(self, weights: PolicyWeights, policy_mode: str = "BUSINESS") -> None:
        self.weights = weights
        self.policy_mode = policy_mode

    @classmethod
    def from_db(cls, db: Session) -> "TemperatureEngine":
        """Builds an engine using the policy mode currently in force."""
        from app.engines.e4_temperature.policy import get_policy

        return cls(weights=get_active_weights(db), policy_mode=get_policy(db).mode)

    def evaluate(
        self, shipment: "Shipment", now: Optional[datetime] = None
    ) -> TemperatureBreakdown:
        """Computes T and lambda for one shipment without persisting."""
        moment = now or utcnow()
        hours_left = shipment.hours_to_deadline(moment)

        return compute_temperature(
            base_priority=shipment.base_priority,
            hours_to_deadline=hours_left,
            hours_overdue=max(0.0, -hours_left),
            cascade_depth=shipment.cascade_depth,
            sla_penalty_per_hour=shipment.sla_penalty_per_hour,
            weights=self.weights,
            customer_premium=shipment.customer_premium,
            shipment_id=shipment.id,
            policy_mode=self.policy_mode,
        )

    def apply(
        self, shipment: "Shipment", now: Optional[datetime] = None
    ) -> TemperatureBreakdown:
        """Computes and writes T and lambda onto the shipment."""
        breakdown = self.evaluate(shipment, now)
        shipment.temperature = breakdown.temperature
        shipment.lam = breakdown.lam
        return breakdown

    def apply_many(
        self,
        db: Session,
        shipments: Iterable["Shipment"],
        now: Optional[datetime] = None,
    ) -> List[TemperatureBreakdown]:
        """Applies E4 across many shipments and commits once."""
        moment = now or utcnow()
        results = [self.apply(shipment, moment) for shipment in shipments]
        db.commit()
        return results
