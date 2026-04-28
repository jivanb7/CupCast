"""
backend/scripts/refresh_api_football_predictions.py
=====================================================
CLI entry point for fetching and storing API-Football win-probability
predictions for upcoming or historical matches.

Two modes:

  upcoming (default)
    Refreshes predictions for all scheduled matches in the next N days.
    Intended for daily cron runs so our model always has fresh API-Football
    signals for the next match-day.

  backfill
    Fetches predictions for completed and scheduled matches in the trailing
    N days, optionally filtered to specific league codes. Used for the
    initial data load and periodic gap-filling.

Usage examples:

  # Upcoming (default, next 7 days):
  conda run -n ml python backend/scripts/refresh_api_football_predictions.py

  # Upcoming, custom window:
  conda run -n ml python backend/scripts/refresh_api_football_predictions.py \\
      --mode upcoming --days-ahead 14

  # Backfill last 120 days, top-5 leagues + UCL:
  conda run -n ml python backend/scripts/refresh_api_football_predictions.py \\
      --mode backfill --days-back 120 --leagues epl,laliga,seriea,bundesliga,ligue1,ucl

  # Backfill all available leagues, last 30 days:
  conda run -n ml python backend/scripts/refresh_api_football_predictions.py \\
      --mode backfill --days-back 30

Environment variables required:
  API_FOOTBALL_KEYS  — comma-separated API-Football key(s)
  DATABASE_URL       — Postgres connection string (or SQLite for local dev)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Allow `python backend/scripts/...` from the repo root AND
# `python -m scripts.refresh_api_football_predictions` from inside backend/.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
for _p in [str(_BACKEND_DIR), str(_REPO_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


logger = logging.getLogger(__name__)

_DEFAULT_DAYS_AHEAD = 7
_DEFAULT_DAYS_BACK = 120


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _init_rotator() -> bool:
    """Initialize the API key rotator from the API_FOOTBALL_KEYS env var.

    Returns False if no keys are configured (caller should exit with code 2).
    """
    from services.api_key_rotator import init_rotator

    raw = os.getenv("API_FOOTBALL_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        print(
            "ERROR: API_FOOTBALL_KEYS env var is empty — cannot fetch predictions",
            file=sys.stderr,
        )
        return False
    init_rotator(keys)
    return True


def _print_summary(summary: dict) -> None:
    print()
    print("=" * 60)
    print("API-Football Predictions Refresh — Summary")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k:<30}: {v}")
    print()


def main() -> int:
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Refresh API-Football win-probability predictions.",
    )
    parser.add_argument(
        "--mode",
        choices=["upcoming", "backfill"],
        default="upcoming",
        help="Operation mode: 'upcoming' (default) refreshes the next N days; "
             "'backfill' fills the trailing N days.",
    )
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=_DEFAULT_DAYS_AHEAD,
        metavar="N",
        help="Days ahead to cover in 'upcoming' mode (default %(default)d).",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=_DEFAULT_DAYS_BACK,
        metavar="N",
        help="Days back to cover in 'backfill' mode (default %(default)d).",
    )
    parser.add_argument(
        "--leagues",
        type=str,
        default=None,
        metavar="CODE,...",
        help=(
            "Comma-separated League.code values to restrict 'backfill' to "
            "(e.g. 'epl,laliga,seriea,bundesliga,ligue1,ucl'). "
            "Default: all leagues."
        ),
    )

    args = parser.parse_args()

    if not _init_rotator():
        return 2

    from database import SessionLocal
    from services.api_football_predictions_service import (
        refresh_for_upcoming,
        backfill_for_recent,
    )

    db = SessionLocal()
    try:
        if args.mode == "upcoming":
            logger.info(
                "Starting upcoming refresh: days_ahead=%d", args.days_ahead
            )
            summary = refresh_for_upcoming(db, days_ahead=args.days_ahead)

        else:  # backfill
            leagues: list[str] | None = None
            if args.leagues:
                leagues = [c.strip() for c in args.leagues.split(",") if c.strip()]

            logger.info(
                "Starting backfill: days_back=%d leagues=%s",
                args.days_back, leagues,
            )
            summary = backfill_for_recent(
                db, days_back=args.days_back, leagues=leagues
            )

    except Exception as exc:
        logger.exception("refresh_api_football_predictions failed: %s", exc)
        return 1
    finally:
        db.close()

    _print_summary(summary)

    # Exit non-zero only on hard errors, not on skips/no-data.
    if summary.get("errors", 0) > 0:
        logger.warning(
            "%d errors encountered — check logs above for details.",
            summary["errors"],
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
