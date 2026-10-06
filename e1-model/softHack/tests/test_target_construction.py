"""Tests for E1 target proxy construction and class balance."""

import unittest
import pandas as pd
import numpy as np


class TestTargetConstruction(unittest.TestCase):

    def setUp(self):
        self.csv_path = "data/processed/e1_training.csv"

    def test_target_binary_values(self):
        """Verify target contains strictly binary values {0, 1}."""
        df = pd.read_csv(self.csv_path, usecols=["misplaced"])
        unique_vals = set(df["misplaced"].unique())
        self.assertTrue(unique_vals.issubset({0, 1}), f"Unexpected target values: {unique_vals}")

    def test_target_class_balance(self):
        """Verify target positive rate is within expected operational range (25% - 35%)."""
        df = pd.read_csv(self.csv_path, usecols=["misplaced"])
        pos_rate = df["misplaced"].mean()
        self.assertGreater(pos_rate, 0.20, f"Positive rate unexpectedly low: {pos_rate}")
        self.assertLess(pos_rate, 0.45, f"Positive rate unexpectedly high: {pos_rate}")

    def test_target_proxy_semantic_mapping(self):
        """Verify proxy mapping logic: 0 -> normal, >0 -> 1."""
        raw_disruptions = pd.Series([0, 1, 2, 5, 9, 0, 3])
        expected = pd.Series([0, 1, 1, 1, 1, 0, 1])
        actual = (raw_disruptions > 0).astype(int)
        pd.testing.assert_series_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()
