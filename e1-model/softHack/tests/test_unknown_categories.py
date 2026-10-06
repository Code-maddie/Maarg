"""Tests for handling unknown categorical values in E1."""

import unittest
from src.inference.predict import predict_misplacement_probability


class TestUnknownCategories(unittest.TestCase):

    def test_unseen_route_and_hub(self):
        """Unseen route, hub, carrier, and sorting method must be handled without raising error."""
        unseen_input = {
            "route": "COMPLETELY_NEW_ROUTE_XYZ",
            "hub": "COMPLETELY_NEW_FACILITY_123",
            "carrier": "experimental_hyperloop",
            "congestion_index": 0.50,
            "num_handoffs": 2,
            "sorting_method": "robotic_arm_v2",
            "weather_flag": 0,
            "hour_of_day": 14
        }
        prob = predict_misplacement_probability(unseen_input)
        self.assertIsInstance(prob, float)
        self.assertGreaterEqual(prob, 0.0)
        self.assertLessEqual(prob, 1.0)


if __name__ == "__main__":
    unittest.main()
