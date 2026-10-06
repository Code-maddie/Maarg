"""Command-line training and verification entrypoint for E1 Misplacement Classifier."""

import os
import sys
import argparse
import json
import pickle
import joblib
import pandas as pd
import numpy as np

from src.data.audit import discover_and_audit_datasets
from src.data.canonical import build_canonical_dataset
from src.data.leakage import audit_leakage
from src.models.train import train_e1_pipeline
from src.inference.predict import E1ModelService, predict_misplacement_probability


def parse_args():
    parser = argparse.ArgumentParser(description="E1 Misplacement Classifier Pipeline")
    parser.add_argument("--data-root", type=str, default="data/raw", help="Path to raw datasets root")
    parser.add_argument("--version", type=str, default="v1", help="Model version tag (default: v1)")
    parser.add_argument("--artifact-dir", type=str, default=None, help="Custom output directory for artifacts")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    return parser.parse_args()


def run_serialization_and_contract_tests(artifact_dir: str):
    """
    Executes mandatory verification steps:
    1. Delete in-memory model and pipeline objects.
    2. Reload model.pkl and feature_pipeline.joblib.
    3. Run predictions on representative test records.
    4. Test unseen categorical values (ensuring handle_unknown='ignore' works).
    5. Test probability bounds [0.0, 1.0].
    6. Verify inference contract: predict_misplacement_probability(features).
    """
    print("\n" + "=" * 60)
    print("RUNNING SERIALIZATION & INFERENCE CONTRACT VERIFICATION")
    print("=" * 60)

    model_path = os.path.join(artifact_dir, "model.pkl")
    pipeline_path = os.path.join(artifact_dir, "feature_pipeline.joblib")

    # Step 1 & 2: Reload cleanly from disk
    print(f"Reloading model from {model_path}...")
    with open(model_path, "rb") as f:
        reloaded_model = pickle.load(f)

    print(f"Reloading pipeline from {pipeline_path}...")
    reloaded_pipeline = joblib.load(pipeline_path)

    # Step 3: Test on representative held-out sample
    sample_path = "data/processed/e1_training.csv"
    sample_df = pd.read_csv(sample_path).tail(10)
    features_only = sample_df.drop(columns=["misplaced"])

    X_transformed = reloaded_pipeline.transform(features_only)
    probs = reloaded_model.predict_proba(X_transformed)[:, 1]

    print(f"Predicted probabilities on 10 held-out samples:\n{probs.round(4)}")
    assert len(probs) == 10, "Expected 10 probability outputs"
    assert ((probs >= 0.0) & (probs <= 1.0)).all(), "Probabilities out of bounds [0, 1]!"
    print("[OK] Output probabilities are strictly bounded in [0, 1].")

    # Step 4: Test unseen categorical value (handle_unknown='ignore')
    unseen_sample = {
        "route": "ROUTE_9999_UNSEEN",
        "hub": "HUB_9999_UNSEEN",
        "carrier": "drone_hyperloop_unseen",
        "congestion_index": 0.85,
        "num_handoffs": 5,
        "sorting_method": "unseen_automated_sorter",
        "weather_flag": 1,
        "hour_of_day": 14
    }
    df_unseen = pd.DataFrame([unseen_sample])
    X_unseen = reloaded_pipeline.transform(df_unseen)
    prob_unseen = float(reloaded_model.predict_proba(X_unseen)[0, 1])
    print(f"Unseen categories test prediction: P(misplaced) = {prob_unseen:.4f}")
    assert 0.0 <= prob_unseen <= 1.0, f"Unseen prediction out of bounds: {prob_unseen}"
    print("[OK] handle_unknown='ignore' successfully handled novel categorical values.")

    # Step 5: Test canonical inference function
    canonical_example = {
        "route": "R001",
        "hub": "F001",
        "carrier": "air",
        "congestion_index": 0.72,
        "num_handoffs": 4,
        "sorting_method": "unknown",
        "weather_flag": 1,
        "hour_of_day": 19
    }
    service = E1ModelService(model_path=model_path, pipeline_path=pipeline_path)
    prob_canonical = service.predict_one(canonical_example)
    print(f"Canonical serving example prediction: P(misplaced) = {prob_canonical:.4f}")
    assert 0.0 <= prob_canonical <= 1.0, f"Canonical prediction out of bounds: {prob_canonical}"
    print("[OK] Canonical inference contract function passed.")

    print("\n[OK] ALL SERIALIZATION & CONTRACT CHECKS PASSED.")


def main():
    args = parse_args()
    version = args.version
    artifact_dir = args.artifact_dir or f"artifacts/misplacement_classifier/{version}"

    # Step 1: Discover and audit raw datasets
    discover_and_audit_datasets(data_root=args.data_root)

    # Step 2: Build canonical dataset and data dictionary
    build_canonical_dataset()

    # Step 3: Audit temporal leakage
    audit_leakage()

    # Step 4: Full training, selection, testing, and artifact export
    train_results = train_e1_pipeline(
        data_path="data/processed/e1_training.csv",
        source_path="data/processed/e1_training_with_source.csv.gz",
        artifact_dir=artifact_dir,
        random_seed=args.seed
    )

    # Step 5: Run serialization and inference contract verification
    run_serialization_and_contract_tests(artifact_dir)

    metrics = train_results["metrics"]["test_metrics"]
    metadata = train_results["metadata"]
    counts = metadata["dataset_row_counts"]

    print("\n" + "=" * 60)
    print("FINAL E1 PIPELINE BUILD SUMMARY")
    print("=" * 60)
    print(f"DATASET ROWS:             {counts['raw_primary_zenodo']}")
    print(f"CANONICAL TRAINING ROWS:  {counts['canonical_training_e1']}")
    print(f"POSITIVE RATE:            {metadata['target_positive_rate']:.4f}")
    print(f"TRAIN/VAL/TEST COUNTS:    Train={counts['train_split']}, Val={counts['validation_split']}, Test={counts['test_split']}")
    print(f"SELECTED MODEL:           {train_results['metrics']['selected_model']}")
    print(f"ROC-AUC:                  {metrics['roc_auc']:.4f}")
    print(f"PR-AUC:                   {metrics['pr_auc']:.4f}")
    print(f"F1:                       {metrics['f1']:.4f}")
    print(f"Brier Score:              {metrics['brier_score']:.4f}")
    print(f"LOG LOSS:                 {metrics['log_loss']:.4f}")
    print(f"ARTIFACT PATHS:           {artifact_dir}")
    print("BUILD STATUS:             SUCCESS")
    print("=" * 60)


if __name__ == "__main__":
    main()
