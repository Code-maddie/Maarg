"""Tests for serialization and deserialization numerical equivalence."""

import unittest
import pickle
import joblib
import pandas as pd
import numpy as np

from src.features.validator import REQUIRED_FEATURE_COLUMNS


class TestSerializationEquivalence(unittest.TestCase):

    def setUp(self):
        self.model_path = "artifacts/misplacement_classifier/v1/model.pkl"
        self.pipeline_path = "artifacts/misplacement_classifier/v1/feature_pipeline.joblib"
        self.test_data = pd.read_csv("data/processed/e1_training.csv").tail(25)[REQUIRED_FEATURE_COLUMNS]

    def test_reloaded_numerical_equivalence(self):
        """Verify that reloaded model produces identical predictions to first load."""
        with open(self.model_path, "rb") as f:
            m1 = pickle.load(f)
        p1 = joblib.load(self.pipeline_path)

        # Run prediction
        X1 = p1.transform(self.test_data)
        prob1 = m1.predict_proba(X1)[:, 1]

        # Delete from memory
        del m1, p1

        # Reload cleanly
        with open(self.model_path, "rb") as f:
            m2 = pickle.load(f)
        p2 = joblib.load(self.pipeline_path)

        X2 = p2.transform(self.test_data)
        prob2 = m2.predict_proba(X2)[:, 1]

        np.testing.assert_allclose(prob1, prob2, rtol=1e-6, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
