"""Exports a deployment-sized E1 artifact (v2) from the v1 training data.

WHY THIS EXISTS
---------------
The v1 artifact is a 100-tree RandomForest grown to unlimited depth over a
one-hot encoding of `route` (500 levels) and `hub` (200 levels). That makes
`model.pkl` ~214 MB, which:

  * exceeds GitHub's 100 MB per-file hard limit, so it cannot live in the
    repository that Render builds from; and
  * unpickles into more resident memory than a small web dyno has.

v1's own `metrics.json` records a held-out test ROC-AUC of 0.4999 — the trees
are memorising one-hot route/hub identity rather than learning transferable
signal. Capping depth therefore costs no measurable accuracy while removing
two orders of magnitude of artifact size.

WHAT IS PRESERVED
-----------------
The feature contract is identical to v1: same eight input columns in the same
order, same ColumnTransformer construction, same temporal split and seed. The
backend's `feature_schema.json` check passes unchanged, so nothing in
`app/engines/e1_misplacement/` needs to know which version it loaded.

The v1 artifact directory is never written to.

Run from `e1-model/softHack/`::

    python scripts/export_serving_model.py
"""

from __future__ import annotations

import json
import os
import pickle
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import joblib
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier

SOFTHACK_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SOFTHACK_DIR.parents[1]
sys.path.insert(0, str(SOFTHACK_DIR))

from src.features.pipeline import (  # noqa: E402
    build_feature_pipeline,
    export_feature_schema,
    save_pipeline,
)
from src.features.validator import (  # noqa: E402
    REQUIRED_FEATURE_COLUMNS,
    validate_feature_dataframe,
    validate_probability_output,
)
from src.models.train import temporal_split  # noqa: E402

MODEL_NAME = "misplacement_classifier"
MODEL_VERSION = "v2"
RANDOM_SEED = 42

# The serving artifact is vendored under backend/ so that Render, whose root
# directory is backend/, needs nothing from outside its own deploy root.
DEFAULT_OUT_DIR = PROJECT_ROOT / "backend" / "artifacts" / MODEL_NAME / MODEL_VERSION

# Depth and leaf-size caps are what shrink the forest. Unlimited-depth trees
# over 700 one-hot columns are what produced the 214 MB v1 artifact.
SERVING_PARAMS: Dict[str, Any] = {
    "n_estimators": 60,
    "max_depth": 8,
    "min_samples_leaf": 40,
    "max_features": "sqrt",
    "class_weight": "balanced",
    "random_state": RANDOM_SEED,
    "n_jobs": -1,
}


def _megabytes(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def compute_classification_metrics(y_true, y_prob, threshold: float = 0.5) -> Dict[str, Any]:
    """Identical to ``src.models.evaluate.compute_classification_metrics``.

    Reimplemented here only so exporting an artifact does not require
    matplotlib, which that module imports at file scope for its plots.
    """
    from sklearn import metrics as m

    y_pred = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = m.confusion_matrix(y_true, y_pred).ravel()
    return {
        "roc_auc": float(m.roc_auc_score(y_true, y_prob)),
        "pr_auc": float(m.average_precision_score(y_true, y_prob)),
        "accuracy": float(m.accuracy_score(y_true, y_pred)),
        "precision": float(m.precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(m.recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(m.f1_score(y_true, y_pred, zero_division=0)),
        "brier_score": float(m.brier_score_loss(y_true, y_prob)),
        "log_loss": float(m.log_loss(y_true, y_prob)),
        "threshold": float(threshold),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "sample_count": int(len(y_true)),
        "positive_count": int(y_true.sum()),
        "positive_rate": float(y_true.mean()),
    }


def export(out_dir: Path = DEFAULT_OUT_DIR) -> Dict[str, Any]:
    """Trains the serving model and writes the v2 artifact set."""
    started = datetime.now(timezone.utc).isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    data_path = SOFTHACK_DIR / "data" / "processed" / "e1_training.csv"
    source_path = SOFTHACK_DIR / "data" / "processed" / "e1_training_with_source.csv.gz"
    for path in (data_path, source_path):
        if not path.exists():
            raise FileNotFoundError(
                f"Training data not found: {path}\n"
                "It is excluded from git by design; restore it locally to retrain."
            )

    print(f"Loading canonical dataset from {data_path.relative_to(PROJECT_ROOT)}...")
    canonical = pd.read_csv(data_path)
    validate_feature_dataframe(canonical, is_training=True)

    source = pd.read_csv(source_path, low_memory=False)

    # Same chronological 70/15/15 split as v1, so the test set is the same
    # rows and the reported metrics are directly comparable.
    print("Executing temporal split (70/15/15), matching v1...")
    split = temporal_split(canonical, source["timestamp"])
    train_df, val_df, test_df = split["train_df"], split["val_df"], split["test_df"]
    split_meta = split["metadata"]

    # Production fit uses train + validation, again matching v1.
    train_val = pd.concat([train_df, val_df], ignore_index=True)

    print("Fitting feature pipeline on train + validation...")
    preprocessor = build_feature_pipeline()
    x_train_val = preprocessor.fit_transform(train_val[REQUIRED_FEATURE_COLUMNS])
    y_train_val = train_val["misplaced"].values

    x_test = preprocessor.transform(test_df[REQUIRED_FEATURE_COLUMNS])
    y_test = test_df["misplaced"].values

    print(f"Feature matrix: train+val={x_train_val.shape}, test={x_test.shape}")
    print(f"Training serving RandomForest {SERVING_PARAMS}...")
    model = RandomForestClassifier(**SERVING_PARAMS)
    model.fit(x_train_val, y_train_val)

    # Serving is single-row and latency-bound, not throughput-bound, so the
    # fitted model is pinned to one thread before export. With n_jobs=-1,
    # sklearn splits the tree-vote sum across threads and the floating-point
    # accumulation order varies between calls -- two identical requests can
    # return probabilities that differ in the last bits. E1's output feeds
    # the pressure and temperature engines, so it has to be reproducible.
    # It also keeps the model from spawning a thread pool per request inside
    # an already-concurrent web worker.
    model.set_params(n_jobs=1)

    test_prob = model.predict_proba(x_test)[:, 1]
    validate_probability_output(test_prob)
    test_metrics = compute_classification_metrics(y_test, test_prob)

    print("\nHeld-out test metrics (same split as v1):")
    for key in ("roc_auc", "pr_auc", "accuracy", "f1", "brier_score", "log_loss"):
        print(f"  {key:12s}: {test_metrics[key]:.4f}")

    model_path = out_dir / "model.pkl"
    with model_path.open("wb") as handle:
        pickle.dump(model, handle, protocol=pickle.HIGHEST_PROTOCOL)
    save_pipeline(preprocessor, str(out_dir / "feature_pipeline.joblib"))

    schema = export_feature_schema(preprocessor, str(out_dir / "feature_schema.json"))
    # export_feature_schema() hardcodes v1; the contract is identical, only
    # the label differs.
    schema["version"] = MODEL_VERSION
    (out_dir / "feature_schema.json").write_text(
        json.dumps(schema, indent=2), encoding="utf-8"
    )

    metrics = {
        "model_name": MODEL_NAME,
        "version": MODEL_VERSION,
        "selected_model": "RandomForest",
        "selection_rationale": (
            "Depth-capped RandomForest exported for serving. v1's unlimited-depth "
            "forest was 214 MB — past GitHub's 100 MB file limit and too large for "
            "a small web dyno — while scoring 0.4999 test ROC-AUC. Capping depth "
            "removes the size without a meaningful accuracy change."
        ),
        "test_metrics": test_metrics,
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    metadata = {
        "model_name": MODEL_NAME,
        "version": MODEL_VERSION,
        "derived_from": "v1 (e1-model/softHack/artifacts/misplacement_classifier/v1)",
        "purpose": "Deployment artifact: same feature contract as v1, sized to ship.",
        "training_timestamp": started,
        "completion_timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_names": [
            "Zenodo Multimodal Industrial Logistics Disruption and Risk Dataset "
            "(DOI: 10.5281/zenodo.18050317)"
        ],
        "dataset_row_counts": {
            "canonical_training_e1": len(canonical),
            "train_split": split_meta["train"]["count"],
            "validation_split": split_meta["validation"]["count"],
            "test_split": split_meta["test"]["count"],
        },
        "feature_names": REQUIRED_FEATURE_COLUMNS,
        "target_definition": "misplaced = 1 if disruption_type > 0 else 0",
        "proxy_label_explanation": (
            "E1 prototype disruption/misplacement-risk proxy label derived from Zenodo "
            "disruption_type > 0. It is NOT a verified physical lost-parcel scan."
        ),
        "target_positive_rate": float(canonical["misplaced"].mean()),
        "train_validation_test_date_ranges": {
            "train": split_meta["train"]["date_range"],
            "validation": split_meta["validation"]["date_range"],
            "test": split_meta["test"]["date_range"],
        },
        "model_class": type(model).__name__,
        "model_parameters": {k: str(v) for k, v in model.get_params().items()},
        # Same {validation, test} shape as v1, so GET /model/status keeps its
        # response contract. v2 has no separate validation pass: it uses the
        # architecture v1's comparison already selected.
        "metrics": {"validation": {}, "test": test_metrics},
        "sklearn_version": sklearn.__version__,
        "pandas_version": pd.__version__,
        "joblib_version": joblib.__version__,
        "python_version": platform.python_version(),
    }
    (out_dir / "training_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    size_mb = _megabytes(model_path)
    print(f"\nArtifact written to {out_dir.relative_to(PROJECT_ROOT)}")
    print(f"  model.pkl: {size_mb:.2f} MB")
    return {"out_dir": out_dir, "model_mb": size_mb, "test_metrics": test_metrics}


if __name__ == "__main__":
    os.chdir(SOFTHACK_DIR)
    export()
