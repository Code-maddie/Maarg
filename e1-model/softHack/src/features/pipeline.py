"""Preprocessing pipeline for E1 Misplacement Classifier."""

import os
import json
import joblib
import pandas as pd
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from typing import Tuple, List, Dict, Any

from src.features.validator import (
    REQUIRED_FEATURE_COLUMNS,
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    validate_feature_dataframe
)


def build_feature_pipeline() -> ColumnTransformer:
    """
    Constructs the standard sklearn ColumnTransformer for E1:
    - Categorical features: OneHotEncoder(handle_unknown='ignore', sparse_output=False)
    - Numeric features: StandardScaler()
    """
    categorical_transformer = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    numeric_transformer = StandardScaler()

    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", categorical_transformer, CATEGORICAL_FEATURES),
            ("num", numeric_transformer, NUMERIC_FEATURES)
        ],
        remainder="drop",
        verbose_feature_names_out=True
    )
    return preprocessor


def export_feature_schema(
    preprocessor: ColumnTransformer,
    output_path: str = "artifacts/misplacement_classifier/v1/feature_schema.json"
) -> Dict[str, Any]:
    """Exports the exact feature schema and transformer configuration to a JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cat_encoder: OneHotEncoder = preprocessor.named_transformers_["cat"]
    num_scaler: StandardScaler = preprocessor.named_transformers_["num"]

    feature_names_out = preprocessor.get_feature_names_out().tolist()

    schema = {
        "model_name": "misplacement_classifier",
        "version": "v1",
        "expected_input_features": REQUIRED_FEATURE_COLUMNS,
        "feature_ordering": REQUIRED_FEATURE_COLUMNS,
        "categorical_features": CATEGORICAL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "target_column": "misplaced",
        "num_transformed_features": len(feature_names_out),
        "transformed_feature_names": feature_names_out,
        "categorical_categories": {
            col: [str(c) for c in cat_encoder.categories_[i]]
            for i, col in enumerate(CATEGORICAL_FEATURES)
        },
        "numeric_scaler_stats": {
            col: {
                "mean": float(num_scaler.mean_[i]),
                "scale": float(num_scaler.scale_[i]),
                "var": float(num_scaler.var_[i])
            }
            for i, col in enumerate(NUMERIC_FEATURES)
        },
        "validation_constraints": {
            "route": {"type": "string", "nullable": False},
            "hub": {"type": "string", "nullable": False},
            "carrier": {"type": "string", "nullable": False},
            "congestion_index": {"type": "float", "min": 0.0, "max": 1.0, "nullable": False},
            "num_handoffs": {"type": "int", "min": 0, "nullable": False},
            "sorting_method": {"type": "string", "default": "unknown", "nullable": False},
            "weather_flag": {"type": "int", "allowed_values": [0, 1], "nullable": False},
            "hour_of_day": {"type": "int", "min": 0, "max": 23, "nullable": False}
        }
    }

    with open(output_path, "w") as f:
        json.dump(schema, f, indent=2)

    print(f"Feature schema exported to {output_path}")
    return schema


def save_pipeline(
    preprocessor: ColumnTransformer,
    output_path: str = "artifacts/misplacement_classifier/v1/feature_pipeline.joblib"
) -> None:
    """Serializes the fitted feature pipeline to disk."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    joblib.dump(preprocessor, output_path)
    print(f"Fitted feature pipeline saved to {output_path}")


def load_pipeline(
    pipeline_path: str = "artifacts/misplacement_classifier/v1/feature_pipeline.joblib"
) -> ColumnTransformer:
    """Loads a serialized feature pipeline from disk."""
    if not os.path.exists(pipeline_path):
        raise FileNotFoundError(f"Feature pipeline artifact not found at {pipeline_path}")
    return joblib.load(pipeline_path)
