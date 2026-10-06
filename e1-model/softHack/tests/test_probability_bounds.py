"""Tests for ensuring all predicted probabilities are strictly in [0.0, 1.0]."""

import unittest
import numpy as np
import pandas as pd

from src.inference.predict import predict_misplacement_probability, predict_batch_probabilities


class TestProbabilityBounds(unittest.TestCase):

    def test_random_samples_probability_bounds(self):
        """Generates 50 varied parameter combinations and tests that P is always in [0, 1]."""
        np.random.seed(42)
        routes = ["R001", "R050", "R999_NEW"]
        hubs = ["F001", "F100", "F999_NEW"]
        carriers = ["air", "sea", "multi", "road", "rail", "drone"]

        for _ in range(50):
            sample = {
                "route": np.random.choice(routes),
                "hub": np.random.choice(hubs),
                "carrier": np.random.choice(carriers),
                "congestion_index": float(np.random.uniform(0.0, 1.0)),
                "num_handoffs": int(np.random.randint(0, 10)),
                "sorting_method": "unknown",
                "weather_flag": int(np.random.choice([0, 1])),
                "hour_of_day": int(np.random.randint(0, 24))
            }
            p = predict_misplacement_probability(sample)
            self.assertFalse(np.isnan(p), f"Probability was NaN for {sample}")
            self.assertFalse(np.isinf(p), f"Probability was Inf for {sample}")
            self.assertGreaterEqual(p, 0.0, f"Probability < 0 for {sample}")
            self.assertLessEqual(p, 1.0, f"Probability > 1 for {sample}")


if __name__ == "__main__":
    unittest.main()
