"""
ml/src/predict.py
==================
Load production model artifacts and run inference on upcoming matches.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.src.config import (
    CLUB_FEATURES,
    FEATURES_DIR,
    INT_TO_RESULT,
    INTL_FEATURES,
    MLFLOW_MODEL_NAME_CLUB,
    MLFLOW_MODEL_NAME_INTL,
    MODELS_DIR,
    PROCESSED_DIR,
    VALUE_PICK_EDGE_THRESHOLD,
)
from ml.src.feature_engineering import build_feature_matrix

logger = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    prob_home_win: float
    prob_draw: float
    prob_away_win: float
    predicted_result: str          # 'H', 'D', or 'A'
    confidence: float              # max probability
    edge_home: float | None = None
    edge_draw: float | None = None
    edge_away: float | None = None
    is_value_pick: bool = False
    value_pick_direction: str | None = None


def load_production_model(model_type: str = "club"):
    """
    Load the production model artifact.
    Tries local joblib first, then MLFlow registry.
    """
    model_name = MLFLOW_MODEL_NAME_CLUB if model_type == "club" else MLFLOW_MODEL_NAME_INTL
    local_path = MODELS_DIR / f"{model_name}_best.joblib"

    if local_path.exists():
        model = joblib.load(local_path)
        logger.info("Loaded %s model from %s", model_type, local_path)
        return model

    # Fallback: try MLFlow registry. Uses the modern @prod alias syntax —
    # the legacy `/Production` stage label was deprecated in MLflow 3.x and
    # raises 404 even when an alias is set. Stay aligned with the backend's
    # prediction_service.py which also resolves models via @prod.
    try:
        import mlflow
        model = mlflow.pyfunc.load_model(f"models:/{model_name}@prod")
        logger.info("Loaded %s model from MLFlow registry via @prod alias", model_type)
        return model
    except Exception as e:
        logger.error("Failed to load %s model: %s", model_type, e)
        raise


def predict_match(
    features_row: pd.Series | pd.DataFrame,
    model,
) -> PredictionResult:
    """Run inference on a single match feature row."""
    if isinstance(features_row, pd.Series):
        X = features_row.values.reshape(1, -1)
    else:
        X = features_row.values if len(features_row.shape) == 2 else features_row.values.reshape(1, -1)

    probs = model.predict_proba(X)[0]
    pred_class = int(np.argmax(probs))

    return PredictionResult(
        prob_home_win=float(probs[0]),
        prob_draw=float(probs[1]),
        prob_away_win=float(probs[2]),
        predicted_result=INT_TO_RESULT[pred_class],
        confidence=float(probs[pred_class]),
    )


def compute_bookmaker_edge(
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    odds_home: float | None,
    odds_draw: float | None,
    odds_away: float | None,
) -> dict:
    """Compute the edge between model probabilities and bookmaker implied probabilities."""
    result = {
        "edge_home": None, "edge_draw": None, "edge_away": None,
        "is_value_pick": False, "value_pick_direction": None,
    }

    if odds_home is None or odds_draw is None or odds_away is None:
        return result
    if any(o <= 0 or pd.isna(o) for o in [odds_home, odds_draw, odds_away]):
        return result

    # Compute implied probabilities (normalized for the vig/overround)
    raw_probs = [1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away]
    total = sum(raw_probs)
    implied_home = raw_probs[0] / total
    implied_draw = raw_probs[1] / total
    implied_away = raw_probs[2] / total

    result["edge_home"] = prob_home - implied_home
    result["edge_draw"] = prob_draw - implied_draw
    result["edge_away"] = prob_away - implied_away

    # Check for value pick
    max_edge = max(result["edge_home"], result["edge_draw"], result["edge_away"])
    if max_edge > VALUE_PICK_EDGE_THRESHOLD:
        result["is_value_pick"] = True
        if result["edge_home"] == max_edge:
            result["value_pick_direction"] = "H"
        elif result["edge_draw"] == max_edge:
            result["value_pick_direction"] = "D"
        else:
            result["value_pick_direction"] = "A"

    return result


def batch_predict_upcoming(
    club_model,
    intl_model=None,
) -> pd.DataFrame:
    """
    Generate predictions for all upcoming scheduled matches.
    """
    fixtures_path = PROCESSED_DIR / "fixtures.parquet"
    if not fixtures_path.exists():
        logger.warning("No fixtures.parquet found")
        return pd.DataFrame()

    fixtures = pd.read_parquet(fixtures_path)
    if len(fixtures) == 0:
        logger.warning("No upcoming fixtures to predict")
        return pd.DataFrame()

    logger.info("Generating predictions for %d upcoming fixtures", len(fixtures))

    # Load historical data for feature computation context
    club_matches = pd.read_parquet(PROCESSED_DIR / "club_matches.parquet")

    # Append ALL fixtures at once (with dummy goals) and build features in one pass
    # This avoids calling build_feature_matrix N times (which refits Dixon-Coles each time)
    fixture_rows = []
    for _, fixture in fixtures.iterrows():
        fixture_rows.append({
            "match_date": fixture["match_date"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "home_goals": 0,
            "away_goals": 0,
            "result": "H",  # Dummy — ignored in rolling features due to shift(1)
            "result_encoded": 0,
            "league_code": fixture.get("league_code", "E0"),
            "season": "2025-26",
        })

    temp_fixtures = pd.DataFrame(fixture_rows)
    combined = pd.concat([club_matches, temp_fixtures], ignore_index=True)

    # Build features ONCE for the entire dataset
    logger.info("Building feature matrix for %d matches (including %d fixtures)...",
                len(combined), len(temp_fixtures))
    feature_df = build_feature_matrix(combined, model_type="club")

    if len(feature_df) == 0:
        logger.warning("No features generated")
        return pd.DataFrame()

    # Extract features for just the appended fixture rows (last N rows)
    n_fixtures = len(temp_fixtures)
    fixture_features = feature_df.tail(n_fixtures)

    predictions = []
    for i, (_, fixture) in enumerate(fixtures.iterrows()):
        try:
            if i >= len(fixture_features):
                continue
            feature_row = fixture_features.iloc[i]
            X = feature_row[CLUB_FEATURES].values.reshape(1, -1).astype(float)

            # Replace NaN with 0 for prediction
            X = np.nan_to_num(X, nan=0.0)

            probs = club_model.predict_proba(X)[0]
            pred_class = int(np.argmax(probs))

            # Bookmaker edge
            edge = compute_bookmaker_edge(
                probs[0], probs[1], probs[2],
                fixture.get("odds_home"), fixture.get("odds_draw"), fixture.get("odds_away"),
            )

            predictions.append({
                "match_date": fixture["match_date"],
                "home_team": fixture["home_team"],
                "away_team": fixture["away_team"],
                "league_code": fixture.get("league_code", ""),
                "prob_home": float(probs[0]),
                "prob_draw": float(probs[1]),
                "prob_away": float(probs[2]),
                "predicted_result": INT_TO_RESULT[pred_class],
                "confidence": float(probs[pred_class]),
                **edge,
            })
        except Exception as e:
            logger.warning("Failed to predict %s vs %s: %s",
                          fixture["home_team"], fixture["away_team"], e)
            continue

    result_df = pd.DataFrame(predictions)
    if len(result_df) > 0:
        logger.info(
            "Generated %d predictions. Value picks: %d",
            len(result_df),
            result_df["is_value_pick"].sum() if "is_value_pick" in result_df else 0,
        )
    return result_df


def write_predictions_to_db(
    predictions_df: pd.DataFrame,
    db_url: str,
    model_version: str,
) -> int:
    """
    Write batch predictions to the database predictions table.

    Uses the backend's SQLAlchemy models to upsert predictions.
    Falls back to CSV if the database is not reachable.
    """
    import sys as _sys
    from pathlib import Path as _Path

    if predictions_df is None or len(predictions_df) == 0:
        logger.warning("No predictions to write")
        return 0

    # Always save CSV as a backup/debug artifact first
    out_path = PROCESSED_DIR / "predictions.csv"
    try:
        predictions_df["model_version"] = model_version
        predictions_df.to_csv(out_path, index=False)
        logger.info("Saved predictions CSV to %s", out_path)
    except Exception as e:
        logger.error("Failed to save predictions CSV: %s", e)
        # If CSV save fails, try an alternative location
        try:
            fallback_path = _Path("/tmp/cupcast_predictions.csv")
            predictions_df.to_csv(fallback_path, index=False)
            logger.info("Saved predictions CSV to fallback %s", fallback_path)
        except Exception:
            logger.error("Failed to save predictions CSV to any location")

    # Try writing to the actual database
    session = None
    try:
        # Add backend to path so we can import its models
        backend_dir = str(_Path(__file__).resolve().parent.parent.parent / "backend")
        if backend_dir not in _sys.path:
            _sys.path.insert(0, backend_dir)

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        # Resolve DB URL: explicit arg > backend config > give up
        _url = db_url if db_url else None
        if not _url:
            try:
                from config import settings
                _url = settings.database_url
            except Exception as e:
                logger.warning("Could not load backend config for DB URL: %s", e)
                logger.info("Predictions saved to CSV only (no database configured)")
                return 0

        if not _url:
            logger.warning("No database URL available — predictions saved to CSV only")
            return 0

        from models.prediction import Prediction
        from models.match import Match
        from models.team import Team

        if _url.startswith("sqlite"):
            eng = create_engine(_url, connect_args={"check_same_thread": False})
        else:
            eng = create_engine(_url)

        # Test connection before proceeding
        eng.connect().close()

        Session = sessionmaker(bind=eng)
        session = Session()

        # Build team lookup: canonical_name -> team_id
        team_lookup = {t.canonical_name: t.id for t in session.query(Team).all()}

        count = 0
        skipped_teams = set()
        skipped_matches = 0
        for _, row in predictions_df.iterrows():
            home_name = row.get("home_team", "")
            away_name = row.get("away_team", "")

            try:
                match_date = pd.to_datetime(row.get("match_date")).date()
            except Exception:
                logger.warning("Invalid match_date for %s vs %s, skipping", home_name, away_name)
                continue

            home_id = team_lookup.get(home_name)
            away_id = team_lookup.get(away_name)
            if not home_id:
                skipped_teams.add(home_name)
                continue
            if not away_id:
                skipped_teams.add(away_name)
                continue

            # Find the match in the DB
            match = (
                session.query(Match)
                .filter(
                    Match.home_team_id == home_id,
                    Match.away_team_id == away_id,
                    Match.match_date == match_date,
                )
                .first()
            )
            if not match:
                skipped_matches += 1
                continue

            # Upsert: update if exists, insert if new
            existing = (
                session.query(Prediction)
                .filter(
                    Prediction.match_id == match.id,
                    Prediction.model_version == model_version,
                )
                .first()
            )

            predicted_result = row.get("predicted_result", "H")
            pred_data = dict(
                match_id=match.id,
                model_version=model_version,
                prob_home_win=float(row.get("prob_home", 0)),
                prob_draw=float(row.get("prob_draw", 0)),
                prob_away_win=float(row.get("prob_away", 0)),
                predicted_result=predicted_result,
                confidence=float(row.get("confidence", 0)),
                is_value_pick=bool(row.get("is_value_pick", False)),
                value_pick_direction=row.get("value_pick_direction"),
                edge_home=row.get("edge_home"),
                edge_draw=row.get("edge_draw"),
                edge_away=row.get("edge_away"),
            )

            # Set was_correct if match already has a result
            if match.result:
                pred_data["was_correct"] = (predicted_result == match.result)

            if existing:
                for k, v in pred_data.items():
                    setattr(existing, k, v)
            else:
                session.add(Prediction(**pred_data))
            count += 1

        session.commit()
        if skipped_teams:
            logger.warning("Teams not found in DB: %s", sorted(skipped_teams))
        if skipped_matches > 0:
            logger.warning("Matches not found in DB for %d predictions", skipped_matches)
        logger.info("Wrote %d predictions to database", count)
        return count

    except Exception as e:
        logger.warning("Could not write to database (CSV saved as fallback): %s", e)
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
        return 0
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
