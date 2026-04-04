"""
CupCast Prediction API

FastAPI service that serves match outcome predictions from the
XGBoost model registered in MLflow Model Registry.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from api.model import get_model, get_model_version, load_model, predict, MODEL_NAME
from api.schemas import (
    HealthResponse,
    PredictRequest,
    PredictResponse,
    REQUIRED_FEATURES,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the model at startup."""
    logger.info("Loading model from MLflow Model Registry...")
    try:
        load_model()
        logger.info("Model loaded successfully.")
    except Exception:
        logger.exception("Failed to load model at startup")
    yield


app = FastAPI(
    title="CupCast Prediction API",
    description="Football match outcome predictions using XGBoost trained on club league data.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
def root():
    """Welcome endpoint."""
    return {
        "service": "CupCast Prediction API",
        "description": "Football match outcome predictions (Home Win / Draw / Away Win)",
        "endpoints": {
            "/": "This message",
            "/health": "Service health check",
            "/predict": "POST match features to get a prediction",
            "/docs": "Interactive API documentation",
        },
    }


@app.get("/health", response_model=HealthResponse)
def health():
    """Health check — confirms the model is loaded and ready."""
    model = get_model()
    return HealthResponse(
        status="healthy" if model is not None else "unhealthy",
        model_loaded=model is not None,
        model_name=MODEL_NAME,
        model_version=get_model_version(),
    )


@app.post("/predict", response_model=PredictResponse)
def predict_match(request: PredictRequest):
    """
    Predict the outcome of a football match.

    Accepts a dictionary of 72 features and returns the predicted result
    (H/D/A) with class probabilities.
    """
    if get_model() is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    # Validate all required features are present
    missing = set(REQUIRED_FEATURES) - set(request.features.keys())
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing {len(missing)} required features: {sorted(missing)[:10]}{'...' if len(missing) > 10 else ''}",
        )

    result = predict(request.features)
    return PredictResponse(**result)
