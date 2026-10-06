"""Serving and inference functions for E1 Misplacement Classifier."""

import os
import pickle
import joblib
from typing import Dict, Any, List, Union
import numpy as np
import pandas as pd

from src.features.validator import (
    REQUIRED_FEATURE_COLUMNS,
    validate_inference_input,
    validate_probability_output
)


DEFAULT_MODEL_PATH = "artifacts/misplacement_classifier/v1/model.pkl"
DEFAULT_PIPELINE_PATH = "artifacts/misplacement_classifier/v1/feature_pipeline.joblib"


class E1ModelService:
    """Singleton-style service wrapping the serialized model and preprocessor."""

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        pipeline_path: str = DEFAULT_PIPELINE_PATH
    ):
        self.model_path = model_path
        self.pipeline_path = pipeline_path
        self.model = None
        self.pipeline = None
        self.load()

    def load(self) -> None:
        """Loads model and preprocessing artifacts from disk."""
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model artifact not found at {self.model_path}")
        if not os.path.exists(self.pipeline_path):
            raise FileNotFoundError(f"Feature pipeline artifact not found at {self.pipeline_path}")

        with open(self.model_path, "rb") as f:
            self.model = pickle.load(f)

        self.pipeline = joblib.load(self.pipeline_path)

    def predict_one(self, features: Dict[str, Any]) -> float:
        """
        Validates input dict, constructs single-row DataFrame with strict ordering,
        transforms through feature pipeline, and predicts probability P(misplaced).
        """
        validated = validate_inference_input(features)
        df_input = pd.DataFrame([validated], columns=REQUIRED_FEATURE_COLUMNS)
        
        X_trans = self.pipeline.transform(df_input)
        probs = self.model.predict_proba(X_trans)
        prob = float(probs[0, 1])
        
        return validate_probability_output(prob)

    def predict_batch(self, records: Union[List[Dict[str, Any]], pd.DataFrame]) -> np.ndarray:
        """
        Predicts probabilities for a batch of records.
        """
        if isinstance(records, pd.DataFrame):
            df_input = records.copy()
        elif isinstance(records, list):
            validated_records = [validate_inference_input(r) for r in records]
            df_input = pd.DataFrame(validated_records, columns=REQUIRED_FEATURE_COLUMNS)
        else:
            raise TypeError(f"Unsupported batch input type: {type(records).__name__}")

        # Ensure required ordering
        df_ordered = df_input[REQUIRED_FEATURE_COLUMNS]
        X_trans = self.pipeline.transform(df_ordered)
        probs = self.model.predict_proba(X_trans)[:, 1]

        return validate_probability_output(probs)


# Global service cache
_SERVICE_INSTANCE = None


def get_service(
    model_path: str = DEFAULT_MODEL_PATH,
    pipeline_path: str = DEFAULT_PIPELINE_PATH
) -> E1ModelService:
    """Returns or initializes the cached E1ModelService."""
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = E1ModelService(model_path, pipeline_path)
    return _SERVICE_INSTANCE


def predict_misplacement_probability(
    features: Dict[str, Any],
    model_path: str = DEFAULT_MODEL_PATH,
    pipeline_path: str = DEFAULT_PIPELINE_PATH
) -> float:
    """
    Production-ready inference function matching E1 serving contract:
      predict_misplacement_probability(features: dict) -> float
    Returns P(misplace) bounded strictly in [0.0, 1.0].
    """
    service = get_service(model_path, pipeline_path)
    return service.predict_one(features)


def predict_batch_probabilities(
    records: Union[List[Dict[str, Any]], pd.DataFrame],
    model_path: str = DEFAULT_MODEL_PATH,
    pipeline_path: str = DEFAULT_PIPELINE_PATH
) -> np.ndarray:
    """Batch prediction returning 1D numpy array of probabilities."""
    service = get_service(model_path, pipeline_path)
    return service.predict_batch(records)
