"""Tests for loading E1 serialized model and pipeline artifacts."""

import os
import unittest
import pickle
import joblib


class TestModelLoading(unittest.TestCase):

    def setUp(self):
        self.model_path = "artifacts/misplacement_classifier/v1/model.pkl"
        self.pipeline_path = "artifacts/misplacement_classifier/v1/feature_pipeline.joblib"

    def test_artifacts_exist(self):
        """Verify model.pkl and feature_pipeline.joblib exist on disk."""
        self.assertTrue(os.path.exists(self.model_path), f"Missing {self.model_path}")
        self.assertTrue(os.path.exists(self.pipeline_path), f"Missing {self.pipeline_path}")

    def test_model_has_predict_proba(self):
        """Verify loaded model supports predict_proba."""
        with open(self.model_path, "rb") as f:
            model = pickle.load(f)
        self.assertTrue(hasattr(model, "predict_proba"), "Model object lacks predict_proba method.")

    def test_pipeline_has_transform(self):
        """Verify loaded pipeline supports transform."""
        pipeline = joblib.load(self.pipeline_path)
        self.assertTrue(hasattr(pipeline, "transform"), "Pipeline object lacks transform method.")


if __name__ == "__main__":
    unittest.main()
