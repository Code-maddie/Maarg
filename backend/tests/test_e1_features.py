"""Phase 3 validation: the E1 feature contract.

These tests need no model, so they run fast and catch contract drift before
the 205 MB artifact is ever touched.
"""

import json

import pytest

from app.core.config import settings
from app.engines.e1_misplacement.features import (
    CATEGORICAL_FEATURES,
    FEATURE_ORDER,
    NUMERIC_FEATURES,
    E1Features,
    FeatureValidationError,
    clamp_probability,
    validate_features,
)
from app.engines.e1_misplacement.service import build_features

VALID_ROW = {
    "route": "R000",
    "hub": "F000",
    "carrier": "air",
    "congestion_index": 0.42,
    "num_handoffs": 3,
    "sorting_method": "unknown",
    "weather_flag": 0,
    "hour_of_day": 17,
}


def test_feature_order_matches_the_trained_artifact() -> None:
    """The single most important test in Phase 3.

    If the code's column order ever diverges from the fitted
    ColumnTransformer, every probability becomes silently wrong.
    """
    schema_path = settings.e1_artifact_path / "feature_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert tuple(schema["feature_ordering"]) == FEATURE_ORDER
    assert tuple(schema["expected_input_features"]) == FEATURE_ORDER
    assert set(schema["categorical_features"]) == CATEGORICAL_FEATURES
    assert set(schema["numeric_features"]) == NUMERIC_FEATURES


def test_dataclass_row_is_in_contract_order() -> None:
    features = E1Features(
        route="R1", hub="F1", carrier="air", congestion_index=0.5,
        num_handoffs=2, weather_flag=1, hour_of_day=9,
    )
    assert tuple(features.as_row()) == FEATURE_ORDER


def test_validate_accepts_a_good_row() -> None:
    assert tuple(validate_features(VALID_ROW)) == FEATURE_ORDER


def test_validate_rejects_a_missing_feature() -> None:
    row = {k: v for k, v in VALID_ROW.items() if k != "carrier"}
    with pytest.raises(FeatureValidationError, match="carrier"):
        validate_features(row)


def test_validate_rejects_an_unexpected_feature() -> None:
    with pytest.raises(FeatureValidationError, match="surprise"):
        validate_features({**VALID_ROW, "surprise": 1})


def test_validate_rejects_none() -> None:
    with pytest.raises(FeatureValidationError, match="must not be None"):
        validate_features({**VALID_ROW, "hub": None})


def test_validate_rejects_a_non_string_category() -> None:
    with pytest.raises(FeatureValidationError, match="must be a string"):
        validate_features({**VALID_ROW, "route": 123})


def test_validate_rejects_a_non_numeric_value() -> None:
    with pytest.raises(FeatureValidationError, match="must be numeric"):
        validate_features({**VALID_ROW, "congestion_index": "high"})


def test_validate_coerces_bool_weather_flag() -> None:
    assert validate_features({**VALID_ROW, "weather_flag": True})["weather_flag"] == 1.0


def test_validate_coerces_ints_to_float() -> None:
    assert isinstance(validate_features(VALID_ROW)["hour_of_day"], float)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0.0, 0.0), (1.0, 1.0), (0.5, 0.5), (-0.001, 0.0), (1.001, 1.0)],
)
def test_clamp_probability_bounds(raw, expected) -> None:
    assert clamp_probability(raw) == expected


def test_clamp_probability_rejects_nan() -> None:
    with pytest.raises(ValueError, match="NaN"):
        clamp_probability(float("nan"))


def test_build_features_composes_the_route_code() -> None:
    features = build_features(origin_code="DEL", dest_code="BOM")
    assert features.route == "DEL-BOM"
    assert features.hub == "DEL"
    assert features.sorting_method == "unknown"


def test_build_features_uses_current_hub_when_given() -> None:
    features = build_features(
        origin_code="DEL", dest_code="BOM", current_hub_code="BLR"
    )
    assert features.hub == "BLR"


def test_build_features_maps_vehicle_type_to_carrier() -> None:
    owned = build_features(origin_code="A", dest_code="B", vehicle_type="OWNED")
    third = build_features(origin_code="A", dest_code="B", vehicle_type="THIRD_PARTY")
    assert owned.carrier == "road"
    assert third.carrier == "multi"


def test_build_features_takes_hour_from_the_timestamp() -> None:
    from datetime import datetime

    features = build_features(
        origin_code="A", dest_code="B", at=datetime(2026, 5, 1, 17, 30)
    )
    assert features.hour_of_day == 17
