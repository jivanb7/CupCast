"""
scripts/export_injuries.py
===========================
Export per-team injury snapshot from the DB to a parquet file consumed by
ml/src/feature_engineering.py.

Minimal initial version: one snapshot row per team with as_of_date=today.
Columns: team_id, as_of_date, active_injuries, key_active_injuries.

Run (from project root):
  python scripts/export_injuries.py
"""

import logging
import os
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import pandas as pd
from sqlalchemy import case, create_engine, func
from sqlalchemy.orm import sessionmaker

from models.player import Player  # noqa: E402
from models.player_injury import PlayerInjury  # noqa: E402

logger = logging.getLogger(__name__)

OUTPUT_PATH = PROJECT_ROOT / "ml" / "data" / "processed" / "team_injuries.parquet"


def _resolve_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite:///./cupcast_dev.db")
    if url.startswith("sqlite:///./"):
        db_file = url[len("sqlite:///./"):]
        url = f"sqlite:///{PROJECT_ROOT / 'backend' / db_file}"
    return url


def export_team_injuries() -> pd.DataFrame:
    """Query DB, aggregate active injuries per team, write parquet, return df."""
    engine = create_engine(_resolve_database_url())
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # active_injuries: count of players on this team with an active injury
        # key_active_injuries: same, restricted to is_key_player=True
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
    finally:
        session.close()

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

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_PATH, index=False)
    logger.info("Wrote %d team injury rows to %s", len(df), OUTPUT_PATH)
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    export_team_injuries()
