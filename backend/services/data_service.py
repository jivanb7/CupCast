"""
backend/services/data_service.py
==================================
Service for triggering data pipeline operations from the admin API.

These functions run the ML pipeline as subprocesses (not in-process) to
avoid blocking the FastAPI event loop and to keep memory usage bounded.

For MVP, these are triggered synchronously (blocking). The admin API endpoint
wraps them in FastAPI BackgroundTasks so the HTTP response returns immediately.

Functions:
  trigger_data_refresh() → runs ml/run_pipeline.py --mode data-only
  trigger_prediction_generation() → runs ml/run_pipeline.py --mode predict-only
"""

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Walk upward from __file__ until we find the `ml/` package directory. Works for
# both local layout (cupcast/backend/services/…) and the Cloud Run image layout
# (/app/services/… with /app/ml/ alongside), where a fixed `.parent.parent.parent`
# would resolve to `/` and `ml/run_pipeline.py` would appear missing.
PROJECT_ROOT = next(
    (p for p in Path(__file__).resolve().parents if (p / "ml" / "run_pipeline.py").is_file()),
    None,
)
if PROJECT_ROOT is None:
    raise RuntimeError("Could not locate `ml/run_pipeline.py` relative to data_service.py")
ML_PIPELINE_SCRIPT = PROJECT_ROOT / "ml" / "run_pipeline.py"


def _run_pipeline(args: list[str], timeout: int = 3600) -> bool:
    """Run the ML pipeline script as a subprocess. Returns True on success."""
    cmd = [sys.executable, "-m", "ml.run_pipeline"] + args
    logger.info(f"Running pipeline: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            check=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        logger.info(f"Pipeline stdout: {result.stdout[-500:] if result.stdout else ''}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Pipeline failed with exit code {e.returncode}: {e.stderr[-500:] if e.stderr else ''}")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"Pipeline timed out after {timeout}s")
        return False
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        return False


def trigger_data_refresh() -> bool:
    """
    Trigger data ingestion + processing + feature engineering.
    Returns True on success, False on failure.
    """
    return _run_pipeline(["--mode", "data-only"])


def trigger_prediction_generation() -> bool:
    """
    Trigger batch prediction generation for upcoming matches.
    Returns True on success, False on failure.
    """
    return _run_pipeline(["--mode", "predict-only"])


def trigger_retrain(model_type: str = "both") -> bool:
    """
    Trigger model retraining.
    model_type: 'club', 'intl', or 'both'
    Returns True on success, False on failure.
    """
    valid_types = ("club", "intl", "both")
    if model_type not in valid_types:
        logger.error(f"Invalid model_type '{model_type}'. Must be one of {valid_types}")
        return False
    result = _run_pipeline(["--mode", "train-only", "--model-type", model_type])
    if result:
        # Invalidate cached model so next prediction uses the new one
        from services.prediction_service import invalidate_model_cache
        invalidate_model_cache()
    return result
