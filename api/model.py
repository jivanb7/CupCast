"""
Model loading from MLflow Model Registry (with local fallback).

Strategy:
  1. Try loading from MLflow Model Registry (requires network access to tracking server)
  2. Fall back to local joblib file (bundled in Docker image for self-contained deployment)
"""

import logging
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from api.schemas import REQUIRED_FEATURES

logger = logging.getLogger(__name__)

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://34.58.128.38:5000")
MODEL_NAME = "cupcast-club-model"
MODEL_VERSION = os.getenv("MODEL_VERSION", "1")
LOCAL_MODEL_PATH = Path(__file__).resolve().parent.parent / "ml" / "models" / "cupcast-club_best.joblib"
RESULT_LABELS = {0: "H", 1: "D", 2: "A"}

# Module-level state
_model = None
_model_version = MODEL_VERSION


def load_model():
    """Load the model from MLflow Model Registry, falling back to local joblib."""
    global _model, _model_version

    # Try MLflow Model Registry first
    try:
        import mlflow
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        model_uri = f"models:/{MODEL_NAME}/{MODEL_VERSION}"
        logger.info("Attempting to load model from MLflow: %s", model_uri)
        _model = mlflow.xgboost.load_model(model_uri)
        _model_version = MODEL_VERSION
        logger.info("Model loaded from MLflow Model Registry: %s v%s", MODEL_NAME, _model_version)
        return
    except Exception as e:
        logger.warning("MLflow load failed (%s), falling back to local file", e)

    # Fall back to local joblib file
    if LOCAL_MODEL_PATH.exists():
        logger.info("Loading model from local file: %s", LOCAL_MODEL_PATH)
        _model = joblib.load(LOCAL_MODEL_PATH)
        _model_version = MODEL_VERSION
        logger.info("Model loaded from local file successfully")
    else:
        raise FileNotFoundError(f"No model found at MLflow or {LOCAL_MODEL_PATH}")


def get_model():
    """Return the loaded model, or None if not yet loaded."""
    return _model


def get_model_version() -> str:
    return _model_version


def predict(features: dict[str, float]) -> dict:
    """
    Run prediction on a single match's features.

    Returns dict with prediction label and class probabilities.
    """
    if _model is None:
        raise RuntimeError("Model not loaded")

    # Build a single-row DataFrame in the exact feature order the model expects
    df = pd.DataFrame([{f: features[f] for f in REQUIRED_FEATURES}])
    probabilities = _model.predict_proba(df)[0]
    predicted_class = int(np.argmax(probabilities))

    return {
        "prediction": RESULT_LABELS[predicted_class],
        "probabilities": {
            "home_win": round(float(probabilities[0]), 4),
            "draw": round(float(probabilities[1]), 4),
            "away_win": round(float(probabilities[2]), 4),
        },
        "model_name": MODEL_NAME,
        "model_version": _model_version,
    }
