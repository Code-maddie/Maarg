"""Input and feature validation for E1 Misplacement Classifier."""

from typing import Dict, Any, List, Union
import numpy as np
import pandas as pd


REQUIRED_FEATURE_COLUMNS = [
    "route",
    "hub",
    "carrier",
    "congestion_index",
    "num_handoffs",
    "sorting_method",
    "weather_flag",
    "hour_of_day"
]

CATEGORICAL_FEATURES = ["route", "hub", "carrier", "sorting_method"]
NUMERIC_FEATURES = ["congestion_index", "num_handoffs", "weather_flag", "hour_of_day"]


class ValidationError(ValueError):
    """Raised when an input fails E1 validation contracts."""
    pass


def validate_inference_input(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates a single inference feature dictionary against the E1 contract.
    Returns cleaned feature dict or raises ValidationError.
    """
    if not isinstance(features, dict):
        raise ValidationError(f"Expected input to be a dictionary, got {type(features).__name__}")

    # Check for missing required columns
    missing = [col for col in REQUIRED_FEATURE_COLUMNS if col not in features]
    if missing:
        raise ValidationError(f"Missing required features: {missing}")

    validated = {}

    # Validate Categoricals
    for cat_col in CATEGORICAL_FEATURES:
        val = features[cat_col]
        if val is None or (isinstance(val, float) and np.isnan(val)):
            raise ValidationError(f"Categorical feature '{cat_col}' cannot be null/NaN.")
        validated[cat_col] = str(val).strip()
        if not validated[cat_col]:
            raise ValidationError(f"Categorical feature '{cat_col}' cannot be empty string.")

    # Validate congestion_index
    cong = features["congestion_index"]
    try:
        cong = float(cong)
    except (ValueError, TypeError):
        raise ValidationError(f"'congestion_index' must be a numeric float, got {cong}")
    if np.isnan(cong) or np.isinf(cong):
        raise ValidationError(f"'congestion_index' cannot be NaN or Inf.")
    if not (0.0 <= cong <= 1.0):
        raise ValidationError(f"'congestion_index' must be between 0.0 and 1.0, got {cong}")
    validated["congestion_index"] = cong

    # Validate num_handoffs
    handoffs = features["num_handoffs"]
    try:
        handoffs = int(handoffs)
    except (ValueError, TypeError):
        raise ValidationError(f"'num_handoffs' must be an integer, got {handoffs}")
    if handoffs < 0:
        raise ValidationError(f"'num_handoffs' must be non-negative, got {handoffs}")
    validated["num_handoffs"] = handoffs

    # Validate weather_flag
    weather = features["weather_flag"]
    try:
        weather = int(weather)
    except (ValueError, TypeError):
        raise ValidationError(f"'weather_flag' must be 0 or 1, got {weather}")
    if weather not in (0, 1):
        raise ValidationError(f"'weather_flag' must be 0 or 1, got {weather}")
    validated["weather_flag"] = weather

    # Validate hour_of_day
    hour = features["hour_of_day"]
    try:
        hour = int(hour)
    except (ValueError, TypeError):
        raise ValidationError(f"'hour_of_day' must be an integer, got {hour}")
    if not (0 <= hour <= 23):
        raise ValidationError(f"'hour_of_day' must be between 0 and 23, got {hour}")
    validated["hour_of_day"] = hour

    return validated


def validate_feature_dataframe(df: pd.DataFrame, is_training: bool = False) -> pd.DataFrame:
    """
    Validates a pandas DataFrame against the E1 feature schema.
    Checks column presence, non-nullity, finite numeric ranges, and target values.
    """
    if not isinstance(df, pd.DataFrame):
        raise ValidationError(f"Expected pandas DataFrame, got {type(df).__name__}")

    required_cols = list(REQUIRED_FEATURE_COLUMNS)
    if is_training:
        required_cols.append("misplaced")

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValidationError(f"DataFrame is missing required columns: {missing}")

    # Check for NaN / Inf
    for col in required_cols:
        if df[col].isna().any():
            raise ValidationError(f"Column '{col}' contains NaN values.")

    for num_col in NUMERIC_FEATURES:
        if np.isinf(df[num_col]).any():
            raise ValidationError(f"Column '{num_col}' contains infinite values.")

    # Check value ranges
    if (df["congestion_index"] < 0.0).any() or (df["congestion_index"] > 1.0).any():
        raise ValidationError("Found 'congestion_index' values outside [0.0, 1.0].")

    if (df["num_handoffs"] < 0).any():
        raise ValidationError("Found negative 'num_handoffs' values.")

    if not df["weather_flag"].isin([0, 1]).all():
        raise ValidationError("Found 'weather_flag' values other than 0 or 1.")

    if (df["hour_of_day"] < 0).any() or (df["hour_of_day"] > 23).any():
        raise ValidationError("Found 'hour_of_day' values outside [0, 23].")

    if is_training:
        if not df["misplaced"].isin([0, 1]).all():
            raise ValidationError("Found 'misplaced' target values other than 0 or 1.")

    return df


def validate_probability_output(proba: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    """Validates that model predicted probability is strictly bounded in [0.0, 1.0]."""
    if isinstance(proba, (float, int, np.floating)):
        if np.isnan(proba) or np.isinf(proba):
            raise ValidationError(f"Predicted probability is NaN or Inf: {proba}")
        if not (0.0 <= proba <= 1.0):
            raise ValidationError(f"Predicted probability out of bounds [0, 1]: {proba}")
        return float(proba)
    elif isinstance(proba, np.ndarray):
        if np.isnan(proba).any() or np.isinf(proba).any():
            raise ValidationError("Predicted probabilities array contains NaN or Inf.")
        if (proba < 0.0).any() or (proba > 1.0).any():
            raise ValidationError("Predicted probabilities array contains values outside [0, 1].")
        return proba
    else:
        raise ValidationError(f"Unexpected probability type: {type(proba).__name__}")
