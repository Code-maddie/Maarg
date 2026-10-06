"""E1 Model Registry — loads and serves the trained misplacement classifier.

Implements the registry described in SH.docx §10.3: artifacts are produced
offline (Colab), the backend only ever loads them, and `/model/reload`
hot-swaps a new version without a redeploy.

The artifacts under ``e1-model/`` are treated as strictly read-only.
"""

from __future__ import annotations

import json
import pickle
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings
from app.core.logging import get_logger
from app.engines.e1_misplacement.features import (
    FEATURE_ORDER,
    clamp_probability,
    validate_features,
)

logger = get_logger(__name__)

MODEL_FILENAME = "model.pkl"
PIPELINE_FILENAME = "feature_pipeline.joblib"
SCHEMA_FILENAME = "feature_schema.json"
METADATA_FILENAME = "training_metadata.json"


class ModelState(StrEnum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    FAILED = "failed"


class ModelNotReadyError(RuntimeError):
    """Raised when a prediction is requested before the model is available."""


@dataclass
class RegistryStatus:
    """Serializable snapshot of the registry, surfaced by /model/status."""

    state: ModelState = ModelState.UNLOADED
    model_loaded: bool = False
    name: str = "misplacement_classifier"
    version: Optional[str] = None
    model_class: Optional[str] = None
    artifact_dir: Optional[str] = None
    feature_names: List[str] = field(default_factory=lambda: list(FEATURE_ORDER))
    metrics: Dict[str, Any] = field(default_factory=dict)
    trained_at: Optional[str] = None
    sklearn_version: Optional[str] = None
    load_seconds: Optional[float] = None
    error: Optional[str] = None


class ModelRegistry:
    """Holds the active E1 model and preprocessing pipeline.

    Loading happens on a background thread: the API starts serving
    immediately and reports ``state="loading"`` until the artifacts are
    ready. A prediction issued during that window waits on the load event
    rather than failing. The serving artifact loads in well under a second,
    but keeping it off the request path means a larger one can be swapped in
    without changing the startup contract.
    """

    def __init__(self, artifact_dir: Optional[Path] = None) -> None:
        self._artifact_dir = Path(artifact_dir or settings.e1_artifact_path)
        self._model: Any = None
        self._pipeline: Any = None
        self._status = RegistryStatus(artifact_dir=str(self._artifact_dir))

        self._lock = threading.RLock()
        self._loaded_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # --- loading ---------------------------------------------------------

    def start_background_load(self) -> None:
        """Kicks off loading without blocking the caller."""
        with self._lock:
            if self._status.state is ModelState.LOADING:
                return
            self._status.state = ModelState.LOADING
            self._loaded_event.clear()

        self._thread = threading.Thread(
            target=self._load_safely, name="e1-model-loader", daemon=True
        )
        self._thread.start()

    def _load_safely(self) -> None:
        """Background entrypoint. Never raises — failure is recorded instead.

        A missing or corrupt artifact must degrade the service to
        ``model_loaded: false``, not prevent the backend from starting.
        """
        try:
            self.load()
        except Exception as exc:  # noqa: BLE001 - must not kill the thread
            with self._lock:
                self._status.state = ModelState.FAILED
                self._status.model_loaded = False
                self._status.error = f"{type(exc).__name__}: {exc}"
            logger.exception("E1 model load failed")
        finally:
            self._loaded_event.set()

    def load(self) -> None:
        """Loads artifacts from disk. Raises on failure."""
        started = time.perf_counter()

        model_path = self._artifact_dir / MODEL_FILENAME
        pipeline_path = self._artifact_dir / PIPELINE_FILENAME

        for path in (model_path, pipeline_path):
            if not path.exists():
                raise FileNotFoundError(f"E1 artifact not found: {path}")

        logger.info("Loading E1 artifacts from %s", self._artifact_dir)

        # joblib is imported lazily so the rest of the backend does not pay
        # the scikit-learn import cost when E1 is disabled.
        import joblib

        with model_path.open("rb") as handle:
            model = pickle.load(handle)
        pipeline = joblib.load(pipeline_path)

        metadata = self._read_json(METADATA_FILENAME)
        schema = self._read_json(SCHEMA_FILENAME)

        self._verify_schema(schema)

        elapsed = time.perf_counter() - started

        with self._lock:
            self._model = model
            self._pipeline = pipeline
            self._status = RegistryStatus(
                state=ModelState.LOADED,
                model_loaded=True,
                name=metadata.get("model_name", "misplacement_classifier"),
                version=metadata.get("version", settings.e1_model_version),
                model_class=type(model).__name__,
                artifact_dir=str(self._artifact_dir),
                feature_names=list(FEATURE_ORDER),
                metrics=metadata.get("metrics", {}),
                trained_at=metadata.get("training_timestamp"),
                sklearn_version=metadata.get("sklearn_version"),
                load_seconds=round(elapsed, 2),
            )

        logger.info(
            "E1 loaded: %s %s (%s) in %.1fs",
            self._status.name,
            self._status.version,
            self._status.model_class,
            elapsed,
        )

    def reload(self) -> RegistryStatus:
        """Synchronously re-reads artifacts from disk (admin hot-swap)."""
        self.load()
        self._loaded_event.set()
        return self.status()

    def _read_json(self, filename: str) -> Dict[str, Any]:
        path = self._artifact_dir / filename
        if not path.exists():
            logger.warning("E1 metadata file missing: %s", path)
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("E1 metadata file is not valid JSON: %s", path)
            return {}

    def _verify_schema(self, schema: Dict[str, Any]) -> None:
        """Fails loudly if the artifact expects a different feature contract.

        Silent drift here would produce confidently wrong probabilities
        rather than an error, so it is checked at load time.
        """
        expected: Sequence[str] = schema.get("feature_ordering") or []
        if expected and tuple(expected) != FEATURE_ORDER:
            raise ValueError(
                "E1 artifact feature ordering does not match the code "
                f"contract.\n  artifact: {list(expected)}\n"
                f"  code:     {list(FEATURE_ORDER)}"
            )

    # --- inference -------------------------------------------------------

    def _await_ready(self) -> None:
        if self._status.state is ModelState.LOADED:
            return

        if self._status.state is ModelState.UNLOADED:
            raise ModelNotReadyError("E1 model has not been loaded")

        if not self._loaded_event.wait(settings.e1_load_timeout_seconds):
            raise ModelNotReadyError(
                f"E1 model still loading after "
                f"{settings.e1_load_timeout_seconds:.0f}s"
            )

        if self._status.state is not ModelState.LOADED:
            raise ModelNotReadyError(
                f"E1 model unavailable: {self._status.error or 'load failed'}"
            )

    def predict(self, features: Dict[str, Any]) -> float:
        """Returns calibrated P(misplace) in [0, 1] for one shipment-leg."""
        return self.predict_batch([features])[0]

    def predict_batch(self, rows: Sequence[Dict[str, Any]]) -> List[float]:
        """Vectorised prediction. Far cheaper than looping ``predict``."""
        if not rows:
            return []

        validated = [validate_features(row) for row in rows]
        self._await_ready()

        import pandas as pd

        frame = pd.DataFrame(validated, columns=list(FEATURE_ORDER))

        with self._lock:
            model, pipeline = self._model, self._pipeline

        transformed = pipeline.transform(frame)
        probabilities = model.predict_proba(transformed)[:, 1]

        return [clamp_probability(value) for value in probabilities]

    # --- introspection ---------------------------------------------------

    def status(self) -> RegistryStatus:
        with self._lock:
            return self._status

    @property
    def is_loaded(self) -> bool:
        return self._status.state is ModelState.LOADED


_registry: Optional[ModelRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> ModelRegistry:
    """Returns the process-wide registry, creating it on first use."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = ModelRegistry()
        return _registry


def reset_registry() -> None:
    """Drops the cached registry. Test-support only."""
    global _registry
    with _registry_lock:
        _registry = None
