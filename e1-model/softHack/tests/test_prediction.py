"""Tests for E1 inference functions and serving contracts."""

import unittest
import pandas as pd
import numpy as np

from src.inference.predict import predict_misplacement_probability, predict_batch_probabilities


class TestPrediction(unittest.TestCase):

    def setUp(self):
        self.valid_input = {
            "route": "R001",
            "hub": "F001",
            "carrier": "air",
            "congestion_index": 0.72,
            "num_handoffs": 4,
            "sorting_method": "unknown",
            "weather_flag": 1,
            "hour_of_day": 19
        }

    def test_single_prediction(self):
        """Verify predict_misplacement_probability returns float in [0.0, 1.0]."""
        p = predict_misplacement_probability(self.valid_input)
        self.assertIsInstance(p, float)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_batch_prediction_list(self):
        """Verify batch prediction with list of dicts."""
        records = [self.valid_input, self.valid_input]
        probs = predict_batch_probabilities(records)
        self.assertIsInstance(probs, np.ndarray)
        self.assertEqual(len(probs), 2)
        self.assertTrue(((probs >= 0.0) & (probs <= 1.0)).all())

    def test_batch_prediction_dataframe(self):
        """Verify batch prediction with pandas DataFrame."""
        df = pd.DataFrame([self.valid_input, self.valid_input])
        probs = predict_batch_probabilities(df)
        self.assertIsInstance(probs, np.ndarray)
        self.assertEqual(len(probs), 2)
        self.assertTrue(((probs >= 0.0) & (probs <= 1.0)).all())


if __name__ == "__main__":
    unittest.main()
