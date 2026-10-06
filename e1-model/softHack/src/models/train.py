"""Model training, candidate evaluation, model selection, and artifact export for E1."""

import os
import sys
import json
import pickle
import joblib
import platform
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Tuple

import pandas as pd
import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier

from src.features.validator import (
    REQUIRED_FEATURE_COLUMNS,
    validate_feature_dataframe,
    validate_probability_output
)
from src.features.pipeline import (
    build_feature_pipeline,
    save_pipeline,
    export_feature_schema
)
from src.models.evaluate import (
    compute_classification_metrics,
    plot_and_save_curves
)


RANDOM_SEED = 42
MODEL_NAME = "misplacement_classifier"
MODEL_VERSION = "v1"


def get_file_checksum(file_path: str) -> str:
    """Computes SHA-256 checksum of a file if it exists."""
    if not os.path.exists(file_path):
        return "not_found"
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def temporal_split(
    canonical_df: pd.DataFrame,
    timestamp_series: pd.Series,
    train_frac: float = 0.70,
    val_frac: float = 0.15
) -> Dict[str, Any]:
    """
    Executes chronological temporal splitting:
    - 70% earliest records for training
    - 15% intermediate records for validation
    - 15% latest records for held-out testing
    """
    n_total = len(canonical_df)
    n_train = int(train_frac * n_total)
    n_val = int(val_frac * n_total)
    n_test = n_total - n_train - n_val

    df = canonical_df.copy()
    df["__timestamp__"] = pd.to_datetime(timestamp_series)
    df = df.sort_values("__timestamp__").reset_index(drop=True)

    train_df = df.iloc[:n_train].copy()
    val_df = df.iloc[n_train:n_train + n_val].copy()
    test_df = df.iloc[n_train + n_val:].copy()

    split_info = {
        "train": {
            "count": len(train_df),
            "date_range": [str(train_df["__timestamp__"].min()), str(train_df["__timestamp__"].max())],
            "positive_rate": float(train_df["misplaced"].mean()),
            "indices": (0, n_train)
        },
        "validation": {
            "count": len(val_df),
            "date_range": [str(val_df["__timestamp__"].min()), str(val_df["__timestamp__"].max())],
            "positive_rate": float(val_df["misplaced"].mean()),
            "indices": (n_train, n_train + n_val)
        },
        "test": {
            "count": len(test_df),
            "date_range": [str(test_df["__timestamp__"].min()), str(test_df["__timestamp__"].max())],
            "positive_rate": float(test_df["misplaced"].mean()),
            "indices": (n_train + n_val, n_total)
        }
    }

    train_clean = train_df.drop(columns=["__timestamp__"])
    val_clean = val_df.drop(columns=["__timestamp__"])
    test_clean = test_df.drop(columns=["__timestamp__"])

    return {
        "train_df": train_clean,
        "val_df": val_clean,
        "test_df": test_clean,
        "metadata": split_info
    }


def train_e1_pipeline(
    data_path: str = "data/processed/e1_training.csv",
    source_path: str = "data/processed/e1_training_with_source.csv.gz",
    artifact_dir: str = "artifacts/misplacement_classifier/v1",
    random_seed: int = RANDOM_SEED
) -> Dict[str, Any]:
    """
    Full end-to-end training, validation, selection, testing, and artifact export for E1.
    """
    start_time = datetime.now(timezone.utc).isoformat()
    os.makedirs(artifact_dir, exist_ok=True)

    print("=" * 60)
    print("E1 MISPLACEMENT CLASSIFIER: TRAINING PIPELINE")
    print("=" * 60)

    # 1. Load data
    print(f"Loading canonical dataset from {data_path}...")
    df_canonical = pd.read_csv(data_path)
    validate_feature_dataframe(df_canonical, is_training=True)

    # Load timestamp for temporal split
    df_source = pd.read_csv(source_path, low_memory=False)
    timestamp_series = df_source["timestamp"]

    # 2. Perform Temporal Split
    print("\nExecuting temporal split (70% train / 15% validation / 15% test)...")
    split_res = temporal_split(df_canonical, timestamp_series)
    train_df = split_res["train_df"]
    val_df = split_res["val_df"]
    test_df = split_res["test_df"]
    split_meta = split_res["metadata"]

    for split_name, meta in split_meta.items():
        print(f"  {split_name.capitalize():10s}: {meta['count']} records | {meta['date_range'][0]} to {meta['date_range'][1]} | Positive rate: {meta['positive_rate']:.4f}")

    # 3. Fit Preprocessing Pipeline strictly on Training split
    print("\nFitting feature pipeline on training set...")
    preprocessor = build_feature_pipeline()
    X_train = preprocessor.fit_transform(train_df[REQUIRED_FEATURE_COLUMNS])
    y_train = train_df["misplaced"].values

    X_val = preprocessor.transform(val_df[REQUIRED_FEATURE_COLUMNS])
    y_val = val_df["misplaced"].values

    X_test = preprocessor.transform(test_df[REQUIRED_FEATURE_COLUMNS])
    y_test = test_df["misplaced"].values

    print(f"Feature matrix dimensions: Train={X_train.shape}, Val={X_val.shape}, Test={X_test.shape}")

    # 4. Train and Evaluate Candidate Classifiers
    print("\nTraining candidate models...")
    candidates = {
        "LogisticRegression": LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            random_state=random_seed
        ),
        "HistGradientBoosting": HistGradientBoostingClassifier(
            class_weight="balanced",
            random_state=random_seed
        ),
        "RandomForest": RandomForestClassifier(
            n_estimators=100,
            class_weight="balanced",
            random_state=random_seed,
            n_jobs=-1
        )
    }

    validation_results = {}
    fitted_candidates = {}

    for name, clf in candidates.items():
        print(f"Fitting candidate: {name}...")
        clf.fit(X_train, y_train)
        fitted_candidates[name] = clf

        val_prob = clf.predict_proba(X_val)[:, 1]
        val_metrics = compute_classification_metrics(y_val, val_prob)
        validation_results[name] = val_metrics
        print(f"  [{name}] Validation Metrics:")
        print(f"    ROC-AUC: {val_metrics['roc_auc']:.4f} | PR-AUC: {val_metrics['pr_auc']:.4f} | F1: {val_metrics['f1']:.4f}")
        print(f"    Brier Score: {val_metrics['brier_score']:.4f} | Log Loss: {val_metrics['log_loss']:.4f} | Accuracy: {val_metrics['accuracy']:.4f}")

    # 5. Model Selection
    # Selection rule: Highest ROC-AUC with lower Brier score
    best_candidate_name = max(
        validation_results.keys(),
        key=lambda k: (validation_results[k]["roc_auc"], -validation_results[k]["brier_score"])
    )
    print(f"\nSelected best candidate: {best_candidate_name}")
    print(f"Selection rationale: Highest validation ROC-AUC ({validation_results[best_candidate_name]['roc_auc']:.4f}) and superior Brier probability score ({validation_results[best_candidate_name]['brier_score']:.4f}).")

    # 6. Fit Production Model using Train + Validation data (Temporal sequence preserved)
    print(f"\nTraining final production model ({best_candidate_name}) using combined train + validation data...")
    train_val_df = pd.concat([train_df, val_df], ignore_index=True)
    
    prod_preprocessor = build_feature_pipeline()
    X_train_val = prod_preprocessor.fit_transform(train_val_df[REQUIRED_FEATURE_COLUMNS])
    y_train_val = train_val_df["misplaced"].values

    X_test_prod = prod_preprocessor.transform(test_df[REQUIRED_FEATURE_COLUMNS])

    if best_candidate_name == "RandomForest":
        prod_model = RandomForestClassifier(
            n_estimators=100,
            class_weight="balanced",
            random_state=random_seed,
            n_jobs=-1
        )
    elif best_candidate_name == "HistGradientBoosting":
        prod_model = HistGradientBoostingClassifier(
            class_weight="balanced",
            random_state=random_seed
        )
    else:
        prod_model = LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            random_state=random_seed
        )

    prod_model.fit(X_train_val, y_train_val)

    # 7. Evaluate Selected Model Exactly ONCE on Held-out Test Set
    print("\nEvaluating final production model ONCE on held-out test set...")
    test_prob = prod_model.predict_proba(X_test_prod)[:, 1]
    validate_probability_output(test_prob)
    test_metrics = compute_classification_metrics(y_test, test_prob)

    print("Held-out Test Metrics:")
    print(f"  ROC-AUC:     {test_metrics['roc_auc']:.4f}")
    print(f"  PR-AUC:      {test_metrics['pr_auc']:.4f}")
    print(f"  Accuracy:    {test_metrics['accuracy']:.4f}")
    print(f"  Precision:   {test_metrics['precision']:.4f}")
    print(f"  Recall:      {test_metrics['recall']:.4f}")
    print(f"  F1 Score:    {test_metrics['f1']:.4f}")
    print(f"  Brier Score: {test_metrics['brier_score']:.4f}")
    print(f"  Log Loss:    {test_metrics['log_loss']:.4f}")
    print(f"  Confusion Matrix: {test_metrics['confusion_matrix']}")

    # 8. Generate and save diagnostic curves
    print("\nGenerating diagnostic curves for production model...")
    plot_paths = plot_and_save_curves(
        y_test,
        test_prob,
        output_dir=artifact_dir,
        model_name=f"E1 v1 ({best_candidate_name})"
    )

    # 9. Export Primary Artifacts
    model_pkl_path = os.path.join(artifact_dir, "model.pkl")
    pipeline_joblib_path = os.path.join(artifact_dir, "feature_pipeline.joblib")
    metrics_json_path = os.path.join(artifact_dir, "metrics.json")
    schema_json_path = os.path.join(artifact_dir, "feature_schema.json")
    metadata_json_path = os.path.join(artifact_dir, "training_metadata.json")

    print(f"\nExporting model to {model_pkl_path}...")
    with open(model_pkl_path, "wb") as f:
        pickle.dump(prod_model, f, protocol=pickle.HIGHEST_PROTOCOL)

    print(f"Exporting feature pipeline to {pipeline_joblib_path}...")
    save_pipeline(prod_preprocessor, pipeline_joblib_path)

    print(f"Exporting feature schema to {schema_json_path}...")
    schema_info = export_feature_schema(prod_preprocessor, schema_json_path)

    # Compile metrics dictionary
    metrics_payload = {
        "model_name": MODEL_NAME,
        "version": MODEL_VERSION,
        "selected_model": best_candidate_name,
        "validation_comparison": validation_results,
        "selection_rationale": (
            f"Selected {best_candidate_name} due to highest validation ROC-AUC "
            f"({validation_results[best_candidate_name]['roc_auc']:.4f}) and superior "
            f"Brier score ({validation_results[best_candidate_name]['brier_score']:.4f})."
        ),
        "test_metrics": test_metrics,
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat()
    }
    with open(metrics_json_path, "w") as f:
        json.dump(metrics_payload, f, indent=2)
    print(f"Metrics saved to {metrics_json_path}")

    # Compile full training metadata
    training_metadata = {
        "model_name": MODEL_NAME,
        "version": MODEL_VERSION,
        "training_timestamp": start_time,
        "completion_timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_names": [
            "Zenodo Multimodal Industrial Logistics Disruption and Risk Dataset (DOI: 10.5281/zenodo.18050317)",
            "Delhivery Logistics Dataset (Secondary Reference - Audited for scope)"
        ],
        "dataset_row_counts": {
            "raw_primary_zenodo": len(df_source),
            "canonical_training_e1": len(df_canonical),
            "train_split": split_meta["train"]["count"],
            "validation_split": split_meta["validation"]["count"],
            "test_split": split_meta["test"]["count"]
        },
        "dataset_checksums": {
            "canonical_training_csv": get_file_checksum(data_path),
            "raw_zenodo_csv": get_file_checksum("data/raw/zenodo/supplychain_datasetV0.csv")
        },
        "feature_names": REQUIRED_FEATURE_COLUMNS,
        "target_definition": "misplaced = 1 if disruption_type > 0 else 0",
        "proxy_label_explanation": (
            "E1 prototype disruption/misplacement-risk proxy label: represents operational "
            "logistics disruption events derived from Zenodo disruption_type > 0. It is NOT "
            "a verified physical lost/misplaced parcel scan."
        ),
        "target_positive_rate": float(df_canonical["misplaced"].mean()),
        "train_validation_test_date_ranges": {
            "train": split_meta["train"]["date_range"],
            "validation": split_meta["validation"]["date_range"],
            "test": split_meta["test"]["date_range"]
        },
        "model_class": str(prod_model.__class__.__name__),
        "model_parameters": {k: str(v) for k, v in prod_model.get_params().items()},
        "sklearn_version": sklearn.__version__,
        "python_version": sys.version,
        "platform": platform.platform(),
        "random_seed": random_seed,
        "metrics": {
            "validation": validation_results[best_candidate_name],
            "test": test_metrics
        },
        "feature_engineering_definitions": {
            "congestion_index": "0.40 * norm(yard_utilization_pct) + 0.30 * norm(gate_turn_time_min) + 0.30 * norm(dwell_time_at_node_min)",
            "weather_flag": "precip_mm >= 4.88 (empirical 75th percentile threshold)",
            "num_handoffs": "stop_count_last_24h proxy for intermediate leg transfers",
            "sorting_method": "unknown (operational placeholder)",
            "hour_of_day": "timestamp hour (0-23)"
        },
        "diagnostic_plots": plot_paths,
        "limitations": [
            "The target is an operational disruption proxy (Zenodo disruption_type > 0), NOT a verified physical parcel misplacement scan.",
            "Sorting method is currently represented by the explicit contract placeholder 'unknown' due to lack of ground-truth sorting technology in source data.",
            "Congestion index is a composite normalized score and should be calibrated with site-specific telemetry when deploying to production facilities."
        ]
    }

    with open(metadata_json_path, "w") as f:
        json.dump(training_metadata, f, indent=2)
    print(f"Training metadata exported to {metadata_json_path}")

    print("\n" + "=" * 60)
    print("E1 TRAINING PIPELINE COMPLETED SUCCESSFULLY")
    print("=" * 60)

    return {
        "model": prod_model,
        "preprocessor": prod_preprocessor,
        "metrics": metrics_payload,
        "metadata": training_metadata
    }


if __name__ == "__main__":
    train_e1_pipeline()
