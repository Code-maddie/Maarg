"""Dataset discovery, inspection, and auditing for E1."""

import os
import glob
import json
import pandas as pd
import numpy as np


def discover_and_audit_datasets(data_root="data/raw", output_path="data/processed/data_audit_report.json"):
    """
    Recursively inspects data_root for tabular datasets, audits schema, statistics,
    and documents training relevance.
    """
    files = glob.glob(os.path.join(data_root, "**", "*"), recursive=True)
    tabular_files = [
        f for f in files
        if os.path.isfile(f) and f.endswith(('.csv', '.csv.gz', '.parquet', '.json'))
    ]

    report = {
        "datasets_found": [],
        "audit_summary": {},
        "training_relevance": {}
    }

    for file_path in tabular_files:
        norm_path = os.path.normpath(file_path).replace("\\", "/")
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"Auditing {norm_path} ({file_size_mb:.2f} MB)...")

        if norm_path.endswith(('.csv', '.csv.gz')):
            df = pd.read_csv(file_path, low_memory=False)
        elif norm_path.endswith('.parquet'):
            df = pd.read_parquet(file_path)
        elif norm_path.endswith('.json'):
            df = pd.read_json(file_path)
        else:
            continue

        n_rows, n_cols = df.shape
        duplicates = int(df.duplicated().sum())
        missing_per_col = {col: int(df[col].isna().sum()) for col in df.columns}
        dtypes_per_col = {col: str(df[col].dtype) for col in df.columns}

        # Categorical cardinalities
        cat_cardinalities = {}
        for col in df.columns:
            if df[col].dtype == 'object' or df[col].nunique() < 50:
                cat_cardinalities[col] = int(df[col].nunique())

        # Timestamp columns
        timestamp_cols = []
        for col in df.columns:
            if any(term in col.lower() for term in ['time', 'date', 'timestamp']):
                timestamp_cols.append(col)

        # Disruption / target columns
        disruption_cols = []
        for col in df.columns:
            if any(term in col.lower() for term in ['disrupt', 'delay', 'misplace', 'risk', 'severity', 'cutoff']):
                disruption_cols.append(col)

        dataset_info = {
            "file_path": norm_path,
            "size_mb": round(file_size_mb, 2),
            "row_count": n_rows,
            "column_count": n_cols,
            "columns": list(df.columns),
            "dtypes": dtypes_per_col,
            "duplicate_rows": duplicates,
            "missing_values_total": sum(missing_per_col.values()),
            "missing_per_column": {k: v for k, v in missing_per_col.items() if v > 0},
            "timestamp_columns": timestamp_cols,
            "disruption_candidate_columns": disruption_cols,
            "categorical_cardinalities": cat_cardinalities
        }

        report["datasets_found"].append(norm_path)
        report["audit_summary"][norm_path] = dataset_info

        # Document training relevance based on schema
        if "supplychain_datasetV0.csv" in norm_path or "zenodo" in norm_path.lower():
            report["training_relevance"][norm_path] = {
                "relevant": True,
                "role": "primary_training_dataset",
                "rationale": (
                    "Multimodal logistics dataset containing explicit disruption_type ground truth, "
                    "route and facility identifiers, carrier mode, stop counts, operational facility metrics "
                    "(yard utilization, gate turn time, dwell time), precipitation, and hourly timestamps."
                )
            }
        elif "delhivery" in norm_path.lower():
            report["training_relevance"][norm_path] = {
                "relevant": False,
                "role": "secondary_logistics_reference",
                "rationale": (
                    "Contains Indian road package delivery trips, but lacks disruption/misplacement ground truth, "
                    "facility yard congestion metrics, and weather precipitation. It represents actual transit times "
                    "rather than facility/carrier disruption events."
                )
            }

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Data audit report saved to {output_path}")

    return report


if __name__ == "__main__":
    discover_and_audit_datasets()
