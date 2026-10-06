"""Tests for E1 feature engineering logic."""

import unittest
import pandas as pd
import numpy as np

from src.data.canonical import compute_congestion_index, compute_weather_flag


class TestFeatureEngineering(unittest.TestCase):

    def setUp(self):
        self.sample_df = pd.DataFrame({
            "yard_utilization_pct": [0.0, 50.0, 100.0, 150.0, -10.0],
            "gate_turn_time_min": [6.0, 50.0, 98.77, 120.0, 0.0],
            "dwell_time_at_node_min": [3.0, 50.0, 100.89, 200.0, 0.0],
            "precip_mm": [0.0, 2.0, 4.88, 10.0, 25.0]
        })

    def test_congestion_index_bounds(self):
        """Verify congestion index is strictly bounded in [0.0, 1.0]."""
        ci = compute_congestion_index(self.sample_df)
        self.assertTrue((ci >= 0.0).all(), "Congestion index below 0.0")
        self.assertTrue((ci <= 1.0).all(), "Congestion index above 1.0")

    def test_congestion_index_monotonicity(self):
        """Increasing yard, gate, and dwell times should increase congestion score."""
        df_low = pd.DataFrame({
            "yard_utilization_pct": [20.0],
            "gate_turn_time_min": [15.0],
            "dwell_time_at_node_min": [10.0]
        })
        df_high = pd.DataFrame({
            "yard_utilization_pct": [80.0],
            "gate_turn_time_min": [60.0],
            "dwell_time_at_node_min": [70.0]
        })
        ci_low = compute_congestion_index(df_low).iloc[0]
        ci_high = compute_congestion_index(df_high).iloc[0]
        self.assertGreater(ci_high, ci_low)

    def test_weather_flag_threshold(self):
        """Verify precipitation threshold (4.88 mm) converts properly to {0, 1}."""
        wf = compute_weather_flag(self.sample_df, precip_threshold=4.88)
        self.assertEqual(wf.iloc[0], 0)  # 0.0 mm
        self.assertEqual(wf.iloc[1], 0)  # 2.0 mm
        self.assertEqual(wf.iloc[2], 1)  # 4.88 mm (exact threshold)
        self.assertEqual(wf.iloc[3], 1)  # 10.0 mm
        self.assertEqual(wf.iloc[4], 1)  # 25.0 mm
        self.assertTrue(set(wf.unique()).issubset({0, 1}))


if __name__ == "__main__":
    unittest.main()
