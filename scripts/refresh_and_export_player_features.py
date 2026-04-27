"""
scripts/refresh_and_export_player_features.py
==============================================
One-shot script the data-refresh workflow runs BEFORE feature engineering
to make sure the player/injury/top-scorer signals are fresh and exported
to the parquets the feature engineering layer reads from.

Pipeline:
  1. Call backend.services.player_availability_service.refresh_all_leagues()
     which populates the DB tables `players`, `player_injuries`, and the
     is_key_player flags by hitting API-Football top-scorers + injuries
     endpoints. With the paid tier this costs ~10-20 requests per league
     × 10 leagues = ~200 requests, well inside the 7500/day budget.
  2. Call export_injuries.export_team_injuries() to dump the active-injury
     snapshot to ml/data/processed/team_injuries.parquet — the file
     ml/src/feature_engineering.add_injury_features already reads.
  3. Compute key_player_availability per (team, season) and export to
     ml/data/processed/team_availability.parquet — consumed by the new
     add_availability_features helper.

Run:
  PYTHONPATH=backend:ml:. python scripts/refresh_and_export_player_features.py
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.team import Team  # noqa: E402
from services.player_availability_service import (  # noqa: E402
    LEAGUE_API_FOOTBALL_IDS,
    compute_key_player_availability,
    refresh_all_leagues,
)

logger = logging.getLogger(__name__)

INJURIES_PATH = PROJECT_ROOT / "ml" / "data" / "processed" / "team_injuries.parquet"
AVAIL_PATH = PROJECT_ROOT / "ml" / "data" / "processed" / "team_availability.parquet"


def _resolve_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite:///./cupcast_dev.db")
    if url.startswith("sqlite:///./"):
        db_file = url[len("sqlite:///./"):]
        url = f"sqlite:///{PROJECT_ROOT / 'backend' / db_file}"
    return url


def _refresh_from_api_football(session) -> dict:
    """Hit API-Football for fresh top-scorers + injuries across all leagues
    we cover. The service handles rate-limiting and key rotation, but the
    rotator must be initialized first with the keys env var. The backend
    web process does this on startup; this script doesn't get that lifecycle
    so we call init_rotator() ourselves here."""
    keys_env = os.environ.get("API_FOOTBALL_KEYS", "")
    if not keys_env:
        logger.warning(
            "API_FOOTBALL_KEYS env var not set — skipping refresh. "
            "The DB's existing injury/top-scorer rows will be used as-is."
        )
        return {}

    # Initialize the rate-limiter / key rotator before calling any
    # services.player_availability_service function. Without this every
    # league call returns 'API key rotator not initialized'.
    try:
        from services.api_key_rotator import init_rotator
        keys = [k.strip() for k in keys_env.split(",") if k.strip()]
        init_rotator(keys)
        logger.info("api_key_rotator initialized with %d key(s)", len(keys))
    except Exception:
        logger.exception("Failed to init_rotator — refresh will fall through")
        return {}

    try:
        result = refresh_all_leagues(session)
        logger.info("API-Football refresh complete: %s", result)
        return result
    except Exception:
        logger.exception(
            "API-Football refresh failed — continuing with whatever the DB "
            "already has. Stale data is better than no training data."
        )
        return {}


def _export_injuries(session) -> int:
    """Re-derive ml/data/processed/team_injuries.parquet from the DB. We
    delegate to the existing export_injuries.py helper so the schema stays
    in sync with what feature_engineering.add_injury_features expects."""
    from sqlalchemy import case, func

    from models.player import Player
    from models.player_injury import PlayerInjury

    key_flag = case((Player.is_key_player.is_(True), 1), else_=0)
    rows = (
        session.query(
            Player.team_id.label("team_id"),
            func.count(PlayerInjury.id).label("active_injuries"),
            func.coalesce(func.sum(key_flag), 0).label("key_active_injuries"),
        )
        .join(PlayerInjury, PlayerInjury.player_id == Player.id)
        .filter(PlayerInjury.is_active.is_(True))
        .group_by(Player.team_id)
        .all()
    )

    today = date.today()
    df = pd.DataFrame(
        [
            {
                "team_id": r.team_id,
                "as_of_date": today,
                "active_injuries": int(r.active_injuries or 0),
                "key_active_injuries": int(r.key_active_injuries or 0),
            }
            for r in rows
        ],
        columns=["team_id", "as_of_date", "active_injuries", "key_active_injuries"],
    )
    INJURIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(INJURIES_PATH, index=False)
    logger.info("Exported %d team injury rows to %s", len(df), INJURIES_PATH)
    return len(df)


def _export_availability(session) -> int:
    """Compute key_player_availability for every team in our covered
    leagues for the CURRENT season. Output schema matches what
    add_availability_features merges on:
        team_id | season | key_player_avail
    Older seasons fall back to default 1.0 at feature-engineering time.
    """
    from services.player_availability_service import _current_season

    season = _current_season()
    teams = (
        session.query(Team)
        .join(Team.league)
        .filter(Team.league.has(code__in=list(LEAGUE_API_FOOTBALL_IDS.keys())))
        .all()
        if hasattr(Team, "league") else
        session.query(Team).all()
    )

    rows = []
    for t in teams:
        try:
            score = compute_key_player_availability(session, t.id, season)
        except Exception:
            score = 1.0  # safe default — "fully available"
        rows.append({"team_id": t.id, "season": season, "key_player_avail": float(score)})

    df = pd.DataFrame(rows, columns=["team_id", "season", "key_player_avail"])
    AVAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(AVAIL_PATH, index=False)
    logger.info("Exported %d team availability rows to %s", len(df), AVAIL_PATH)
    return len(df)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    engine = create_engine(_resolve_database_url())
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Step 1: refresh the DB tables from API-Football. Best-effort —
        # if it fails we keep going with whatever's already there.
        _refresh_from_api_football(session)

        # Step 2: export per-team injury snapshot.
        try:
            _export_injuries(session)
        except Exception:
            logger.exception("injury export failed (training will fall back to zeros)")

        # Step 3: export per-team availability snapshot.
        try:
            _export_availability(session)
        except Exception:
            logger.exception("availability export failed (training will fall back to 1.0)")
    finally:
        session.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
