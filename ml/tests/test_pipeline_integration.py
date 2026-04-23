"""
ml/tests/test_pipeline_integration.py
=======================================
Integration tests that verify the trained ML pipeline artifacts are present
and functional. These tests touch the real model files and parquet data.

All tests in this module are skipped automatically if the artifact they
require does not exist — they are not expected to pass in a fresh clone
before the pipeline has been run.
"""

import pytest
import numpy as np
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _paths():
    from ml.src.config import MODELS_DIR, PROCESSED_DIR, FEATURES_DIR
    return MODELS_DIR, PROCESSED_DIR, FEATURES_DIR


# ---------------------------------------------------------------------------
# Model artifact tests
# ---------------------------------------------------------------------------

class TestModelFiles:
    # ml/models/ is no longer committed — models live in MLflow/GCS now.
    # These checks run only when someone has trained locally (joblibs present
    # on disk as training output) and skip in CI / fresh clones.

    def test_club_model_file_exists(self):
        MODELS_DIR, _, _ = _paths()
        model_path = MODELS_DIR / "cupcast-club-model_best.joblib"
        if not model_path.exists():
            pytest.skip(f"No local training output at {model_path}")

    def test_intl_model_file_exists(self):
        MODELS_DIR, _, _ = _paths()
        model_path = MODELS_DIR / "cupcast-international-model_best.joblib"
        if not model_path.exists():
            pytest.skip(f"No local training output at {model_path}")

    def test_club_model_file_is_nonzero(self):
        MODELS_DIR, _, _ = _paths()
        model_path = MODELS_DIR / "cupcast-club-model_best.joblib"
        if not model_path.exists():
            pytest.skip("Club model file does not exist")
        assert model_path.stat().st_size > 1000, "Club model file appears empty or truncated"

    def test_intl_model_file_is_nonzero(self):
        MODELS_DIR, _, _ = _paths()
        model_path = MODELS_DIR / "cupcast-international-model_best.joblib"
        if not model_path.exists():
            pytest.skip("International model file does not exist")
        assert model_path.stat().st_size > 1000, "International model file appears empty or truncated"


# ---------------------------------------------------------------------------
# Model loading tests
# ---------------------------------------------------------------------------

class TestModelLoading:
    @pytest.fixture(scope="class")
    def club_model(self):
        MODELS_DIR, _, _ = _paths()
        if not (MODELS_DIR / "cupcast-club-model_best.joblib").exists():
            pytest.skip("Club model not found")
        import joblib
        return joblib.load(MODELS_DIR / "cupcast-club-model_best.joblib")

    @pytest.fixture(scope="class")
    def intl_model(self):
        MODELS_DIR, _, _ = _paths()
        if not (MODELS_DIR / "cupcast-international-model_best.joblib").exists():
            pytest.skip("International model not found")
        import joblib
        return joblib.load(MODELS_DIR / "cupcast-international-model_best.joblib")

    def test_club_model_loads_via_joblib(self, club_model):
        assert club_model is not None

    def test_club_model_has_predict_proba(self, club_model):
        assert hasattr(club_model, "predict_proba"), "Club model must have predict_proba method"

    def test_club_model_predict_proba_shape(self, club_model):
        """predict_proba must return 3-class probabilities."""
        from ml.src.config import CLUB_FEATURES
        X = np.zeros((1, len(CLUB_FEATURES)))
        probs = club_model.predict_proba(X)
        assert probs.shape == (1, 3), f"Expected (1, 3), got {probs.shape}"

    def test_club_model_probabilities_sum_to_one(self, club_model):
        from ml.src.config import CLUB_FEATURES
        X = np.zeros((1, len(CLUB_FEATURES)))
        probs = club_model.predict_proba(X)[0]
        assert abs(sum(probs) - 1.0) < 1e-6, f"Probabilities sum to {sum(probs)}"

    def test_club_model_probabilities_are_non_negative(self, club_model):
        from ml.src.config import CLUB_FEATURES
        X = np.zeros((1, len(CLUB_FEATURES)))
        probs = club_model.predict_proba(X)[0]
        assert all(p >= 0 for p in probs), f"Negative probabilities: {probs}"

    def test_intl_model_loads_via_joblib(self, intl_model):
        assert intl_model is not None

    def test_intl_model_predict_proba_shape(self, intl_model):
        """International model must also return 3-class probabilities."""
        from ml.src.config import INTL_FEATURES
        X = np.zeros((1, len(INTL_FEATURES)))
        probs = intl_model.predict_proba(X)
        assert probs.shape == (1, 3), f"Expected (1, 3), got {probs.shape}"

    def test_intl_model_probabilities_sum_to_one(self, intl_model):
        from ml.src.config import INTL_FEATURES
        X = np.zeros((1, len(INTL_FEATURES)))
        probs = intl_model.predict_proba(X)[0]
        assert abs(sum(probs) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Predictions CSV tests
# ---------------------------------------------------------------------------

class TestPredictionsCSV:
    @pytest.fixture(scope="class")
    def predictions_df(self):
        import pandas as pd
        _, PROCESSED_DIR, _ = _paths()
        csv_path = PROCESSED_DIR / "predictions.csv"
        if not csv_path.exists():
            pytest.skip(f"predictions.csv not found at {csv_path}")
        return pd.read_csv(csv_path)

    def test_predictions_csv_exists(self):
        _, PROCESSED_DIR, _ = _paths()
        csv_path = PROCESSED_DIR / "predictions.csv"
        assert csv_path.exists(), (
            "predictions.csv not found. "
            "Run: conda run -n ml python cupcast/ml/run_pipeline.py --mode predict-only"
        )

    def test_predictions_has_expected_columns(self, predictions_df):
        expected_cols = [
            "home_team", "away_team", "prob_home", "prob_draw", "prob_away",
            "predicted_result", "confidence",
        ]
        for col in expected_cols:
            assert col in predictions_df.columns, f"Missing column: {col}"

    def test_predictions_has_rows(self, predictions_df):
        assert len(predictions_df) > 0, "predictions.csv is empty"

    def test_probabilities_sum_to_one(self, predictions_df):
        """Each row's home+draw+away probabilities should sum to ~1.0."""
        prob_sums = predictions_df["prob_home"] + predictions_df["prob_draw"] + predictions_df["prob_away"]
        assert (abs(prob_sums - 1.0) < 0.01).all(), (
            f"Found rows with probabilities not summing to 1.0: {prob_sums[abs(prob_sums - 1.0) >= 0.01]}"
        )

    def test_predicted_result_values_are_valid(self, predictions_df):
        """predicted_result must be H, D, or A."""
        valid = {"H", "D", "A"}
        invalid_mask = ~predictions_df["predicted_result"].isin(valid)
        assert invalid_mask.sum() == 0, (
            f"Invalid predicted_result values: {predictions_df.loc[invalid_mask, 'predicted_result'].unique()}"
        )

    def test_confidence_is_max_probability(self, predictions_df):
        """confidence should equal the probability of the predicted result."""
        result_to_col = {"H": "prob_home", "D": "prob_draw", "A": "prob_away"}
        for _, row in predictions_df.head(20).iterrows():
            col = result_to_col[row["predicted_result"]]
            assert abs(row["confidence"] - row[col]) < 0.01, (
                f"Confidence {row['confidence']} != {col} {row[col]}"
            )


# ---------------------------------------------------------------------------
# Feature parquet tests
# ---------------------------------------------------------------------------

class TestFeatureParquets:
    @pytest.fixture(scope="class")
    def club_features(self):
        import pandas as pd
        _, _, FEATURES_DIR = _paths()
        parquet_path = FEATURES_DIR / "club_features.parquet"
        if not parquet_path.exists():
            pytest.skip(f"club_features.parquet not found at {parquet_path}")
        return pd.read_parquet(parquet_path)

    @pytest.fixture(scope="class")
    def intl_features(self):
        import pandas as pd
        _, _, FEATURES_DIR = _paths()
        parquet_path = FEATURES_DIR / "intl_features.parquet"
        if not parquet_path.exists():
            pytest.skip(f"intl_features.parquet not found at {parquet_path}")
        return pd.read_parquet(parquet_path)

    def test_club_features_parquet_exists(self):
        _, _, FEATURES_DIR = _paths()
        assert (FEATURES_DIR / "club_features.parquet").exists()

    def test_intl_features_parquet_exists(self):
        _, _, FEATURES_DIR = _paths()
        assert (FEATURES_DIR / "intl_features.parquet").exists()

    def test_club_features_has_expected_column_count(self, club_features):
        """Club feature matrix should contain all CLUB_FEATURES plus metadata columns."""
        from ml.src.config import CLUB_FEATURES
        missing = [col for col in CLUB_FEATURES if col not in club_features.columns]
        assert not missing, f"Missing feature columns: {missing}"

    def test_intl_features_has_expected_column_count(self, intl_features):
        """International feature matrix should contain all INTL_FEATURES."""
        from ml.src.config import INTL_FEATURES
        missing = [col for col in INTL_FEATURES if col not in intl_features.columns]
        assert not missing, f"Missing feature columns: {missing}"

    def test_club_features_has_no_all_nan_columns(self, club_features):
        """No feature column should be entirely NaN."""
        from ml.src.config import CLUB_FEATURES
        for col in CLUB_FEATURES:
            if col in club_features.columns:
                assert not club_features[col].isna().all(), f"Column '{col}' is all NaN"

    def test_club_features_has_sufficient_rows(self, club_features):
        """Should have tens of thousands of rows from historical data."""
        assert len(club_features) > 10_000, f"Only {len(club_features)} rows in club_features"

    def test_intl_features_has_sufficient_rows(self, intl_features):
        """Should have tens of thousands of international matches."""
        assert len(intl_features) > 5_000, f"Only {len(intl_features)} rows in intl_features"

    def test_club_features_result_encoded_has_3_classes(self, club_features):
        """result_encoded should have exactly 3 unique values: 0, 1, 2."""
        if "result_encoded" not in club_features.columns:
            pytest.skip("result_encoded not in club_features")
        unique_classes = set(club_features["result_encoded"].dropna().unique())
        assert unique_classes == {0, 1, 2}, f"Expected {{0, 1, 2}}, got {unique_classes}"
