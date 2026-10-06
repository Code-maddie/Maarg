"""Temporal leakage audit for E1 Misplacement Classifier features."""

import os
import json
from typing import Dict, Any


FEATURE_LEAKAGE_AUDIT = {
    "route": {
        "source_column": "route_id",
        "observable_at_prediction_time": True,
        "is_leakage": False,
        "rationale": "Static planned lane identifier known prior to shipment departure."
    },
    "hub": {
        "source_column": "facility_id",
        "observable_at_prediction_time": True,
        "is_leakage": False,
        "rationale": "The facility node where the shipment is currently in-transit or undergoing transfer."
    },
    "carrier": {
        "source_column": "carrier_mode",
        "observable_at_prediction_time": True,
        "is_leakage": False,
        "rationale": "Transport mode / operating carrier assigned to the leg prior to execution."
    },
    "congestion_index": {
        "source_column": "yard_utilization_pct, gate_turn_time_min, dwell_time_at_node_min",
        "observable_at_prediction_time": True,
        "is_leakage": False,
        "rationale": (
            "Operational telemetry and yard/facility status available in real time as the shipment "
            "approaches or is processed at the hub. It does not reflect post-disruption incident resolution."
        )
    },
    "num_handoffs": {
        "source_column": "stop_count_last_24h",
        "observable_at_prediction_time": True,
        "is_leakage": False,
        "rationale": "Count of intermediate stops/handoffs accumulated over the prior 24-hour operational window before prediction."
    },
    "sorting_method": {
        "source_column": "operational contract placeholder ('unknown')",
        "observable_at_prediction_time": True,
        "is_leakage": False,
        "rationale": "Hub facility sorting configuration known in advance (fixed to 'unknown' in v1)."
    },
    "weather_flag": {
        "source_column": "precip_mm",
        "observable_at_prediction_time": True,
        "is_leakage": False,
        "rationale": "Meteorological sensor/nowcast measurement at the node at prediction timestamp."
    },
    "hour_of_day": {
        "source_column": "timestamp hour",
        "observable_at_prediction_time": True,
        "is_leakage": False,
        "rationale": "Clock hour when prediction is triggered."
    }
}

EXCLUDED_LEAKAGE_COLUMNS = {
    "disruption_type": "Ground-truth target source; directly reveals disruption event.",
    "severity_level": "Post-event impact assessment recorded only after disruption occurs.",
    "zone_risk_level": "Derived risk label potentially informed by incident outcome.",
    "sustainability_impact_class": "Post-trip ESG audit metric computed after execution.",
    "actual_CO2e_kg": "Actual emissions measured post-trip.",
    "co2e_gap_pct": "Post-trip discrepancy between actual and planned emissions.",
    "eta_gap_hours": "Realized delay outcome calculated against final arrival time.",
    "km_detour_pct": "Realized route diversion percentage after detour completed.",
    "engine_fault_code_count": "Post-incident vehicle diagnostics.",
    "idle_time_min": "Accumulated idle duration over entire trip leg."
}


def audit_leakage(output_path: str = "data/processed/leakage_report.json") -> Dict[str, Any]:
    """Generates an explicit temporal leakage audit report for E1."""
    report = {
        "audit_name": "E1 Temporal Feature Leakage Audit",
        "timestamp_semantics": "In-flight operational state at prediction timestamp",
        "features_included": FEATURE_LEAKAGE_AUDIT,
        "leakage_free_status": all(not f["is_leakage"] for f in FEATURE_LEAKAGE_AUDIT.values()),
        "excluded_columns": EXCLUDED_LEAKAGE_COLUMNS,
        "conclusion": (
            "All 8 selected features are strictly observable at or before prediction time. "
            "All post-event resolution, actual delay outcomes, and incident severity indicators "
            "have been excluded from the feature matrix."
        )
    }

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Leakage audit report saved to {output_path}")

    return report


if __name__ == "__main__":
    audit_leakage()
