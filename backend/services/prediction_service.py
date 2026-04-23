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
  Loaded on first access via `mlflow.<flavor>.load_model("models:/<name>@prod")`.
  MLflow resolves the `prod` alias to the current version, then downloads
  the artifact from the registry's GCS backend.

  This gives us autonomous promotion: retraining → `mlflow models set-alias
  prod <new_version>` → call POST /admin/models/reload on Cloud Run. No
  env-var edits, no redeploy.

  The tracking server is fronted by Caddy (HTTPS + basic auth) so Cloud Run
  can reach it over the public internet with MLFLOW_TRACKING_USERNAME /
  MLFLOW_TRACKING_PASSWORD creds, while the raw MLflow port stays firewalled
  to admin IPs only.

Integration with ML module:
  Feature engineering still lives in ml.src and is imported directly.
"""

import logging
import sys
import threading
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Guards concurrent mutation of module-level model/data caches. Acquired by
# invalidate_model_cache() (admin retrain thread) and any code path that
# reads/writes _club_model, _club_top5_model, _intl_model, _club_matches_df.
_cache_lock = threading.Lock()

# Locate the `ml` package directory. Two supported layouts:
#   * Local dev:   cupcast/backend/services/prediction_service.py  → project root is parents[2]
#   * Cloud Run:   /app/services/prediction_service.py             → /app is parents[1]
# Walk upward from __file__ until we find a directory containing `ml/src/config.py`.
_PKG_CANDIDATE = next(
    (p for p in Path(__file__).resolve().parents if (p / "ml" / "src" / "config.py").is_file()),
    None,
)
if _PKG_CANDIDATE is None:
    raise RuntimeError("Could not locate the `ml` package relative to prediction_service.py")
PROJECT_ROOT = _PKG_CANDIDATE
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.src.config import ML_DIR, PROCESSED_DIR  # noqa: E402

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
    with _cache_lock:
        _club_model = None
        _club_top5_model = None
        _intl_model = None
        _club_matches_df = None
    logger.info("Model cache invalidated — next prediction will reload from MLflow registry")


def _load_from_registry(model_name: str, flavor: str):
    """Pull a model from the MLflow registry via its `prod` alias.

    `flavor` picks the correct loader — sklearn and xgboost produce different
    on-disk formats, and calling the wrong one raises an unpickling error.
    The URI `models:/<name>@prod` tells MLflow to resolve the `prod` alias
    to a concrete version at load time, then fetch its artifact from the
    registry's backing store (GCS in our case).
    """
    if not model_name:
        raise RuntimeError(
            "Registered model name is not configured. Set "
            "MLFLOW_MODEL_CLUB / _TOP5 / _INTL in the backend environment."
        )
    # Imported lazily so local tooling that never hits inference (alembic,
    # admin scripts) doesn't pay the mlflow import cost.
    import mlflow.sklearn
    import mlflow.xgboost

    loader = mlflow.sklearn if flavor == "sklearn" else mlflow.xgboost
    uri = f"models:/{model_name}@prod"
    model = loader.load_model(uri)
    logger.info("Loaded %s model from %s", flavor, uri)
    return model


def get_club_model(league_code: str = "E0"):
    """Lazy-load the appropriate club model based on league.

    Routes top 5 leagues (EPL, La Liga, Serie A, Bundesliga, Ligue 1, UCL)
    to a specialist model trained on those leagues only. Lower English leagues
    use the general model trained on all leagues.
    """
    global _club_top5_model

    if league_code in TOP5_ML_CODES:
        if _club_top5_model is None:
            from config import settings
            with _cache_lock:
                # Double-check after acquiring the lock — another thread may
                # have loaded it while we were waiting.
                if _club_top5_model is None:
                    # Top5 is a CalibratedClassifierCV wrapping an XGBoost booster,
                    # so the mlflow flavor is sklearn (CalibratedClassifierCV is
                    # sklearn-native, even though the inner estimator is xgb).
                    _club_top5_model = _load_from_registry(
                        settings.mlflow_model_club_top5, flavor="sklearn"
                    )
        return _club_top5_model

    return _load_general_club_model()


def _load_general_club_model():
    """Load the general club model (all leagues)."""
    global _club_model
    if _club_model is None:
        from config import settings
        with _cache_lock:
            if _club_model is None:
                _club_model = _load_from_registry(
                    settings.mlflow_model_club, flavor="sklearn"
                )
    return _club_model


def get_intl_model():
    """Lazy-load the production international (XGBoost) model."""
    global _intl_model
    if _intl_model is None:
        from config import settings
        with _cache_lock:
            if _intl_model is None:
                _intl_model = _load_from_registry(
                    settings.mlflow_model_intl, flavor="xgboost"
                )
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
    except ImportError as e:
        # Surface the real underlying cause — without it a missing submodule
        # or bad PYTHONPATH produces an undiagnosable 500.
        raise ImportError(f"Cannot import ml.src.config: {e}") from e

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
        raise ImportError(f"Cannot import feature engineering: {e}") from e

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

    # Batch-fetch all existing predictions for these matches to avoid N+1 queries
    # inside the upsert loop below. Build a (match_id, model_version) lookup.
    _pred_match_ids = [m.id for (m, _) in match_index_map.values()]
    _existing_preds = (
        db.query(Prediction)
        .filter(
            Prediction.match_id.in_(_pred_match_ids),
            Prediction.model_version == model_version,
        )
        .all()
        if _pred_match_ids
        else []
    )
    existing_by_match = {p.match_id: p for p in _existing_preds}

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

            # Upsert — use batched lookup to avoid N+1 query per match
            existing = existing_by_match.get(match.id)

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
