"""Canonical dataset builder for E1 Misplacement Classifier."""

import os
import json
import pandas as pd
import numpy as np


# Exact canonical schema required for E1 training
CANONICAL_COLUMNS = [
    "route",
    "hub",
    "carrier",
    "congestion_index",
    "num_handoffs",
    "sorting_method",
    "weather_flag",
    "hour_of_day",
    "misplaced"
]

FEATURE_COLUMNS = [
    "route",
    "hub",
    "carrier",
    "congestion_index",
    "num_handoffs",
    "sorting_method",
    "weather_flag",
    "hour_of_day"
]


def compute_congestion_index(df: pd.DataFrame) -> pd.Series:
    """
    Computes a bounded [0, 1] normalized operational congestion index
    using facility indicators: yard utilization, gate turn time, and dwell time.

    Formula:
      yard_norm  = clip(yard_utilization_pct / 100.0, 0, 1)
      gate_norm  = clip((gate_turn_time_min - min_gate) / (max_gate - min_gate), 0, 1)
      dwell_norm = clip((dwell_time_at_node_min - min_dwell) / (max_dwell - min_dwell), 0, 1)
      congestion_index = clip(0.40 * yard_norm + 0.30 * gate_norm + 0.30 * dwell_norm, 0, 1)
    """
    yard_util = df["yard_utilization_pct"].astype(float)
    gate_turn = df["gate_turn_time_min"].astype(float)
    dwell_time = df["dwell_time_at_node_min"].astype(float)

    yard_norm = np.clip(yard_util / 100.0, 0.0, 1.0)
    
    # Gate turn time normalization (min 6.0, max 98.77 in raw distribution)
    gate_min, gate_max = 6.0, 98.77
    gate_norm = np.clip((gate_turn - gate_min) / (gate_max - gate_min), 0.0, 1.0)

    # Dwell time normalization (min 3.0, max 100.89 in raw distribution)
    dwell_min, dwell_max = 3.0, 100.89
    dwell_norm = np.clip((dwell_time - dwell_min) / (dwell_max - dwell_min), 0.0, 1.0)

    congestion = 0.40 * yard_norm + 0.30 * gate_norm + 0.30 * dwell_norm
    return np.clip(congestion, 0.0, 1.0).round(4)


def compute_weather_flag(df: pd.DataFrame, precip_threshold: float = 4.88) -> pd.Series:
    """
    Constructs a deterministic binary weather flag based on the empirical
    75th percentile of precipitation (4.88 mm).
    weather_flag = 1 if precip_mm >= threshold else 0.
    """
    precip = df["precip_mm"].astype(float)
    return (precip >= precip_threshold).astype(int)


def build_canonical_dataset(
    raw_path: str = "data/raw/zenodo/supplychain_datasetV0.csv",
    output_csv: str = "data/processed/e1_training.csv",
    output_with_source: str = "data/processed/e1_training_with_source.csv.gz",
    output_dict: str = "data/processed/e1_data_dictionary.json"
) -> pd.DataFrame:
    """
    Loads the primary raw dataset, applies deterministic canonical mappings,
    sorts chronologically by timestamp, and exports canonical dataset and dictionary.
    """
    print(f"Loading raw dataset from {raw_path}...")
    df_raw = pd.read_csv(raw_path, low_memory=False)

    # Sort strictly by timestamp for temporal integrity
    df_raw["timestamp_dt"] = pd.to_datetime(df_raw["timestamp"])
    df_raw = df_raw.sort_values("timestamp_dt").reset_index(drop=True)

    print(f"Raw records loaded: {len(df_raw)}, date range: {df_raw['timestamp_dt'].min()} to {df_raw['timestamp_dt'].max()}")

    # 1. Feature mappings
    route = df_raw["route_id"].astype(str)
    hub = df_raw["facility_id"].astype(str)
    carrier = df_raw["carrier_mode"].astype(str)
    num_handoffs = df_raw["stop_count_last_24h"].astype(int)
    congestion_index = compute_congestion_index(df_raw)
    sorting_method = pd.Series(["unknown"] * len(df_raw), dtype=str)
    weather_flag = compute_weather_flag(df_raw)
    hour_of_day = df_raw["timestamp_dt"].dt.hour.astype(int)

    # 2. Target definition
    # E1 prototype disruption/misplacement-risk proxy label:
    # 0 = normal (non-disrupted), 1 = disruption event
    misplaced = (df_raw["disruption_type"] > 0).astype(int)

    # Construct canonical dataframe with EXACTLY the 9 specified columns
    canonical_df = pd.DataFrame({
        "route": route,
        "hub": hub,
        "carrier": carrier,
        "congestion_index": congestion_index,
        "num_handoffs": num_handoffs,
        "sorting_method": sorting_method,
        "weather_flag": weather_flag,
        "hour_of_day": hour_of_day,
        "misplaced": misplaced
    })

    # Validate exact column ordering and count
    assert list(canonical_df.columns) == CANONICAL_COLUMNS, f"Columns mismatch: {list(canonical_df.columns)}"

    os.makedirs(os.path.dirname(output_csv), exist_ok=True)

    # Save canonical CSV
    canonical_df.to_csv(output_csv, index=False)
    print(f"Canonical E1 dataset saved to {output_csv} ({len(canonical_df)} rows, {len(canonical_df.columns)} cols)")

    # Save traceable dataframe with source columns separately
    traceable_df = canonical_df.copy()
    traceable_df["timestamp"] = df_raw["timestamp"]
    traceable_df["raw_disruption_type"] = df_raw["disruption_type"]
    traceable_df["raw_precip_mm"] = df_raw["precip_mm"]
    traceable_df["raw_yard_utilization_pct"] = df_raw["yard_utilization_pct"]
    traceable_df["raw_gate_turn_time_min"] = df_raw["gate_turn_time_min"]
    traceable_df["raw_dwell_time_at_node_min"] = df_raw["dwell_time_at_node_min"]
    traceable_df.to_csv(output_with_source, index=False, compression="gzip")
    print(f"Traceable dataset with raw source columns saved to {output_with_source}")

    # Build data dictionary
    data_dict = {
        "dataset_name": "E1 Canonical Training Dataset",
        "version": "v1",
        "row_count": len(canonical_df),
        "target_positive_rate": float(misplaced.mean()),
        "columns": {
            "route": {
                "dtype": "string",
                "role": "categorical_feature",
                "source": "route_id",
                "description": "Unique identifier for the transit corridor/lane.",
                "example": "R001",
                "cardinality": int(route.nunique())
            },
            "hub": {
                "dtype": "string",
                "role": "categorical_feature",
                "source": "facility_id",
                "description": "Unique identifier for the logistics node/facility/terminal.",
                "example": "F001",
                "cardinality": int(hub.nunique())
            },
            "carrier": {
                "dtype": "string",
                "role": "categorical_feature",
                "source": "carrier_mode",
                "description": "Transport mode or carrier type operating the leg (air, multi, sea, rail, road).",
                "example": "air",
                "cardinality": int(carrier.nunique())
            },
            "congestion_index": {
                "dtype": "float",
                "role": "numeric_feature",
                "source": "Composite: 0.40*(yard_util/100) + 0.30*norm(gate_turn) + 0.30*norm(dwell_time)",
                "description": "Normalized composite facility congestion score bounded in [0, 1].",
                "min": float(congestion_index.min()),
                "max": float(congestion_index.max()),
                "mean": float(congestion_index.mean())
            },
            "num_handoffs": {
                "dtype": "int",
                "role": "numeric_feature",
                "source": "stop_count_last_24h",
                "description": "Operational proxy for number of intermediate transfer stops/handoffs in the last 24h.",
                "min": int(num_handoffs.min()),
                "max": int(num_handoffs.max()),
                "mean": float(num_handoffs.mean())
            },
            "sorting_method": {
                "dtype": "string",
                "role": "categorical_feature",
                "source": "operational contract placeholder ('unknown')",
                "description": "Sorting mechanism at the hub. Because the raw dataset does not observe sorting methods, explicit 'unknown' category is used to maintain contract integrity.",
                "example": "unknown",
                "cardinality": 1
            },
            "weather_flag": {
                "dtype": "int",
                "role": "numeric_feature (binary)",
                "source": "precip_mm >= 4.88 (75th percentile empirical threshold)",
                "description": "Binary indicator: 1 if precipitation exceeds upper quartile (4.88 mm), 0 otherwise.",
                "min": 0,
                "max": 1,
                "positive_rate": float(weather_flag.mean())
            },
            "hour_of_day": {
                "dtype": "int",
                "role": "numeric_feature",
                "source": "timestamp hour",
                "description": "Hour of the day when the shipment state was recorded (0 to 23).",
                "min": 0,
                "max": 23
            },
            "misplaced": {
                "dtype": "int",
                "role": "target",
                "source": "disruption_type > 0",
                "description": "E1 prototype disruption/misplacement-risk proxy label: 0 for normal operations, 1 for operational disruption events.",
                "min": 0,
                "max": 1,
                "positive_rate": float(misplaced.mean()),
                "class_distribution": {
                    "0_normal": int((misplaced == 0).sum()),
                    "1_disrupted": int((misplaced == 1).sum())
                }
            }
        }
    }

    with open(output_dict, "w") as f:
        json.dump(data_dict, f, indent=2)
    print(f"Data dictionary saved to {output_dict}")

    return canonical_df


if __name__ == "__main__":
    build_canonical_dataset()
