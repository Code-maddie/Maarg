"""E2 — Foresight Reservation.

Pre-buys cargo space against predicted misplacement risk, so that when a
shipment actually goes missing the recovery is instant instead of requiring
a fresh search and auction.

The buy rule is the critical-fractile condition from SH.docx §16:

    Buy option  <=>  P(misplace) >= Premium / (Premium + C_dedicated - E[Bounty])

Read plainly: pay the premium only when the risk is high enough that the
expected saving — the difference between dedicated recovery and what a
bounty would have cost — outweighs the premium being spent up front.

CALIBRATION WARNING
-------------------
This rule consumes P(misplace) directly, so it is only as good as E1's
calibration. The bundled E1 artifact has a measured test ROC-AUC of 0.4999
and a Brier score of 0.243, which means its probabilities are
close to uninformative. The maths here is correct and independently tested;
the *inputs* are weak. Recorded rather than silently worked around.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Shipment

logger = get_logger(__name__)

# Premium charged to hold an option, as a fraction of the dedicated cost it
# insures against.
DEFAULT_PREMIUM_RATE = 0.08

# Below this probability the option is never worth buying, regardless of the
# arithmetic — avoids buying thousands of near-worthless options.
MIN_RISK_TO_CONSIDER = 0.05


@dataclass(frozen=True, slots=True)
class ReservationDecision:
    """Whether to buy, and the numbers behind it."""

    shipment_id: Optional[int]
    should_reserve: bool
    p_misplace: float
    threshold: float
    premium: float
    dedicated_cost: float
    expected_bounty: float
    expected_saving: float
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def critical_fractile_threshold(
    *, premium: float, dedicated_cost: float, expected_bounty: float
) -> float:
    """Premium / (Premium + C_dedicated - E[Bounty]), clamped to [0, 1].

    The denominator is the premium plus the saving the option unlocks. When
    that saving is zero or negative the option can never pay for itself, so
    the threshold is 1.0 — i.e. buy only at certainty, which never happens.
    """
    saving = dedicated_cost - expected_bounty

    if premium <= 0:
        # A free option is always worth taking.
        return 0.0

    denominator = premium + saving
    if denominator <= 0 or saving <= 0:
        return 1.0

    return max(0.0, min(1.0, premium / denominator))


def evaluate_reservation(
    *,
    p_misplace: Optional[float],
    dedicated_cost: float,
    expected_bounty: float,
    premium: Optional[float] = None,
    premium_rate: float = DEFAULT_PREMIUM_RATE,
    shipment_id: Optional[int] = None,
) -> ReservationDecision:
    """Applies the critical-fractile rule to one shipment."""
    risk = 0.0 if p_misplace is None else max(0.0, min(1.0, p_misplace))
    cost_of_premium = (
        premium if premium is not None else dedicated_cost * premium_rate
    )
    saving = dedicated_cost - expected_bounty

    threshold = critical_fractile_threshold(
        premium=cost_of_premium,
        dedicated_cost=dedicated_cost,
        expected_bounty=expected_bounty,
    )

    if p_misplace is None:
        should = False
        reason = "Shipment has not been scored by E1; no risk estimate available"
    elif risk < MIN_RISK_TO_CONSIDER:
        should = False
        reason = (
            f"Risk {risk:.3f} is below the {MIN_RISK_TO_CONSIDER:.2f} floor "
            "for considering an option"
        )
    elif saving <= 0:
        should = False
        reason = (
            f"Expected bounty {expected_bounty:.2f} is not cheaper than "
            f"dedicated recovery {dedicated_cost:.2f}; the option saves nothing"
        )
    elif risk >= threshold:
        should = True
        reason = (
            f"P(misplace) {risk:.3f} >= threshold {threshold:.3f}: "
            f"premium {cost_of_premium:.2f} is justified by an expected "
            f"saving of {saving:.2f}"
        )
    else:
        should = False
        reason = (
            f"P(misplace) {risk:.3f} < threshold {threshold:.3f}: "
            f"premium {cost_of_premium:.2f} is not justified"
        )

    return ReservationDecision(
        shipment_id=shipment_id,
        should_reserve=should,
        p_misplace=round(risk, 4),
        threshold=round(threshold, 4),
        premium=round(cost_of_premium, 2),
        dedicated_cost=round(dedicated_cost, 2),
        expected_bounty=round(expected_bounty, 2),
        expected_saving=round(saving, 2),
        reason=reason,
    )


def evaluate_shipment(
    shipment: Shipment,
    *,
    dedicated_cost: float,
    expected_bounty: float,
    premium_rate: float = DEFAULT_PREMIUM_RATE,
) -> ReservationDecision:
    """Reservation decision for a persisted shipment."""
    return evaluate_reservation(
        p_misplace=shipment.p_misplace,
        dedicated_cost=dedicated_cost,
        expected_bounty=expected_bounty,
        premium_rate=premium_rate,
        shipment_id=shipment.id,
    )


def premium_burn_ratio(
    premiums_paid: float, recoveries_avoided_cost: float
) -> float:
    """Premium spent per rupee of recovery cost avoided.

    SH.docx §5.1 calls this out as the Foresight-specific metric judges ask
    about. Below 1.0 means the options paid for themselves.
    """
    if recoveries_avoided_cost <= 0:
        return float("inf") if premiums_paid > 0 else 0.0
    return round(premiums_paid / recoveries_avoided_cost, 4)
