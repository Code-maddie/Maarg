"""Tests for E1 ColumnTransformer preprocessing pipeline."""

import os
import unittest
import pandas as pd
import numpy as np

from src.features.pipeline import build_feature_pipeline
from src.features.validator import REQUIRED_FEATURE_COLUMNS, CATEGORICAL_FEATURES, NUMERIC_FEATURES


class TestPreprocessing(unittest.TestCase):

    def setUp(self):
        self.pipeline = build_feature_pipeline()
        self.sample_df = pd.DataFrame({
            "route": ["R001", "R002", "R001"],
            "hub": ["F001", "F002", "F001"],
            "carrier": ["air", "sea", "air"],
            "congestion_index": [0.25, 0.75, 0.50],
            "num_handoffs": [1, 5, 3],
            "sorting_method": ["unknown", "unknown", "unknown"],
            "weather_flag": [0, 1, 0],
            "hour_of_day": [8, 18, 12]
        })

    def test_pipeline_fit_transform(self):
        """Verify pipeline fits and transforms DataFrame without error."""
        X_trans = self.pipeline.fit_transform(self.sample_df[REQUIRED_FEATURE_COLUMNS])
        self.assertIsInstance(X_trans, np.ndarray)
        self.assertEqual(X_trans.shape[0], len(self.sample_df))
        self.assertFalse(np.isnan(X_trans).any(), "Transformed output has NaNs")

    def test_feature_ordering_guarantee(self):
        """Changing input column order should still produce consistent output when reindexed."""
        self.pipeline.fit(self.sample_df[REQUIRED_FEATURE_COLUMNS])
        
        # Scrambled columns
        reversed_cols = list(reversed(REQUIRED_FEATURE_COLUMNS))
        df_scrambled = self.sample_df[reversed_cols]
        
        # When mapped correctly via schema, output must be identical
        X1 = self.pipeline.transform(self.sample_df[REQUIRED_FEATURE_COLUMNS])
        X2 = self.pipeline.transform(df_scrambled[REQUIRED_FEATURE_COLUMNS])
        np.testing.assert_allclose(X1, X2)


if __name__ == "__main__":
    unittest.main()
