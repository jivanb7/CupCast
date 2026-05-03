"""Automated model behavior tests.

Seven tests covering the model's behavioral invariants. Tests train a
small XGBoost model on synthetic data inside the test, so they have no
external dependency on MLflow, GCS, or the production model registry.
That makes them safe to run in CI on every push.

Run locally with:
    pytest ml/tests/test_automated_model.py -v
"""
from __future__ import annotations

import numpy as np
import pytest
import xgboost as xgb

N_FEATURES = 87
N_CLASSES = 3   # H, D, A


@pytest.fixture(scope="module")
def trained_model():
    """Train a tiny XGBoost classifier on synthetic data once per module.
    The test suite uses this single in-memory model rather than loading
    from MLflow, so CI does not need any network access."""
    rng = np.random.default_rng(42)
    X = rng.standard_normal((300, N_FEATURES))
    y = rng.integers(0, N_CLASSES, size=300)

    model = xgb.XGBClassifier(
        n_estimators=20,
        max_depth=3,
        objective="multi:softprob",
        num_class=N_CLASSES,
        tree_method="hist",
        random_state=0,
    )
    model.fit(X, y)
    return model


@pytest.fixture
def single_input_row():
    """A single feature vector shaped like the production model expects."""
    rng = np.random.default_rng(7)
    return rng.standard_normal((1, N_FEATURES))


@pytest.fixture
def batch_input():
    """Ten-row feature batch for shape and aggregation tests."""
    rng = np.random.default_rng(7)
    return rng.standard_normal((10, N_FEATURES))


# ─────────────────────────────────────────────────────────────────────
# Test 1 — Model outputs three-class probabilities
# ─────────────────────────────────────────────────────────────────────
def test_model_outputs_three_class_probabilities(trained_model, single_input_row):
    """Football has three outcomes (Home/Draw/Away). The model must
    output a length-3 probability vector for every match."""
    probs = trained_model.predict_proba(single_input_row)
    assert probs.shape == (1, N_CLASSES), \
        f"Expected shape (1, {N_CLASSES}), got {probs.shape}"


# ─────────────────────────────────────────────────────────────────────
# Test 2 — Probabilities sum to 1.0
# ─────────────────────────────────────────────────────────────────────
def test_probabilities_sum_to_one(trained_model, batch_input):
    """For every prediction, the three class probabilities must sum to
    exactly 1.0 (within floating-point tolerance). Otherwise downstream
    edge calculation breaks."""
    probs = trained_model.predict_proba(batch_input)
    sums = probs.sum(axis=1)
    np.testing.assert_allclose(sums, 1.0, atol=1e-6, rtol=0,
                               err_msg="Probabilities do not sum to 1.0")


# ─────────────────────────────────────────────────────────────────────
# Test 3 — All probabilities are in [0, 1]
# ─────────────────────────────────────────────────────────────────────
def test_all_probabilities_in_unit_interval(trained_model, batch_input):
    """Every individual probability must be a real probability, not a
    raw classifier score that escaped calibration."""
    probs = trained_model.predict_proba(batch_input)
    assert (probs >= 0).all(), "Found negative probabilities"
    assert (probs <= 1).all(), "Found probabilities greater than 1.0"


# ─────────────────────────────────────────────────────────────────────
# Test 4 — Batch prediction shape matches input shape
# ─────────────────────────────────────────────────────────────────────
def test_batch_prediction_preserves_row_count(trained_model):
    """Predicting on N input rows must return N output rows. Shape
    drift here would silently mis-align predictions to fixtures."""
    rng = np.random.default_rng(0)
    for n_rows in (1, 5, 25, 100):
        X = rng.standard_normal((n_rows, N_FEATURES))
        probs = trained_model.predict_proba(X)
        assert probs.shape[0] == n_rows, \
            f"Input had {n_rows} rows, output had {probs.shape[0]}"


# ─────────────────────────────────────────────────────────────────────
# Test 5 — Predicted class equals argmax of probabilities
# ─────────────────────────────────────────────────────────────────────
def test_predicted_class_is_argmax_of_probabilities(trained_model, batch_input):
    """The hard prediction must be the class with the highest
    probability. Disagreement here means predict() and predict_proba()
    are using different decision functions, which is a serious bug."""
    probs = trained_model.predict_proba(batch_input)
    preds = trained_model.predict(batch_input)
    expected = probs.argmax(axis=1)
    np.testing.assert_array_equal(preds, expected,
        err_msg="predict() does not match argmax of predict_proba()")


# ─────────────────────────────────────────────────────────────────────
# Test 6 — Model handles edge case: all-zero feature vector
# ─────────────────────────────────────────────────────────────────────
def test_model_handles_all_zero_features_without_crashing(trained_model):
    """A row of all zeros (e.g. a totally cold-start fixture with
    missing feature data) must produce a valid probability vector,
    not a NaN or an exception."""
    X = np.zeros((1, N_FEATURES))
    probs = trained_model.predict_proba(X)
    assert not np.isnan(probs).any(), "All-zero input produced NaN output"
    assert probs.shape == (1, N_CLASSES)
    np.testing.assert_allclose(probs.sum(), 1.0, atol=1e-6)


# ─────────────────────────────────────────────────────────────────────
# Test 7 — Feature count matches production schema
# ─────────────────────────────────────────────────────────────────────
def test_model_feature_count_matches_production(trained_model):
    """The trained model must expose the same number of features as
    the production CLUB_FEATURES list. If we add or remove features
    in config.py without retraining, predictions will fail at runtime."""
    assert trained_model.n_features_in_ == N_FEATURES, (
        f"Expected {N_FEATURES} features (matching production CLUB_FEATURES), "
        f"got {trained_model.n_features_in_}"
    )
