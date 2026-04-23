"""
ml/tests/test_predict.py
=========================
Tests for predict.py.

Unit tests use a stub model (not the real trained model) for speed and isolation.
Integration tests that load the real model are marked with pytest.mark.integration.
"""

import numpy as np
import pytest
import pandas as pd
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Stub model factory
# ---------------------------------------------------------------------------

def make_stub_model(probs: list) -> MagicMock:
    """Create a mock model that returns the given probabilities from predict_proba."""
    model = MagicMock()
    model.predict_proba.return_value = np.array([probs])
    return model


# ---------------------------------------------------------------------------
# TestPredictMatch
# ---------------------------------------------------------------------------

class TestPredictMatch:
    def test_probabilities_sum_to_one(self):
        """Model probabilities must sum to exactly 1.0."""
        from ml.src.predict import predict_match

        model = make_stub_model([0.6, 0.25, 0.15])
        feature_row = pd.Series(np.zeros(60))  # 60 club features
        result = predict_match(feature_row, model)

        total = result.prob_home_win + result.prob_draw + result.prob_away_win
        assert abs(total - 1.0) < 1e-6, f"Probabilities sum to {total}"

    def test_predicted_result_is_argmax(self):
        """predicted_result should match the class with the highest probability."""
        from ml.src.predict import predict_match

        # Away team has highest probability
        model = make_stub_model([0.20, 0.25, 0.55])
        feature_row = pd.Series(np.zeros(60))
        result = predict_match(feature_row, model)

        assert result.predicted_result == "A", f"Expected 'A', got '{result.predicted_result}'"

    def test_predicted_result_home_win(self):
        from ml.src.predict import predict_match

        model = make_stub_model([0.65, 0.20, 0.15])
        feature_row = pd.Series(np.zeros(60))
        result = predict_match(feature_row, model)
        assert result.predicted_result == "H"

    def test_predicted_result_draw(self):
        from ml.src.predict import predict_match

        model = make_stub_model([0.30, 0.50, 0.20])
        feature_row = pd.Series(np.zeros(60))
        result = predict_match(feature_row, model)
        assert result.predicted_result == "D"

    def test_confidence_is_max_probability(self):
        """confidence should be the probability of the predicted class."""
        from ml.src.predict import predict_match

        model = make_stub_model([0.65, 0.20, 0.15])
        feature_row = pd.Series(np.zeros(60))
        result = predict_match(feature_row, model)
        assert abs(result.confidence - 0.65) < 1e-6

    def test_accepts_dataframe_row(self):
        """predict_match should accept a single-row DataFrame as well as a Series."""
        from ml.src.predict import predict_match

        model = make_stub_model([0.50, 0.30, 0.20])
        feature_df = pd.DataFrame([np.zeros(60)])
        result = predict_match(feature_df, model)
        assert result.predicted_result == "H"

    def test_result_has_all_fields(self):
        """PredictionResult should have all documented fields."""
        from ml.src.predict import predict_match, PredictionResult

        model = make_stub_model([0.55, 0.25, 0.20])
        feature_row = pd.Series(np.zeros(60))
        result = predict_match(feature_row, model)

        assert hasattr(result, "prob_home_win")
        assert hasattr(result, "prob_draw")
        assert hasattr(result, "prob_away_win")
        assert hasattr(result, "predicted_result")
        assert hasattr(result, "confidence")


# ---------------------------------------------------------------------------
# TestBookmakerEdge
# ---------------------------------------------------------------------------

class TestBookmakerEdge:
    def test_correct_implied_probability_normalization(self):
        """
        Given odds H=2.0, D=3.5, A=4.0:
        raw implied = 0.500, 0.286, 0.250 → sum = 1.036
        normalized = 0.483, 0.276, 0.241
        Edge home = 0.65 - 0.483 = 0.167 → value pick
        """
        from ml.src.predict import compute_bookmaker_edge

        result = compute_bookmaker_edge(0.65, 0.20, 0.15, 2.0, 3.5, 4.0)

        raw_sum = (1 / 2.0) + (1 / 3.5) + (1 / 4.0)
        expected_implied_home = (1 / 2.0) / raw_sum
        expected_edge_home = 0.65 - expected_implied_home

        assert result["edge_home"] is not None
        assert abs(result["edge_home"] - expected_edge_home) < 0.001

    def test_value_pick_flagged_above_threshold(self):
        """Large positive edge → is_value_pick=True with correct direction."""
        from ml.src.predict import compute_bookmaker_edge

        result = compute_bookmaker_edge(0.65, 0.20, 0.15, 2.0, 3.5, 4.0)
        assert result["is_value_pick"] is True
        assert result["value_pick_direction"] == "H"

    def test_no_edge_when_odds_missing(self):
        """Missing odds should return a result dict with is_value_pick=False."""
        from ml.src.predict import compute_bookmaker_edge

        result = compute_bookmaker_edge(0.6, 0.2, 0.2, None, None, None)
        assert result["is_value_pick"] is False
        assert result["edge_home"] is None
        assert result["edge_draw"] is None
        assert result["edge_away"] is None

    def test_no_value_pick_when_model_matches_market(self):
        """When model and market agree, no value pick should be flagged."""
        from ml.src.predict import compute_bookmaker_edge

        # Set odds so implied probs roughly match model probs
        # Model: 0.50/0.25/0.25 (evens on home, 4.0 on draw/away)
        result = compute_bookmaker_edge(0.50, 0.25, 0.25, 2.0, 4.0, 4.0)
        # raw implied: 0.5 + 0.25 + 0.25 = 1.0 (no vig, normalized ≈ same)
        assert result["is_value_pick"] is False

    def test_edge_home_draw_away_are_all_present(self):
        from ml.src.predict import compute_bookmaker_edge

        result = compute_bookmaker_edge(0.65, 0.20, 0.15, 2.0, 3.5, 4.0)
        assert "edge_home" in result
        assert "edge_draw" in result
        assert "edge_away" in result
        assert "is_value_pick" in result
        assert "value_pick_direction" in result


# ---------------------------------------------------------------------------
# Integration tests — use real trained model (slow, marked separately)
# ---------------------------------------------------------------------------

class TestLoadProductionModel:
    """These tests require the real trained models in ml/models/."""

    @pytest.fixture(scope="class")
    def club_model(self):
        from ml.src.config import MODELS_DIR
        model_path = MODELS_DIR / "cupcast-club-model_best.joblib"
        if not model_path.exists():
            pytest.skip(f"Club model not found at {model_path}")
        from ml.src.predict import load_production_model
        return load_production_model("club")

    @pytest.fixture(scope="class")
    def intl_model(self):
        from ml.src.config import MODELS_DIR
        model_path = MODELS_DIR / "cupcast-international-model_best.joblib"
        if not model_path.exists():
            pytest.skip(f"International model not found at {model_path}")
        from ml.src.predict import load_production_model
        return load_production_model("intl")

    def test_club_model_has_predict_proba(self, club_model):
        assert hasattr(club_model, "predict_proba")

    def test_club_model_predict_proba_returns_3_classes(self, club_model):
        """Club model must output probabilities for 3 classes: H, D, A."""
        from ml.src.config import CLUB_FEATURES
        X = np.zeros((1, len(CLUB_FEATURES)))
        probs = club_model.predict_proba(X)
        assert probs.shape == (1, 3), f"Expected (1, 3), got {probs.shape}"

    def test_club_model_probabilities_sum_to_one(self, club_model):
        from ml.src.config import CLUB_FEATURES
        X = np.zeros((1, len(CLUB_FEATURES)))
        probs = club_model.predict_proba(X)[0]
        assert abs(sum(probs) - 1.0) < 1e-6

    def test_intl_model_has_predict_proba(self, intl_model):
        assert hasattr(intl_model, "predict_proba")

    def test_intl_model_predict_proba_returns_3_classes(self, intl_model):
        from ml.src.config import INTL_FEATURES
        X = np.zeros((1, len(INTL_FEATURES)))
        probs = intl_model.predict_proba(X)
        assert probs.shape == (1, 3), f"Expected (1, 3), got {probs.shape}"
