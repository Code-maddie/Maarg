"""E1 feature contract.

The eight features and their ordering are fixed by the trained artifact's
``feature_schema.json``. Nothing here may be changed without retraining E1 —
the ColumnTransformer was fitted against exactly this column order.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Final, Mapping

# Order matters: the fitted ColumnTransformer indexes columns positionally.
FEATURE_ORDER: Final[tuple[str, ...]] = (
    "route",
    "hub",
    "carrier",
    "congestion_index",
    "num_handoffs",
    "sorting_method",
    "weather_flag",
    "hour_of_day",
)

CATEGORICAL_FEATURES: Final[frozenset[str]] = frozenset(
    {"route", "hub", "carrier", "sorting_method"}
)
NUMERIC_FEATURES: Final[frozenset[str]] = frozenset(
    {"congestion_index", "num_handoffs", "weather_flag", "hour_of_day"}
)

# The training data contains exactly one sorting_method value. The metadata
# records it as an explicit contract placeholder, not a real observation.
SORTING_METHOD_PLACEHOLDER: Final[str] = "unknown"

# Observed training ranges, used for validation only — values outside these
# are accepted (the pipeline handles them) but are worth flagging.
NUMERIC_RANGES: Final[Dict[str, tuple[float, float]]] = {
    "congestion_index": (0.0, 1.0),
    "num_handoffs": (0.0, 50.0),
    "weather_flag": (0.0, 1.0),
    "hour_of_day": (0.0, 23.0),
}


class FeatureValidationError(ValueError):
    """Raised when an inference payload does not satisfy the E1 contract."""


@dataclass(frozen=True, slots=True)
class E1Features:
    """One scored unit: a shipment at a hub on a route at an hour."""

    route: str
    hub: str
    carrier: str
    congestion_index: float
    num_handoffs: int
    weather_flag: int
    hour_of_day: int
    sorting_method: str = SORTING_METHOD_PLACEHOLDER

    def as_row(self) -> Dict[str, Any]:
        """Dict in the exact column order the pipeline expects."""
        data = asdict(self)
        return {name: data[name] for name in FEATURE_ORDER}


def validate_features(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Checks an inference payload and returns it in canonical column order.

    Raises :class:`FeatureValidationError` with an explicit message rather
    than letting a malformed row reach the pipeline, where the failure would
    surface as an opaque numpy or sklearn error.
    """
    missing = [name for name in FEATURE_ORDER if name not in payload]
    if missing:
        raise FeatureValidationError(
            f"Missing required feature(s): {', '.join(sorted(missing))}. "
            f"E1 requires exactly: {', '.join(FEATURE_ORDER)}"
        )

    unexpected = set(payload) - set(FEATURE_ORDER)
    if unexpected:
        raise FeatureValidationError(
            f"Unexpected feature(s): {', '.join(sorted(unexpected))}"
        )

    row: Dict[str, Any] = {}
    for name in FEATURE_ORDER:
        value = payload[name]

        if value is None:
            raise FeatureValidationError(f"Feature '{name}' must not be None")

        if name in CATEGORICAL_FEATURES:
            if not isinstance(value, str):
                raise FeatureValidationError(
                    f"Feature '{name}' must be a string, got "
                    f"{type(value).__name__}"
                )
            row[name] = value
            continue

        # Numeric. bool is a subclass of int, so it is accepted deliberately
        # for weather_flag.
        if isinstance(value, bool):
            value = int(value)
        if not isinstance(value, (int, float)):
            raise FeatureValidationError(
                f"Feature '{name}' must be numeric, got {type(value).__name__}"
            )
        row[name] = float(value)

    return row


def clamp_probability(value: float) -> float:
    """Bounds a probability into [0, 1].

    E2's critical-fractile maths divides by terms derived from this value, so
    a NaN or out-of-range probability escaping here would corrupt downstream
    engines rather than fail loudly.
    """
    probability = float(value)
    if probability != probability:  # NaN
        raise ValueError("Model returned NaN probability")
    return min(1.0, max(0.0, probability))
