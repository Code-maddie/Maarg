"""Phase 3 validation: the E1 ModelRegistry against the real artifacts.

These load the real serving artifact once per session. They are marked
`slow` so they can be deselected with `-m "not slow"`.
"""

import math
from pathlib import Path

import pytest

from app.core.config import settings
from app.engines.e1_misplacement.features import FeatureValidationError
from app.engines.e1_misplacement.registry import (
    ModelNotReadyError,
    ModelRegistry,
    ModelState,
)
from app.engines.e1_misplacement.service import E1Service, build_features

pytestmark = pytest.mark.slow

# Values drawn from the real training vocabulary, so the one-hot encoder sees
# known categories rather than falling back to all-zeros.
REAL_ROW = {
    "route": "R000",
    "hub": "F000",
    "carrier": "air",
    "congestion_index": 0.42,
    "num_handoffs": 3,
    "sorting_method": "unknown",
    "weather_flag": 0,
    "hour_of_day": 17,
}


@pytest.fixture(scope="session")
def registry() -> ModelRegistry:
    """Loads the real artifacts once for the whole session."""
    instance = ModelRegistry()
    instance.load()
    return instance


# --- loading -------------------------------------------------------------

def test_artifacts_exist_on_disk() -> None:
    artifact_dir: Path = settings.e1_artifact_path
    assert (artifact_dir / "model.pkl").exists()
    assert (artifact_dir / "feature_pipeline.joblib").exists()


def test_registry_loads(registry: ModelRegistry) -> None:
    status = registry.status()
    assert status.state is ModelState.LOADED
    assert status.model_loaded is True
    assert status.model_class == "RandomForestClassifier"
    assert status.version == settings.e1_model_version


def test_status_reports_training_provenance(registry: ModelRegistry) -> None:
    status = registry.status()
    assert status.sklearn_version == "1.9.0"
    assert status.trained_at is not None
    assert "test" in status.metrics


def test_missing_artifacts_fail_clearly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="E1 artifact not found"):
        ModelRegistry(artifact_dir=tmp_path).load()


def test_background_load_failure_is_recorded_not_raised(tmp_path: Path) -> None:
    """A broken artifact must degrade the service, never crash startup."""
    broken = ModelRegistry(artifact_dir=tmp_path)
    broken.start_background_load()
    broken._thread.join(timeout=30)  # noqa: SLF001 - deterministic in test

    status = broken.status()
    assert status.state is ModelState.FAILED
    assert status.model_loaded is False
    assert "FileNotFoundError" in (status.error or "")


def test_predicting_before_load_raises_not_ready(tmp_path: Path) -> None:
    unloaded = ModelRegistry(artifact_dir=tmp_path)
    with pytest.raises(ModelNotReadyError):
        unloaded.predict(REAL_ROW)


# --- prediction ----------------------------------------------------------

def test_single_prediction_is_a_probability(registry: ModelRegistry) -> None:
    probability = registry.predict(REAL_ROW)
    assert isinstance(probability, float)
    assert 0.0 <= probability <= 1.0
    assert not math.isnan(probability)


def test_prediction_is_deterministic(registry: ModelRegistry) -> None:
    assert registry.predict(REAL_ROW) == registry.predict(REAL_ROW)


def test_batch_matches_single_predictions(registry: ModelRegistry) -> None:
    rows = [REAL_ROW, {**REAL_ROW, "hour_of_day": 3, "congestion_index": 0.1}]
    batch = registry.predict_batch(rows)

    assert len(batch) == 2
    assert batch[0] == pytest.approx(registry.predict(rows[0]))
    assert batch[1] == pytest.approx(registry.predict(rows[1]))


def test_empty_batch_returns_empty(registry: ModelRegistry) -> None:
    assert registry.predict_batch([]) == []


def test_all_batch_probabilities_are_bounded(registry: ModelRegistry) -> None:
    rows = [
        {**REAL_ROW, "hour_of_day": hour, "congestion_index": hour / 24}
        for hour in range(24)
    ]
    probabilities = registry.predict_batch(rows)

    assert len(probabilities) == 24
    assert all(0.0 <= p <= 1.0 for p in probabilities)


def test_features_actually_move_the_output(registry: ModelRegistry) -> None:
    """Guards against a pipeline that silently maps everything to one value."""
    rows = [
        {**REAL_ROW, "route": f"R{i:03d}", "hub": f"F{i:03d}", "num_handoffs": i % 7}
        for i in range(40)
    ]
    probabilities = registry.predict_batch(rows)
    assert len(set(probabilities)) > 1


def test_unknown_categories_do_not_crash(registry: ModelRegistry) -> None:
    """The simulator will emit hub/route codes outside the training vocabulary."""
    probability = registry.predict(
        {**REAL_ROW, "route": "DEL-BOM", "hub": "DEL", "carrier": "spaceship"}
    )
    assert 0.0 <= probability <= 1.0


def test_missing_feature_is_rejected(registry: ModelRegistry) -> None:
    with pytest.raises(FeatureValidationError):
        registry.predict({k: v for k, v in REAL_ROW.items() if k != "hub"})


def test_reload_keeps_the_model_available(registry: ModelRegistry) -> None:
    before = registry.predict(REAL_ROW)
    status = registry.reload()
    assert status.model_loaded is True
    assert registry.predict(REAL_ROW) == pytest.approx(before)


# --- service façade ------------------------------------------------------

def test_service_scores_built_features(registry: ModelRegistry) -> None:
    service = E1Service(registry=registry)
    probability = service.score(
        build_features(origin_code="DEL", dest_code="BOM", num_handoffs=2)
    )
    assert 0.0 <= probability <= 1.0


def test_service_batch_scoring(registry: ModelRegistry) -> None:
    service = E1Service(registry=registry)
    rows = [
        build_features(origin_code="DEL", dest_code="BOM", num_handoffs=n)
        for n in range(5)
    ]
    probabilities = service.score_many(rows)

    assert len(probabilities) == 5
    assert all(0.0 <= p <= 1.0 for p in probabilities)
