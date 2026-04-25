"""
backend/scripts/compute_team_elo.py
====================================
One-shot historical Elo backfill for national teams.

Walks `intl_matches.parquet` chronologically, applying the World Football
Elo update from `services.national_elo` to every completed match. At the
end, writes one row per team into `team_elo` with source='historical_backfill'
and as_of_date=today.

Why a one-shot script (not a service):
  Backfill is fundamentally batch — we need full history in date order, and
  re-running it just rewrites the snapshot. Live updates (one row per match
  as scores arrive) belong in a different code path; this script is the
  cold start.

Usage:
    cd saas
    conda run -n ml python backend/scripts/compute_team_elo.py --dry-run
    conda run -n ml python backend/scripts/compute_team_elo.py        # writes to DB

The team_elo table schema is being created by another agent; this script
will fail at the DB-write step until that migration lands. Use --dry-run
in the meantime — the Elo math runs end-to-end without touching the DB.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

# Make `backend` importable regardless of cwd. Mirrors the pattern in
# scripts/generate_predictions.py.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from services.national_elo import infer_k, update_elo  # noqa: E402

logger = logging.getLogger(__name__)

INTL_MATCHES_PATH = PROJECT_ROOT / "ml" / "data" / "processed" / "intl_matches.parquet"
INITIAL_ELO = 1500.0


# ---------------------------------------------------------------------------
# Pure computation (no DB)
# ---------------------------------------------------------------------------


def compute_elo_history(matches: pd.DataFrame) -> dict[str, float]:
    """Walk matches chronologically and return final Elo per team name.

    Expects columns: match_date, home_team, away_team, home_goals, away_goals,
    tournament, tournament_type, is_neutral_venue.

    Teams not seen before start at INITIAL_ELO (1500). The defaultdict
    pattern means a brand-new team's first match is computed against 1500
    on both sides if both are new — this is the standard cold-start.
    """
    required = {
        "match_date", "home_team", "away_team",
        "home_goals", "away_goals",
        "tournament", "tournament_type", "is_neutral_venue",
    }
    missing = required - set(matches.columns)
    if missing:
        raise ValueError(f"intl_matches parquet missing required columns: {missing}")

    # Sort ascending. .sort_values is stable, so ties on date keep parquet order.
    matches = matches.sort_values("match_date", kind="stable").reset_index(drop=True)

    elo: dict[str, float] = defaultdict(lambda: INITIAL_ELO)
    n_processed = 0

    # Iterate via itertuples — ~5x faster than iterrows for ~50k rows and
    # we're not mutating the frame.
    for row in matches.itertuples(index=False):
        home, away = row.home_team, row.away_team
        if not isinstance(home, str) or not isinstance(away, str):
            continue
        try:
            hg, ag = int(row.home_goals), int(row.away_goals)
        except (TypeError, ValueError):
            continue

        is_neutral = bool(row.is_neutral_venue)
        k = infer_k(row.tournament_type, row.tournament)

        new_home, new_away = update_elo(
            home_elo=elo[home],
            away_elo=elo[away],
            home_goals=hg,
            away_goals=ag,
            k_constant=k,
            is_neutral=is_neutral,
        )
        elo[home] = new_home
        elo[away] = new_away
        n_processed += 1

    logger.info("Processed %d matches across %d teams", n_processed, len(elo))
    return dict(elo)


# ---------------------------------------------------------------------------
# Team identity resolution
# ---------------------------------------------------------------------------


def resolve_team_ids(db, team_names: list[str]) -> tuple[dict[str, int], list[str]]:
    """Map parquet team names → teams.id.

    Strategy mirrors services/fixture_seeder.py:
      1. Exact canonical_name match (filtered to team_type='national')
      2. TeamNameAlias lookup
    Anything that resolves to neither is returned in the unresolved list so
    the caller can decide whether to seed missing aliases or proceed.
    """
    from models.team import Team, TeamNameAlias

    # Pull all national teams once — cheaper than per-name queries.
    nationals = db.query(Team).filter(Team.team_type == "national").all()
    by_canonical = {t.canonical_name: t.id for t in nationals}

    # Pull all aliases once. We don't filter by source here because the
    # parquet was built from Kaggle international data and may have been
    # seeded under various source tags.
    aliases = db.query(TeamNameAlias).all()
    by_alias = {a.alias: a.team_id for a in aliases}

    resolved: dict[str, int] = {}
    unresolved: list[str] = []
    for name in team_names:
        if name in by_canonical:
            resolved[name] = by_canonical[name]
        elif name in by_alias:
            resolved[name] = by_alias[name]
        else:
            unresolved.append(name)

    return resolved, unresolved


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------


def write_elo_snapshot(
    db, team_ratings: dict[int, float], as_of: date
) -> int:
    """Insert one team_elo row per resolved team for source='historical_backfill'.

    Uses a raw INSERT against the team_elo table by name — the ORM model
    may not exist yet (the schema agent owns that file), so we side-step
    SQLAlchemy's declarative layer and let the DB enforce the FK.
    """
    from sqlalchemy import text

    stmt = text(
        """
        INSERT INTO team_elo (team_id, rating, as_of_date, source, created_at)
        VALUES (:team_id, :rating, :as_of, 'historical_backfill', CURRENT_TIMESTAMP)
        """
    )
    inserted = 0
    for team_id, rating in team_ratings.items():
        db.execute(stmt, {"team_id": team_id, "rating": rating, "as_of": as_of})
        inserted += 1
    db.commit()
    return inserted


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_top20(team_ratings: dict[str, float]) -> None:
    """Print top 20 by rating as a sanity-check table."""
    ranked = sorted(team_ratings.items(), key=lambda kv: kv[1], reverse=True)[:20]
    print()
    print(f"{'Rank':<5} {'Team':<28} {'Elo':>7}")
    print("-" * 42)
    for i, (team, rating) in enumerate(ranked, start=1):
        print(f"{i:<5} {team:<28} {rating:>7.1f}")
    print()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill national-team Elo ratings.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute Elo and print top 20 but do not write to the database.",
    )
    parser.add_argument(
        "--matches-path",
        default=str(INTL_MATCHES_PATH),
        help="Path to intl_matches.parquet (default: ml/data/processed/intl_matches.parquet)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    matches_path = Path(args.matches_path)
    if not matches_path.exists():
        logger.error("intl_matches parquet not found at %s", matches_path)
        return 2

    logger.info("Loading %s", matches_path)
    matches = pd.read_parquet(matches_path)
    logger.info("Loaded %d rows", len(matches))

    team_ratings = compute_elo_history(matches)
    _print_top20(team_ratings)

    if args.dry_run:
        logger.info("--dry-run set; skipping DB writes")
        return 0

    # Resolve names → team_id and write snapshot.
    from database import SessionLocal

    db = SessionLocal()
    try:
        resolved, unresolved = resolve_team_ids(db, list(team_ratings.keys()))
        if unresolved:
            logger.warning(
                "%d teams could not be resolved to teams.id (skipping): %s",
                len(unresolved),
                ", ".join(unresolved[:10]) + (" ..." if len(unresolved) > 10 else ""),
            )

        ratings_by_id = {resolved[name]: rating for name, rating in team_ratings.items() if name in resolved}
        n = write_elo_snapshot(db, ratings_by_id, as_of=date.today())
        logger.info("Wrote %d team_elo rows (source=historical_backfill)", n)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
