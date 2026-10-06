"""Policy modes — the admin dial that re-weights E4 (SH.docx §5.1).

Changing the mode changes the coefficients E4 uses for T_base and its
component terms, so the next tick visibly produces different recommendations.
This is the strongest "look, it's adaptive" control in the demo.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import PolicyMode
from app.models.enums import PolicyModeName

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PolicyWeights:
    """Coefficients consumed by E4.

    ``w_base`` scales the shipment's intrinsic priority; ``w_time`` how hard
    an approaching deadline bites; ``w_delay`` how much accumulated lateness
    counts; ``w_cascade`` how much downstream impact counts.
    """

    w_base: float = 20.0
    w_time: float = 40.0
    w_delay: float = 25.0
    w_cascade: float = 15.0

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)


# Each mode is a different opinion about what matters. Weights are tuned so
# every mode can still reach the full 0-100 range.
POLICY_WEIGHTS: Dict[str, PolicyWeights] = {
    # Balanced default.
    PolicyModeName.BUSINESS.value: PolicyWeights(
        w_base=20.0, w_time=40.0, w_delay=25.0, w_cascade=15.0
    ),
    # Deadlines dominate: heat rises sharply as the clock runs out.
    PolicyModeName.SLA_STRICT.value: PolicyWeights(
        w_base=10.0, w_time=60.0, w_delay=25.0, w_cascade=5.0
    ),
    # Long-waiting shipments matter most, regardless of their value.
    PolicyModeName.FAIRNESS.value: PolicyWeights(
        w_base=5.0, w_time=25.0, w_delay=60.0, w_cascade=10.0
    ),
    # Protect the network: downstream impact dominates.
    PolicyModeName.EFFICIENCY.value: PolicyWeights(
        w_base=15.0, w_time=25.0, w_delay=15.0, w_cascade=45.0
    ),
}

DEFAULT_MODE = PolicyModeName.BUSINESS.value


def weights_for(mode: str) -> PolicyWeights:
    """Returns the weights for a mode, falling back to BUSINESS."""
    return POLICY_WEIGHTS.get(mode, POLICY_WEIGHTS[DEFAULT_MODE])


def get_policy(db: Session) -> PolicyMode:
    """Returns the singleton policy row, creating it on first use."""
    policy = db.scalars(select(PolicyMode).order_by(PolicyMode.id).limit(1)).first()

    if policy is None:
        policy = PolicyMode(
            mode=DEFAULT_MODE,
            weights_json=json.dumps(weights_for(DEFAULT_MODE).as_dict()),
        )
        db.add(policy)
        db.commit()

    return policy


def get_active_weights(db: Session) -> PolicyWeights:
    """Weights currently in force.

    Any custom coefficients stored on the row override the mode defaults, so
    an admin can tune without inventing a new mode.
    """
    policy = get_policy(db)
    defaults = weights_for(policy.mode)

    try:
        stored = json.loads(policy.weights_json or "{}")
    except json.JSONDecodeError:
        logger.warning("PolicyMode.weights_json is not valid JSON; using defaults")
        return defaults

    if not isinstance(stored, dict) or not stored:
        return defaults

    merged = {**defaults.as_dict()}
    for key, value in stored.items():
        if key in merged and isinstance(value, (int, float)):
            merged[key] = float(value)

    return PolicyWeights(**merged)


def set_policy(
    db: Session,
    mode: str,
    *,
    weights: Optional[Dict[str, float]] = None,
    updated_by: Optional[int] = None,
) -> PolicyMode:
    """Switches the active policy mode. Raises on an unknown mode."""
    if mode not in POLICY_WEIGHTS:
        raise ValueError(
            f"Unknown policy mode '{mode}'. "
            f"Expected one of: {', '.join(sorted(POLICY_WEIGHTS))}"
        )

    policy = get_policy(db)
    policy.mode = mode
    policy.weights_json = json.dumps(weights or weights_for(mode).as_dict())
    policy.updated_by = updated_by
    db.commit()

    logger.info("Policy mode set to %s", mode)
    return policy
