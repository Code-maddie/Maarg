"""Model registry routes — SH.docx §9 "ML / Model registry".

`POST /model/reload` is admin-only and audited, per SH.docx §9 and §12.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import CurrentUser, require_role
from app.models import AuditLog
from app.models.enums import AuditAction, UserRole

from app.engines.e1_misplacement.features import FeatureValidationError
from app.engines.e1_misplacement.registry import (
    ModelNotReadyError,
    get_registry,
)
from app.schemas.model import (
    BatchPredictionRequest,
    BatchPredictionResponse,
    ModelStatusResponse,
    PredictionRequest,
    PredictionResponse,
)

router = APIRouter(prefix="/model", tags=["model"])


@router.get("/status", response_model=ModelStatusResponse, summary="Active model")
def model_status() -> ModelStatusResponse:
    """Reports the active E1 version, its metrics and load state."""
    snapshot = asdict(get_registry().status())
    snapshot["state"] = str(snapshot["state"])
    snapshot.pop("artifact_dir", None)  # filesystem layout is not public
    return ModelStatusResponse(**snapshot)


@router.post("/reload", response_model=ModelStatusResponse, summary="Hot-swap model")
def model_reload(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
) -> ModelStatusResponse:
    """Re-reads the artifacts from disk without restarting the service."""
    try:
        get_registry().reload()
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"E1 reload failed: {exc}",
        ) from exc

    db.add(
        AuditLog(
            actor_user_id=user.db_user_id,
            action=AuditAction.RELOAD_MODEL.value,
            target_type="ModelArtifact",
            reason_text=f"E1 hot-reloaded ({get_registry().status().version})",
        )
    )
    db.commit()
    return model_status()


@router.post("/predict", response_model=PredictionResponse, summary="Score one row")
def predict(payload: PredictionRequest) -> PredictionResponse:
    """Returns P(misplace) for a single shipment-leg feature row."""
    registry = get_registry()
    try:
        probability = registry.predict(payload.model_dump())
    except ModelNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except FeatureValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return PredictionResponse(
        p_misplace=probability, model_version=registry.status().version
    )


@router.post(
    "/predict/batch",
    response_model=BatchPredictionResponse,
    summary="Score many rows",
)
def predict_batch(payload: BatchPredictionRequest) -> BatchPredictionResponse:
    """Vectorised scoring — one pipeline pass for the whole batch."""
    registry = get_registry()
    try:
        probabilities = registry.predict_batch(
            [row.model_dump() for row in payload.rows]
        )
    except ModelNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except FeatureValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return BatchPredictionResponse(
        probabilities=probabilities,
        count=len(probabilities),
        model_version=registry.status().version,
    )
