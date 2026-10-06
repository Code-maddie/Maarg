"""Recovery Pressure Score and Emergency Recovery Mode.

DOCUMENTED ASSUMPTION
---------------------
Pressure is one of the finalized feature list items but has no formula in
SH.docx §16, so the formula below is defined here rather than quoted.

Why it is not a duplicate of Temperature:

  Temperature T(s)  -> *business urgency*, in [0,100]. Feeds lambda, which
                       prices the shipment in rupees/hour. Answers
                       "how much is it worth spending to fix this?"

  Pressure P(s)     -> *operational stress*, in [0,1]. Answers
                       "how hard should the system search, and should it
                        stop being economical about it?"

They differ because an expensive shipment with plenty of slack is hot but not
under pressure, while a cheap shipment that has already failed three recovery
attempts with two hours left is under extreme pressure but never becomes hot
enough to justify a large bounty on urgency alone.

Pressure is a weighted mean of four normalised factors, so it is bounded in
[0, 1] by construction:

    P(s) = w_time*f_time + w_temp*f_temp + w_cascade*f_cascade + w_risk*f_risk

Crossing EMERGENCY_THRESHOLD puts the shipment into Emergency Recovery Mode,
which authorises the router to consider dedicated vehicles regardless of cost.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from app.models.base import utcnow

if TYPE_CHECKING:  # pragma: no cover
    from app.models import Shipment

# Weights sum to 1.0, which is what bounds the score in [0, 1].
W_TIME = 0.40
W_TEMPERATURE = 0.25
W_CASCADE = 0.20
W_RISK = 0.15

# At or above this, the shipment enters Emergency Recovery Mode.
EMERGENCY_THRESHOLD = 0.75

# Time pressure reaches zero this far ahead of the deadline.
TIME_HORIZON_HOURS = 12.0

# Cascade depth at or beyond this saturates its factor.
CASCADE_SATURATION_DEPTH = 5

# Failed recovery attempts at or beyond this saturate the risk factor.
ATTEMPT_SATURATION = 3


@dataclass(frozen=True, slots=True)
class PressureBreakdown:
    """Pressure with every contributing factor, for the Explainer."""

    shipment_id: Optional[int]
    pressure: float
    emergency: bool
    f_time: float
    f_temperature: float
    f_cascade: float
    f_risk: float
    hours_to_deadline: float

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def time_factor(hours_to_deadline: float) -> float:
    """1.0 at or past the deadline, 0.0 at the horizon, linear between."""
    if hours_to_deadline <= 0:
        return 1.0
    if hours_to_deadline >= TIME_HORIZON_HOURS:
        return 0.0
    return (TIME_HORIZON_HOURS - hours_to_deadline) / TIME_HORIZON_HOURS


def temperature_factor(temperature: float) -> float:
    """Normalises T(s) from [0,100] onto [0,1]."""
    return _clamp01(temperature / 100.0)


def cascade_factor(cascade_depth: int) -> float:
    if cascade_depth <= 0:
        return 0.0
    return _clamp01(cascade_depth / CASCADE_SATURATION_DEPTH)


def risk_factor(p_misplace: Optional[float], failed_attempts: int = 0) -> float:
    """Blends E1 risk with how many recovery attempts have already failed.

    Failed attempts are weighted more heavily than the prior probability:
    an attempt that actually failed is stronger evidence than a prediction.
    """
    prior = _clamp01(p_misplace if p_misplace is not None else 0.0)
    attempts = _clamp01(failed_attempts / ATTEMPT_SATURATION)
    return _clamp01(0.4 * prior + 0.6 * attempts)


def compute_pressure(
    *,
    hours_to_deadline: float,
    temperature: float,
    cascade_depth: int = 0,
    p_misplace: Optional[float] = None,
    failed_attempts: int = 0,
    shipment_id: Optional[int] = None,
) -> PressureBreakdown:
    """Computes the Recovery Pressure Score with a full breakdown."""
    f_time = time_factor(hours_to_deadline)
    f_temp = temperature_factor(temperature)
    f_cascade = cascade_factor(cascade_depth)
    f_risk = risk_factor(p_misplace, failed_attempts)

    pressure = _clamp01(
        W_TIME * f_time
        + W_TEMPERATURE * f_temp
        + W_CASCADE * f_cascade
        + W_RISK * f_risk
    )

    return PressureBreakdown(
        shipment_id=shipment_id,
        pressure=round(pressure, 4),
        emergency=pressure >= EMERGENCY_THRESHOLD,
        f_time=round(f_time, 4),
        f_temperature=round(f_temp, 4),
        f_cascade=round(f_cascade, 4),
        f_risk=round(f_risk, 4),
        hours_to_deadline=round(hours_to_deadline, 3),
    )


def evaluate_shipment(
    shipment: "Shipment",
    now: Optional[datetime] = None,
    *,
    failed_attempts: int = 0,
) -> PressureBreakdown:
    """Computes pressure for a persisted shipment without writing."""
    moment = now or utcnow()
    return compute_pressure(
        hours_to_deadline=shipment.hours_to_deadline(moment),
        temperature=shipment.temperature,
        cascade_depth=shipment.cascade_depth,
        p_misplace=shipment.p_misplace,
        failed_attempts=failed_attempts,
        shipment_id=shipment.id,
    )


def apply_pressure(
    shipment: "Shipment",
    now: Optional[datetime] = None,
    *,
    failed_attempts: int = 0,
) -> PressureBreakdown:
    """Computes pressure and writes it onto the shipment."""
    breakdown = evaluate_shipment(shipment, now, failed_attempts=failed_attempts)
    shipment.pressure = breakdown.pressure
    return breakdown
