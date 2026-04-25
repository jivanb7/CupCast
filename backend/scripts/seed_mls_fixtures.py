"""
backend/scripts/seed_mls_fixtures.py
=====================================
Pull upcoming MLS fixtures from API-Football and seed them into ``matches``.

Why this exists
  The standing fixture seeder (``services/fixture_seeder.py``) covers the Big-5
  + EPL pyramid via Football-Data.org and fills WC/EPL gaps via ESPN. MLS is
  served by ESPN for *live scores* but not picked up by the scheduled fixture
  seed, so the DB has zero scheduled MLS matches even though 30 MLS clubs
  are seeded.

Scope
  - INSERT only, scheduled status, idempotent on (home, away, league, date).
  - Pulls the next 30 days from API-Football league_id=253 for the current
    season (2026 = 2026 MLS regular season; MLS is a calendar-year league).
  - Reuses the team-resolution pattern from ``services/fixture_seeder.py``
    (alias-aware via ``_resolve_team``).

Usage
    cd backend && conda run -n ml python scripts/seed_mls_fixtures.py
    cd backend && conda run -n ml python scripts/seed_mls_fixtures.py --days 45 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

# Make backend importable when run as `python scripts/seed_mls_fixtures.py`
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Load .env from saas/ root so API_FOOTBALL_KEYS is available outside the
# FastAPI lifespan.
try:
    from dotenv import load_dotenv

    load_dotenv(_BACKEND_DIR.parent / ".env")
except ImportError:
    pass

from sqlalchemy.orm import Session  # noqa: E402

from database import SessionLocal  # noqa: E402
from models.league import League  # noqa: E402
from models.match import Match  # noqa: E402
from services.fixture_seeder import _resolve_team, _current_season_str  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("seed_mls_fixtures")

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
MLS_API_FOOTBALL_LEAGUE_ID = 253
DEFAULT_DAYS_AHEAD = 30
REQUEST_TIMEOUT_SECONDS = 20


def _get_api_keys() -> list[str]:
    raw = os.getenv("API_FOOTBALL_KEYS") or os.getenv("API_FOOTBALL_KEY") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def _mls_season() -> int:
    """MLS runs Feb–Dec on a calendar year, so API-Football's season key is
    the current year. We bump after October only as a fallback for off-season
    runs after a new schedule is published.
    """
    now = datetime.now(timezone.utc)
    return now.year


def _fetch_fixtures(
    season: int, from_date: date, to_date: date, key: str
) -> Optional[list[dict]]:
    url = f"{API_FOOTBALL_BASE}/fixtures"
    headers = {"x-apisports-key": key}
    params = {
        "league": MLS_API_FOOTBALL_LEAGUE_ID,
        "season": season,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
    }
    try:
        resp = requests.get(
            url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        logger.error("network error: %s", exc)
        return None

    if resp.status_code == 429:
        logger.error("rate limited (429) — try again later or rotate keys")
        return None
    if resp.status_code in (401, 403):
        logger.error("auth failure (HTTP %d) — check API_FOOTBALL_KEYS", resp.status_code)
        return None
    if resp.status_code != 200:
        logger.error("HTTP %d body=%s", resp.status_code, resp.text[:200])
        return None

    try:
        payload = resp.json()
    except ValueError as exc:
        logger.error("JSON decode error: %s", exc)
        return None

    return payload.get("response", []) or []


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS_AHEAD,
        help=f"How many days ahead to fetch (default: {DEFAULT_DAYS_AHEAD}).",
    )
    p.add_argument(
        "--season",
        type=int,
        default=_mls_season(),
        help="API-Football season (default: current year).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print would-be inserts; do not write to DB.",
    )
    return p.parse_args()


def seed_mls_fixtures(args: argparse.Namespace) -> int:
    keys = _get_api_keys()
    if not keys:
        logger.error("API_FOOTBALL_KEYS not set in env — aborting")
        return 2
    key = keys[0]

    today = date.today()
    to_date = today + timedelta(days=args.days)
    season = args.season

    logger.info(
        "fetching MLS fixtures: season=%d from=%s to=%s dry_run=%s",
        season, today.isoformat(), to_date.isoformat(), args.dry_run,
    )

    fixtures = _fetch_fixtures(season, today, to_date, key)
    if fixtures is None:
        return 3

    api_returned = len(fixtures)
    inserted = 0
    skipped_existing = 0
    unresolved = 0
    skipped_other = 0
    samples: list[str] = []

    db: Session = SessionLocal()
    try:
        league = db.query(League).filter(League.code == "mls").first()
        if league is None:
            logger.error("league code='mls' not in DB — aborting")
            return 4

        season_str = _current_season_str()

        for fx in fixtures:
            fx_node = fx.get("fixture", {}) or {}
            teams_node = fx.get("teams", {}) or {}
            home_node = teams_node.get("home", {}) or {}
            away_node = teams_node.get("away", {}) or {}

            home_name = (home_node.get("name") or "").strip()
            away_name = (away_node.get("name") or "").strip()
            ts = fx_node.get("date") or ""  # ISO 8601, e.g. "2026-04-25T23:30:00+00:00"

            if not home_name or not away_name or not ts:
                skipped_other += 1
                continue

            # Parse ISO timestamp -> match_date + kickoff_time (UTC).
            try:
                # Python <3.11 doesn't accept "Z"; replace defensively.
                ts_clean = ts.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_clean).astimezone(timezone.utc)
            except ValueError:
                skipped_other += 1
                continue

            match_date = dt.date()
            kickoff_time = dt.strftime("%H:%M")

            home_id = _resolve_team(db, home_name, "mls")
            away_id = _resolve_team(db, away_name, "mls")
            if not home_id or not away_id:
                logger.debug(
                    "unresolved: home=%r (id=%s) away=%r (id=%s)",
                    home_name, home_id, away_name, away_id,
                )
                unresolved += 1
                continue

            existing = (
                db.query(Match)
                .filter(
                    Match.home_team_id == home_id,
                    Match.away_team_id == away_id,
                    Match.league_id == league.id,
                    Match.match_date == match_date,
                )
                .first()
            )
            if existing:
                # Backfill kickoff_time if missing (matches fixture_seeder behaviour).
                if kickoff_time and not existing.kickoff_time:
                    existing.kickoff_time = kickoff_time
                skipped_existing += 1
                continue

            new_match = Match(
                home_team_id=home_id,
                away_team_id=away_id,
                league_id=league.id,
                match_date=match_date,
                kickoff_time=kickoff_time,
                status="scheduled",
                season=season_str,
            )
            if not args.dry_run:
                db.add(new_match)
            inserted += 1
            if len(samples) < 5:
                samples.append(
                    f"{match_date} {kickoff_time} UTC  {home_name} vs {away_name}"
                )

        if not args.dry_run:
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.error("commit failed: %s", exc)
                return 5

        print()
        print("=" * 72)
        print("SEED MLS FIXTURES — SUMMARY" + ("  [DRY-RUN]" if args.dry_run else ""))
        print("=" * 72)
        print(f"  api_returned     : {api_returned}")
        print(f"  inserted         : {inserted}")
        print(f"  skipped_existing : {skipped_existing}")
        print(f"  unresolved       : {unresolved}")
        print(f"  skipped_other    : {skipped_other}")
        if samples:
            print()
            print("Sample inserts:")
            for s in samples:
                print(f"  + {s}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(seed_mls_fixtures(_parse_args()))
