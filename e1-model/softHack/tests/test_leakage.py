"""Tests for temporal leakage prevention in E1."""

import os
import json
import unittest
import pandas as pd

from src.features.validator import REQUIRED_FEATURE_COLUMNS
from src.data.leakage import EXCLUDED_LEAKAGE_COLUMNS


class TestLeakage(unittest.TestCase):

    def test_forbidden_columns_excluded(self):
        """Verify that no post-event or leakage columns are present in REQUIRED_FEATURE_COLUMNS."""
        for forbidden in EXCLUDED_LEAKAGE_COLUMNS.keys():
            self.assertNotIn(
                forbidden,
                REQUIRED_FEATURE_COLUMNS,
                f"Leakage violation: forbidden column '{forbidden}' is in feature set!"
            )

    def test_canonical_dataset_has_no_leakage_columns(self):
        """Verify e1_training.csv contains only canonical features and target."""
        df = pd.read_csv("data/processed/e1_training.csv", nrows=10)
        for col in df.columns:
            if col != "misplaced":
                self.assertIn(col, REQUIRED_FEATURE_COLUMNS)

    def test_leakage_report_file(self):
        """Verify leakage report exists and confirms leakage-free status."""
        report_path = "data/processed/leakage_report.json"
        self.assertTrue(os.path.exists(report_path), "Leakage report missing.")
        with open(report_path, "r") as f:
            report = json.load(f)
        self.assertTrue(report["leakage_free_status"], "Leakage audit reported leakage!")


if __name__ == "__main__":
    unittest.main()
