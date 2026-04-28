"""
backend/scripts/export_api_football_predictions.py
====================================================
Exports the api_football_predictions table to a Parquet file for use as
ML features during training and inference.

Output path:
    ml/data/processed/api_football_predictions.parquet

Columns exported:
    match_id   (int64)   — FK to matches.id (only set for current-DB rows; useful for inference-time joins)
    match_date (date)    — kickoff date, used as part of the (home, away, date) merge key in training
    home_team  (str)     — canonical home team name from teams.canonical_name (matches what football-data CSVs ingest as)
    away_team  (str)     — canonical away team name
    prob_home  (float64) — API-Football's predicted home-win probability [0, 1]
    prob_draw  (float64) — draw probability
    prob_away  (float64) — away-win probability
    fetched_at (datetime[ns, UTC]) — when the estimate was last refreshed

Usage:
    # From repo root:
    conda run -n ml python backend/scripts/export_api_football_predictions.py

    # Or from inside backend/:
    conda run -n ml python -m scripts.export_api_football_predictions

The feature_engineering.py pipeline reads this file at parquet-build time
and left-joins on match_id. Rows with NULL prob_* values (fixtures where
API-Football returned no percent block) are exported as NaN — the feature
pipeline is expected to handle missing values via imputation.

Notes:
  - The script never modifies the DB — read-only query.
  - Output directory is created if it doesn't exist.
  - Overwrites the existing parquet file on each run (idempotent).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Make backend modules importable regardless of cwd.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
for _p in [str(_BACKEND_DIR), str(_REPO_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402

logger = logging.getLogger(__name__)

OUTPUT_PATH = _REPO_ROOT / "ml" / "data" / "processed" / "api_football_predictions.parquet"

_QUERY = """
    SELECT
        afp.match_id,
        m.match_date,
        h.canonical_name AS home_team,
        a.canonical_name AS away_team,
        afp.prob_home,
        afp.prob_draw,
        afp.prob_away,
        afp.fetched_at
    FROM api_football_predictions afp
    JOIN matches m ON m.id = afp.match_id
    JOIN teams h ON h.id = m.home_team_id
    JOIN teams a ON a.id = m.away_team_id
    ORDER BY afp.match_id
"""


def export(output_path: Path = OUTPUT_PATH) -> Path:
    """Read api_football_predictions and write to Parquet.

    Args:
        output_path: Destination .parquet file path (default: ml/data/processed/).

    Returns:
        The resolved path to the written file.

    Raises:
        Exception: Propagates DB/IO errors to the caller so CLI can log and exit.
    """
    from sqlalchemy import text
    from database import engine

    logger.info("Querying api_football_predictions …")
    with engine.connect() as conn:
        df = pd.read_sql(text(_QUERY), conn)

    logger.info("Fetched %d rows from api_football_predictions", len(df))

    # Coerce types explicitly so downstream pandas code doesn't encounter
    # surprising object-dtype columns from the JSONB-adjacent nulls.
    df["match_id"] = df["match_id"].astype("Int64")
    df["match_date"] = pd.to_datetime(df["match_date"])
    for col in ("home_team", "away_team"):
        df[col] = df[col].astype(str)
    for col in ("prob_home", "prob_draw", "prob_away"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "fetched_at" in df.columns:
        df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df.to_parquet(output_path, index=False, engine="pyarrow")
    logger.info("Exported %d rows to %s", len(df), output_path)

    return output_path


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    try:
        out = export()
        print(f"Wrote {out}")
        return 0
    except Exception as exc:
        logger.exception("export_api_football_predictions failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
