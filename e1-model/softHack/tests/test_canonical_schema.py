"""Tests for E1 canonical schema and data dictionary."""

import os
import json
import unittest
import pandas as pd

from src.data.canonical import CANONICAL_COLUMNS, FEATURE_COLUMNS
from src.features.validator import validate_feature_dataframe


class TestCanonicalSchema(unittest.TestCase):

    def setUp(self):
        self.csv_path = "data/processed/e1_training.csv"
        self.dict_path = "data/processed/e1_data_dictionary.json"

    def test_canonical_file_exists(self):
        """Verify that e1_training.csv exists."""
        self.assertTrue(os.path.exists(self.csv_path), f"{self.csv_path} does not exist.")

    def test_exact_columns_and_order(self):
        """Verify that e1_training.csv has exactly the 9 specified canonical columns."""
        df = pd.read_csv(self.csv_path, nrows=50)
        self.assertEqual(list(df.columns), CANONICAL_COLUMNS)

    def test_no_null_values(self):
        """Verify no nulls in canonical dataset."""
        df = pd.read_csv(self.csv_path)
        null_counts = df.isna().sum()
        self.assertEqual(int(null_counts.sum()), 0, f"Found nulls:\n{null_counts[null_counts > 0]}")

    def test_data_dictionary_exists_and_matches(self):
        """Verify data dictionary schema matches canonical columns."""
        self.assertTrue(os.path.exists(self.dict_path), f"{self.dict_path} does not exist.")
        with open(self.dict_path, "r") as f:
            data_dict = json.load(f)

        dict_cols = list(data_dict["columns"].keys())
        self.assertEqual(dict_cols, CANONICAL_COLUMNS)


if __name__ == "__main__":
    unittest.main()
