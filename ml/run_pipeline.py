"""
ml/run_pipeline.py
===================
Top-level orchestration script for the CupCast ML pipeline (SaaS deployment).

Usage:
  # Full pipeline: ingest → process → features → train → predict
  conda run -n ml python -m ml.run_pipeline --mode full

  # Just generate new predictions (skip re-training)
  conda run -n ml python -m ml.run_pipeline --mode predict-only

  # Just ingest + process + features (no training)
  conda run -n ml python -m ml.run_pipeline --mode data-only

  # Train only (uses existing feature files)
  conda run -n ml python -m ml.run_pipeline --mode train-only --model-type club

All pipeline steps are idempotent — it is safe to re-run.
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="CupCast ML Pipeline (SaaS)")
    parser.add_argument(
        "--mode",
        choices=["full", "predict-only", "data-only", "train-only"],
        default="full",
        help="Pipeline mode",
    )
    parser.add_argument(
        "--model-type",
        choices=["club", "intl", "both"],
        default="club",
        help="Which model(s) to train",
    )
    parser.add_argument(
        "--n-trials",
        type=int,
        default=10,
        help="Number of Optuna trials for hyperparameter tuning (default: 10)",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download data even if local files exist",
    )
    args = parser.parse_args()

    mode = args.mode

    # ── Data ingestion + processing + feature engineering ──
    if mode in ("full", "data-only"):
        try:
            logger.info("=== Stage: Data Ingestion ===")
            from ml.src.data_ingestion import run_ingestion
            run_ingestion(force=args.force_download)
        except Exception:
            logger.exception("Data ingestion failed")
            return 1

        try:
            logger.info("=== Stage: Data Processing ===")
            from ml.src.data_processing import run_processing
            run_processing()
        except Exception:
            logger.exception("Data processing failed")
            return 1

        try:
            logger.info("=== Stage: Feature Engineering ===")
            from ml.src.feature_engineering import run_feature_engineering
            run_feature_engineering()
        except Exception:
            logger.exception("Feature engineering failed")
            return 1

    # ── Model training (logs to remote MLflow) ──
    if mode in ("full", "train-only"):
        logger.info("=== Stage: Model Training ===")
        from ml.train_remote import run_training

        if args.model_type in ("club", "both"):
            try:
                logger.info("Training club model...")
                run_training(model_type="club", n_trials=args.n_trials)
            except Exception:
                logger.exception("Club model training failed")
                return 1
        if args.model_type in ("intl", "both"):
            try:
                logger.info("Training international model...")
                run_training(model_type="intl", n_trials=args.n_trials)
            except Exception:
                logger.exception("International model training failed")
                return 1

    # ── Predictions ──
    if mode in ("full", "predict-only"):
        logger.info("=== Stage: Prediction ===")
        try:
            from ml.src.predict import (
                load_production_model,
                batch_predict_upcoming,
                write_predictions_to_db,
            )

            club_model = load_production_model("club")
        except Exception:
            logger.exception("Failed to load club model — cannot generate predictions")
            return 1

        intl_model = None
        try:
            intl_model = load_production_model("intl")
        except Exception:
            logger.warning("International model not available — skipping intl predictions")

        try:
            predictions = batch_predict_upcoming(club_model, intl_model)
            if len(predictions) > 0:
                write_predictions_to_db(
                    predictions,
                    db_url="",  # Empty = auto-detect from backend config
                    model_version="latest",
                )
                logger.info("Wrote %d predictions", len(predictions))
            else:
                logger.warning("No predictions generated (missing fixtures?)")
        except Exception:
            logger.exception("Prediction generation failed")
            return 1

    logger.info("Pipeline complete (mode=%s)", mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
