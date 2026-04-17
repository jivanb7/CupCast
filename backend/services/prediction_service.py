"""
backend/services/prediction_service.py
========================================
Business logic for loading models and generating predictions.

Responsibilities:
  - Lazy-load the production model artifacts at first use (not at startup)
  - Run inference on upcoming scheduled matches
  - Compute bookmaker edge via edge_service
  - Upsert prediction results into the predictions table

Model loading:
  Models are cached as module-level singletons after first load.
  Loaded from ml/models/{model_name}_best.joblib using joblib.

Integration with ML module:
  Uses joblib directly to load the trained XGBClassifier artifacts.
  Does NOT import from ml.src.predict to avoid cross-module path issues.
  The feature engineering is handled by importing the ml module directly.
"""

import logging
import sys
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Add project root to sys.path so we can import ml.src modules with full package path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # cupcast/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
ML_DIR = PROJECT_ROOT / "ml"

MODELS_DIR = ML_DIR / "models"
PROCESSED_DIR = ML_DIR / "data" / "processed"

# Canonical model file names (must match what ml-engineer saves)
CLUB_MODEL_FILENAME = "cupcast-club-model_best.joblib"
CLUB_TOP5_MODEL_FILENAME = "cupcast-club-top5_best.joblib"
INTL_MODEL_FILENAME = "cupcast-international-model_best.joblib"

# Map backend DB league codes → ML pipeline league codes
DB_TO_ML_LEAGUE = {
    "epl": "E0", "championship": "E1", "league_one": "E2",
    "league_two": "E3", "national_league": "EC",
    "laliga": "SP1", "seriea": "I1", "bundesliga": "D1",
    "ligue1": "F1", "ucl": "UCL",
}

# Top 5 leagues use the specialist model
TOP5_ML_CODES = {"E0", "SP1", "I1", "D1", "F1", "UCL"}

# Module-level model cache
_club_model = None
_club_top5_model = None
_intl_model = None
_club_matches_df = None  # Cached historical match data for feature engineering


def invalidate_model_cache():
    """Clear cached models and data so next request loads fresh artifacts. Call after retrain."""
    global _club_model, _club_top5_model, _intl_model, _club_matches_df
    _club_model = None
    _club_top5_model = None
    _intl_model = None
    _club_matches_df = None
    logger.info("Model cache invalidated — next prediction will load fresh model from disk")


def get_club_model(league_code: str = "E0"):
    """Lazy-load the appropriate club model based on league.

    Routes top 5 leagues (EPL, La Liga, Serie A, Bundesliga, Ligue 1, UCL)
    to a specialist model trained on those leagues only. Lower English leagues
    use the general model trained on all leagues.
    """
    global _club_model, _club_top5_model

    if league_code in TOP5_ML_CODES:
        if _club_top5_model is None:
            model_path = MODELS_DIR / CLUB_TOP5_MODEL_FILENAME
            if model_path.exists():
                import joblib
                _club_top5_model = joblib.load(model_path)
                logger.info("Loaded top5 specialist model from %s", model_path)
            else:
                logger.warning("Top5 model not found at %s, falling back to general", model_path)
                return _load_general_club_model()
        return _club_top5_model

    return _load_general_club_model()


def _load_general_club_model():
    """Load the general club model (all leagues)."""
    global _club_model
    if _club_model is None:
        model_path = MODELS_DIR / CLUB_MODEL_FILENAME
        if not model_path.exists():
            raise FileNotFoundError(
                f"Club model not found at {model_path}. "
                "Run the ML training pipeline first."
            )
        import joblib
        _club_model = joblib.load(model_path)
        logger.info("Loaded general club model from %s", model_path)
    return _club_model


def get_intl_model():
    """Lazy-load the production international model from disk."""
    global _intl_model
    if _intl_model is None:
        model_path = MODELS_DIR / INTL_MODEL_FILENAME
        if not model_path.exists():
            raise FileNotFoundError(
                f"International model not found at {model_path}. "
                "Run the ML training pipeline first."
            )
        import joblib
        _intl_model = joblib.load(model_path)
        logger.info("Loaded international model from %s", model_path)
    return _intl_model


def generate_batch_predictions(db) -> int:
    """
    Run batch inference on all upcoming scheduled matches.

    OPTIMIZED: Builds the feature matrix ONCE with all upcoming matches appended
    to historical data, then runs inference on all matches in one pass per model.
    Previously took ~4 min per match (Dixon-Coles refit each time); now takes
    ~5 min total regardless of match count.

    Process:
      1. Load historical data + append all upcoming matches as dummy rows
      2. Build feature matrix once (single Dixon-Coles fit)
      3. Extract feature rows for upcoming matches
      4. Route to appropriate model (top5 vs general) and predict
      5. Upsert predictions into DB
    """
    import numpy as np
    import pandas as pd

    from models.league import League
    from models.match import Match
    from models.prediction import Prediction
    from models.team import Team
    from services.edge_service import compute_edge

    try:
        from ml.src.config import CLUB_FEATURES, INT_TO_RESULT
    except ImportError:
        INT_TO_RESULT = {0: "H", 1: "D", 2: "A"}
        raise ImportError("Cannot import ml.src.config — required for predictions")

    # Load historical match data (cached)
    global _club_matches_df
    club_matches_path = PROCESSED_DIR / "club_matches.parquet"
    if _club_matches_df is None:
        if not club_matches_path.exists():
            raise FileNotFoundError(f"club_matches.parquet not found at {club_matches_path}")
        _club_matches_df = pd.read_parquet(club_matches_path)
        logger.info("Loaded club_matches.parquet (%d rows)", len(_club_matches_df))

    try:
        from ml.src.feature_engineering import build_feature_matrix
    except ImportError as e:
        raise ImportError(f"Cannot import feature engineering: {e}")

    # Fetch upcoming scheduled matches
    today = date.today()
    scheduled = (
        db.query(Match)
        .filter(Match.status == "scheduled", Match.match_date >= today)
        .order_by(Match.match_date)
        .all()
    )
    if not scheduled:
        logger.info("No upcoming scheduled matches to predict")
        return 0

    # Preload teams and leagues
    team_ids = list({m.home_team_id for m in scheduled} | {m.away_team_id for m in scheduled})
    teams_by_id = {t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()}
    league_ids = list({m.league_id for m in scheduled if m.league_id})
    leagues_by_id = {lg.id: lg for lg in db.query(League).filter(League.id.in_(league_ids)).all()}

    # ── Step 1: Build dummy rows for ALL upcoming matches ──
    upcoming_rows = []
    match_index_map = {}  # maps position in upcoming_rows → Match ORM object

    for match in scheduled:
        home_team = teams_by_id.get(match.home_team_id)
        away_team = teams_by_id.get(match.away_team_id)
        if not home_team or not away_team:
            continue

        league = leagues_by_id.get(match.league_id)
        db_league_code = league.code if league else "epl"
        ml_league_code = DB_TO_ML_LEAGUE.get(db_league_code, "E0")

        upcoming_rows.append({
            "match_date": pd.Timestamp(match.match_date),
            "home_team": home_team.canonical_name,
            "away_team": away_team.canonical_name,
            "home_goals": 0, "away_goals": 0,
            "result": "H", "result_encoded": 0,  # Dummy — won't be used
            "league_code": ml_league_code,
            "season": "2025-26",
            "ht_home_goals": 0, "ht_away_goals": 0,
            "home_shots": 0, "away_shots": 0,
            "home_shots_on_target": 0, "away_shots_on_target": 0,
            "home_corners": 0, "away_corners": 0,
            "home_fouls": 0, "away_fouls": 0,
            "home_yellow_cards": 0, "away_yellow_cards": 0,
            "home_red_cards": 0, "away_red_cards": 0,
            "odds_home": None, "odds_draw": None, "odds_away": None,
        })
        match_index_map[len(upcoming_rows) - 1] = (match, ml_league_code)

    if not upcoming_rows:
        logger.info("No valid upcoming matches (teams not resolved)")
        return 0

    logger.info("Building feature matrix for %d upcoming + %d historical matches...",
                len(upcoming_rows), len(_club_matches_df))

    # ── Step 2: Build feature matrix ONCE ──
    upcoming_df = pd.DataFrame(upcoming_rows)
    combined = pd.concat([_club_matches_df, upcoming_df], ignore_index=True)

    feature_df = build_feature_matrix(combined, model_type="club")

    # The last N rows correspond to our upcoming matches
    n_historical = len(_club_matches_df)
    n_upcoming = len(upcoming_rows)

    # feature_df may have fewer rows if some were dropped (NaN result_encoded)
    # We tagged upcoming matches with result_encoded=0, so they survive dropna.
    # Find them by matching on the tail of the dataframe.
    # Since we appended upcoming after historical, they'll be the last rows
    # whose match_date matches our upcoming dates.
    upcoming_features = feature_df.tail(n_upcoming).copy()

    if len(upcoming_features) != n_upcoming:
        logger.warning("Feature matrix returned %d rows for %d upcoming matches — adjusting",
                        len(upcoming_features), n_upcoming)
        # Fall back: match by home_team + away_team + match_date
        upcoming_features = feature_df[
            feature_df["match_date"].isin(upcoming_df["match_date"].unique()) &
            feature_df["home_team"].isin(upcoming_df["home_team"].unique())
        ].tail(n_upcoming)

    logger.info("Got features for %d upcoming matches", len(upcoming_features))

    # ── Step 3: Predict in batch per model group ──
    model_version = "v2.0.0-routed"
    count = 0
    skipped = 0

    for idx, (match, ml_league_code) in match_index_map.items():
        if idx >= len(upcoming_features):
            skipped += 1
            continue

        try:
            feature_row = upcoming_features.iloc[idx]

            # Route to appropriate model
            club_model = get_club_model(ml_league_code)
            feature_names = list(club_model.feature_names_in_)

            # Extract features the model expects
            available = [f for f in feature_names if f in feature_row.index]
            if len(available) < len(feature_names) * 0.8:
                skipped += 1
                continue

            X = feature_row[available].values.reshape(1, -1).astype(float)
            X = np.nan_to_num(X, nan=0.0)

            if X.shape[1] != len(feature_names):
                skipped += 1
                continue

            probs = club_model.predict_proba(X)[0]
            pred_class = int(np.argmax(probs))
            predicted_result = INT_TO_RESULT.get(pred_class, "H")
            confidence = float(probs[pred_class])

            edge_result = compute_edge(
                prob_home=float(probs[0]),
                prob_draw=float(probs[1]),
                prob_away=float(probs[2]),
                odds_home=None, odds_draw=None, odds_away=None,
            )

            # Upsert
            existing = db.query(Prediction).filter(
                Prediction.match_id == match.id,
                Prediction.model_version == model_version,
            ).first()

            pred_data = dict(
                match_id=match.id,
                model_version=model_version,
                prob_home_win=float(probs[0]),
                prob_draw=float(probs[1]),
                prob_away_win=float(probs[2]),
                predicted_result=predicted_result,
                confidence=confidence,
                is_value_pick=edge_result.is_value_pick if edge_result else False,
                value_pick_direction=edge_result.value_pick_direction if edge_result else None,
                edge_home=edge_result.edge_home if edge_result else None,
                edge_draw=edge_result.edge_draw if edge_result else None,
                edge_away=edge_result.edge_away if edge_result else None,
            )

            if existing:
                for k, v in pred_data.items():
                    setattr(existing, k, v)
            else:
                db.add(Prediction(**pred_data))

            count += 1

        except Exception as e:
            logger.warning("Failed to predict match %d: %s", match.id, e)
            skipped += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to commit predictions: %s", e)
        raise

    logger.info("Generated %d predictions, skipped %d (batch mode)", count, skipped)
    return count
