"""
backend/api/admin.py
=====================
Internal/admin endpoints for triggering pipeline operations.

ALL endpoints in this router require the ADMIN_API_KEY header:
  X-Admin-Key: <value from ADMIN_API_KEY env var>

Return 403 Forbidden if key is missing or incorrect.

Endpoints:
  POST /admin/data/refresh
    Triggers: ML data ingestion + processing + feature engineering
    Returns: {"status": "started"} (fires background task)

  POST /admin/model/retrain
    Query params: model_type ('club' | 'intl' | 'both', default 'both')
    Triggers: Model training pipeline
    Returns: {"status": "started"}

  POST /admin/predictions/generate
    Triggers: Load production model, run inference on upcoming matches, store
    Returns: {"status": "done", "predictions_generated": N}

Security note:
  Protected by a static API key for MVP. In production, these should
  be triggered by GitHub Actions using a secrets-stored key, never exposed to
  the public internet.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from config import settings
from database import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


def verify_admin_key(x_admin_key: str = Header(...)):
    """FastAPI dependency: verify the admin API key header."""
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return x_admin_key


@router.post("/scores/update")
def update_scores(
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Fetch latest scores from football-data.co.uk and update match results."""
    from services.score_updater import update_scores as do_update

    try:
        stats = do_update(db)
        return {"status": "done", **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Score update failed: {str(e)}")


@router.post("/data/refresh")
def refresh_data(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Trigger data ingestion and processing pipeline as a background task."""
    from services.data_service import trigger_data_refresh

    background_tasks.add_task(trigger_data_refresh)
    return {"status": "started", "message": "Data refresh pipeline started in background"}


@router.post("/model/retrain")
def retrain_model(
    background_tasks: BackgroundTasks,
    model_type: str = "both",
    _key: str = Depends(verify_admin_key),
):
    """Trigger model retraining for one or both model types."""
    from services.data_service import trigger_retrain

    valid_types = ("club", "intl", "both")
    if model_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid model_type '{model_type}'. Must be one of {valid_types}",
        )

    background_tasks.add_task(trigger_retrain, model_type)
    return {"status": "started", "model_type": model_type, "message": "Retraining started"}


@router.post("/predictions/generate")
def generate_predictions(
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Run batch inference on upcoming matches and store predictions."""
    from services.prediction_service import generate_batch_predictions

    try:
        n = generate_batch_predictions(db)
        return {"status": "done", "predictions_generated": n}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction generation failed: {str(e)}")


@router.post("/fixtures/seed")
def seed_fixtures(
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Fetch upcoming fixtures from Football-Data.org + fixtures.csv and seed into DB."""
    from services.fixture_seeder import seed_all_fixtures

    try:
        stats = seed_all_fixtures(db)
        return {"status": "done", **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fixture seeding failed: {str(e)}")


@router.post("/players/refresh")
def refresh_all_players(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Refresh top scorers and injuries for all leagues.

    Fetches /players/topscorers and /injuries from API-Football for each of
    the 10 tracked leagues (~20 API calls total). Runs synchronously and returns
    counts when complete.
    """
    from services.player_availability_service import refresh_all_leagues

    try:
        result = refresh_all_leagues(db)
        return {"status": "done", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Player refresh failed: {str(e)}")


@router.post("/odds/refresh")
def refresh_all_odds(
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Refresh bookmaker odds + value-pick flags for upcoming matches in all leagues.

    Fetches /fixtures + /odds from API-Football for each league, matches fixtures
    to DB matches, and upserts odds_home/draw/away + recomputed edges onto every
    Prediction row. Runs synchronously and returns counts.

    API cost: ~5 calls per league (1 fixtures + ~4 odds pages) = ~50 calls total.

    Expected schedule (Cloud Scheduler, both UTC):
      - 07:30 daily — after prediction refresh at 07:00
      - 15:00 daily — mid-day top-up for late-priced matches
    """
    from services.odds_service import refresh_all_leagues_odds

    try:
        result = refresh_all_leagues_odds(db)
        return {"status": "done", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Odds refresh failed: {str(e)}")


@router.post("/odds/refresh/{league_code}")
def refresh_league_odds(
    league_code: str,
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Refresh odds + value-pick flags for a single league."""
    from services.odds_service import refresh_odds_for_league
    from services.player_availability_service import LEAGUE_API_FOOTBALL_IDS

    if league_code not in LEAGUE_API_FOOTBALL_IDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown league_code '{league_code}'. "
                f"Must be one of: {sorted(LEAGUE_API_FOOTBALL_IDS.keys())}"
            ),
        )

    try:
        stats = refresh_odds_for_league(db, league_code)
        return {"status": "done", **stats}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Odds refresh failed for '{league_code}': {str(e)}",
        )


@router.post("/players/refresh/{league_code}")
def refresh_league_players(
    league_code: str,
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Refresh top scorers and injuries for a specific league.

    Args:
        league_code: One of the tracked league codes, e.g. 'epl', 'ucl', 'laliga'.
    """
    from services.player_availability_service import (
        LEAGUE_API_FOOTBALL_IDS,
        refresh_injuries,
        refresh_top_scorers,
    )

    if league_code not in LEAGUE_API_FOOTBALL_IDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown league_code '{league_code}'. "
                f"Must be one of: {sorted(LEAGUE_API_FOOTBALL_IDS.keys())}"
            ),
        )

    try:
        scorers = refresh_top_scorers(db, league_code)
        injuries = refresh_injuries(db, league_code)
        return {
            "status": "done",
            "league": league_code,
            "scorers_updated": scorers,
            "injuries_updated": injuries,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Player refresh failed for '{league_code}': {str(e)}",
        )
