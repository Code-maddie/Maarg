"""Request/response schemas for the model registry endpoints."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.engines.e1_misplacement.features import (
    SORTING_METHOD_PLACEHOLDER,
)


class ModelStatusResponse(BaseModel):
    """Active model version and metrics — SH.docx §9 `GET /model/status`."""

    state: str = Field(..., description="unloaded | loading | loaded | failed")
    model_loaded: bool
    name: str
    version: Optional[str] = None
    model_class: Optional[str] = None
    feature_names: List[str]
    metrics: Dict[str, Any] = Field(default_factory=dict)
    trained_at: Optional[str] = None
    sklearn_version: Optional[str] = None
    load_seconds: Optional[float] = None
    error: Optional[str] = None

    # The field names start with "model_", which pydantic otherwise reserves.
    model_config = ConfigDict(protected_namespaces=())


class PredictionRequest(BaseModel):
    """One E1 feature row. Field names and order follow the artifact."""

    route: str = Field(..., examples=["R000"])
    hub: str = Field(..., examples=["F000"])
    carrier: str = Field(..., examples=["air"])
    congestion_index: float = Field(..., examples=[0.42])
    num_handoffs: int = Field(..., ge=0, examples=[3])
    weather_flag: int = Field(..., ge=0, le=1, examples=[0])
    hour_of_day: int = Field(..., ge=0, le=23, examples=[17])
    sorting_method: str = Field(
        default=SORTING_METHOD_PLACEHOLDER, examples=[SORTING_METHOD_PLACEHOLDER]
    )


class PredictionResponse(BaseModel):
    """P(misplace) for one shipment-leg."""

    p_misplace: float = Field(..., ge=0.0, le=1.0)
    model_version: Optional[str] = None

    model_config = ConfigDict(protected_namespaces=())


class BatchPredictionRequest(BaseModel):
    rows: List[PredictionRequest] = Field(..., min_length=1, max_length=1000)


class BatchPredictionResponse(BaseModel):
    probabilities: List[float]
    count: int
    model_version: Optional[str] = None

    model_config = ConfigDict(protected_namespaces=())
