"""Tests for input validation error handling."""

import unittest
from src.features.validator import validate_inference_input, ValidationError
from src.inference.predict import predict_misplacement_probability


class TestInvalidInputs(unittest.TestCase):

    def setUp(self):
        self.base_valid = {
            "route": "R001",
            "hub": "F001",
            "carrier": "air",
            "congestion_index": 0.5,
            "num_handoffs": 2,
            "sorting_method": "unknown",
            "weather_flag": 0,
            "hour_of_day": 12
        }

    def test_missing_column(self):
        """Missing required column must raise ValidationError."""
        invalid = self.base_valid.copy()
        del invalid["route"]
        with self.assertRaises(ValidationError):
            validate_inference_input(invalid)

    def test_negative_num_handoffs(self):
        """Negative num_handoffs must raise ValidationError."""
        invalid = self.base_valid.copy()
        invalid["num_handoffs"] = -1
        with self.assertRaises(ValidationError):
            validate_inference_input(invalid)

    def test_out_of_bounds_congestion(self):
        """congestion_index outside [0, 1] must raise ValidationError."""
        invalid = self.base_valid.copy()
        invalid["congestion_index"] = 1.5
        with self.assertRaises(ValidationError):
            validate_inference_input(invalid)

        invalid["congestion_index"] = -0.1
        with self.assertRaises(ValidationError):
            validate_inference_input(invalid)

    def test_out_of_bounds_hour(self):
        """hour_of_day outside 0..23 must raise ValidationError."""
        invalid = self.base_valid.copy()
        invalid["hour_of_day"] = 25
        with self.assertRaises(ValidationError):
            validate_inference_input(invalid)

    def test_invalid_weather_flag(self):
        """weather_flag outside {0, 1} must raise ValidationError."""
        invalid = self.base_valid.copy()
        invalid["weather_flag"] = 5
        with self.assertRaises(ValidationError):
            validate_inference_input(invalid)

    def test_nan_values(self):
        """NaN values must raise ValidationError."""
        invalid = self.base_valid.copy()
        invalid["congestion_index"] = float("nan")
        with self.assertRaises(ValidationError):
            validate_inference_input(invalid)


if __name__ == "__main__":
    unittest.main()
