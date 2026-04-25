"""
backend/scripts/seed_missing_clubs.py
=====================================
Seed *missing* club rows into the ``teams`` table from API-Football.

Why this exists
  Two leagues have unseeded clubs that block fixture/prediction flow:
    * MLS — 30 clubs, none seeded (live-scores go through ESPN, so the
      logo backfill never had rows to update).
    * UCL — qualifying-round clubs (e.g. Brann, Pafos, KuPS, FC Basel 1893,
      HNK Rijeka, Vikingur Gota, Shkendija, Kairat Almaty, Milsami Orhei,
      Saburtalo, FC Noah, Shelbourne, Drita) that aren't already represented
      under any of our domestic leagues.

Scope
  - INSERT only. Never UPDATE existing rows (the logo-backfill agent owns that).
  - club rows only (``team_type = 'club'``). Never touches national teams.

Resolution
  Reuses ``_resolve_club_team`` from ``backfill_team_logos.py`` to detect
  whether the API team already exists under any club row (UCL teams typically
  belong to their domestic league row in our DB). If resolved → skip.

Usage
    cd backend && conda run -n ml python scripts/seed_missing_clubs.py --dry-run
    cd backend && conda run -n ml python scripts/seed_missing_clubs.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests

# Make backend importable when run as `python scripts/seed_missing_clubs.py`
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Load .env from saas/ root (one level above backend/) so API_FOOTBALL_KEYS
# is available even when invoked outside of the FastAPI lifespan.
try:
    from dotenv import load_dotenv

    load_dotenv(_BACKEND_DIR.parent / ".env")
except ImportError:
    pass

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from database import SessionLocal  # noqa: E402
from models.league import League  # noqa: E402
from models.team import Team  # noqa: E402

# Reuse the battle-tested resolver from the logo backfill — it handles
# accents, fillers, alias table, and league-scoped fuzzy.
from scripts.backfill_team_logos import _resolve_club_team  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("seed_missing_clubs")

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
INTER_CALL_SLEEP_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 20

# League code → API-Football league id. MLS isn't in
# LEAGUE_API_FOOTBALL_IDS (live-scores go through ESPN); UCL is id=2.
LEAGUE_API_IDS: dict[str, int] = {
    "mls": 253,
    "ucl": 2,
}


def _current_season() -> int:
    """API-Football keys seasons by start year. July is the cutover."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1


def _get_api_keys() -> list[str]:
    raw = os.getenv("API_FOOTBALL_KEYS") or os.getenv("API_FOOTBALL_KEY") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def _fetch_teams_for_league(
    api_league_id: int, season: int, key: str
) -> Optional[list[dict]]:
    """Single GET to /teams?league=X&season=Y. Returns None on hard failure."""
    url = f"{API_FOOTBALL_BASE}/teams"
    headers = {"x-apisports-key": key}
    params = {"league": api_league_id, "season": season}

    try:
        resp = requests.get(
            url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        logger.error("network error league=%d season=%d: %s", api_league_id, season, exc)
        return None

    if resp.status_code == 429:
        logger.error("rate limited (429) on league=%d", api_league_id)
        return None
    if resp.status_code in (401, 403):
        logger.error("auth failure (HTTP %d) — check API_FOOTBALL_KEYS", resp.status_code)
        return None
    if resp.status_code != 200:
        logger.error(
            "HTTP %d league=%d season=%d body=%s",
            resp.status_code, api_league_id, season, resp.text[:200],
        )
        return None

    try:
        payload = resp.json()
    except ValueError as exc:
        logger.error("JSON decode error league=%d: %s", api_league_id, exc)
        return None

    return payload.get("response", []) or []


def _short_name(team_blob: dict) -> str:
    """API-Football's ``team.code`` if present, else first 3 letters uppercased."""
    code = (team_blob.get("code") or "").strip()
    if code:
        return code
    name = (team_blob.get("name") or "").strip()
    return name[:3].upper()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--leagues",
        default="mls,ucl",
        help="Comma-separated league codes to seed (default: mls,ucl).",
    )
    p.add_argument(
        "--season",
        type=int,
        default=_current_season(),
        help="API-Football season start year (default: current).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print would-be inserts; do not write to DB.",
    )
    return p.parse_args()


def seed_missing_clubs(args: argparse.Namespace) -> int:
    keys = _get_api_keys()
    if not keys:
        logger.error("API_FOOTBALL_KEYS not set in env — aborting")
        return 2
    key = keys[0]
    season = args.season
    target_codes = [c.strip().lower() for c in args.leagues.split(",") if c.strip()]
    logger.info(
        "season=%d leagues=%s dry_run=%s api_keys_loaded=%d",
        season, target_codes, args.dry_run, len(keys),
    )

    db: Session = SessionLocal()
    try:
        per_league: list[dict] = []
        skipped_existing_global: list[tuple[str, str, str]] = []  # (league, api_name, db_canonical)

        # Snapshot all club rows once; resolver uses this as its index.
        # We rebuild after each commit so newly-inserted rows are considered
        # for subsequent leagues (so e.g. a UCL run after MLS sees MLS rows).
        club_index: list[Team] = (
            db.query(Team).filter(Team.team_type == "club").all()
        )

        for league_code in target_codes:
            api_league_id = LEAGUE_API_IDS.get(league_code)
            if api_league_id is None:
                logger.warning("no API-Football id mapped for league=%s — skipping", league_code)
                continue

            league_obj = db.query(League).filter(League.code == league_code).first()
            if league_obj is None:
                logger.warning("league %s not in DB — skipping", league_code)
                continue

            existing_count_before = (
                db.query(Team)
                .filter(Team.league_id == league_obj.id)
                .filter(Team.team_type == "club")
                .count()
            )

            logger.info(
                "fetching league=%s (api_id=%d, season=%d, existing_in_league=%d)",
                league_code, api_league_id, season, existing_count_before,
            )
            payload = _fetch_teams_for_league(api_league_id, season, key)
            if payload is None:
                logger.error("hard failure on %s — bailing out", league_code)
                return 3

            inserted_rows: list[dict] = []
            skipped_existing: list[tuple[str, str]] = []  # (api_name, db_canonical)

            for entry in payload:
                team_blob = entry.get("team", {}) or {}
                api_name = (team_blob.get("name") or "").strip()
                if not api_name:
                    continue

                # Resolve against ALL clubs (UCL teams live under domestic leagues).
                resolved = _resolve_club_team(db, api_name, league_obj.id, club_index)
                if resolved is not None:
                    skipped_existing.append((api_name, resolved.canonical_name))
                    skipped_existing_global.append(
                        (league_code, api_name, resolved.canonical_name)
                    )
                    continue

                # Defensive: avoid colliding with a non-club row that shares the
                # exact canonical_name (canonical_name has a UNIQUE constraint).
                clash = (
                    db.query(Team)
                    .filter(Team.canonical_name == api_name)
                    .first()
                )
                if clash is not None:
                    logger.warning(
                        "[%s] canonical_name clash for %r (existing team_type=%s) — skipping",
                        league_code, api_name, clash.team_type,
                    )
                    skipped_existing_global.append(
                        (league_code, api_name, f"{clash.canonical_name} (clash, type={clash.team_type})")
                    )
                    continue

                row = {
                    "canonical_name": api_name,
                    "short_name": _short_name(team_blob),
                    "team_type": "club",
                    "league_id": league_obj.id,
                    "country": (team_blob.get("country") or None),
                    "confederation": None,  # clubs do not have a confederation
                    "logo_url": (team_blob.get("logo") or None),
                }
                inserted_rows.append(row)

            if args.dry_run:
                logger.info(
                    "[%s] DRY-RUN would insert %d rows; existing %d already-resolved",
                    league_code, len(inserted_rows), len(skipped_existing),
                )
                for r in inserted_rows:
                    logger.info(
                        "  + %-30s short=%-5s country=%-20s logo=%s",
                        r["canonical_name"], r["short_name"], r["country"], bool(r["logo_url"]),
                    )
            else:
                # Bulk INSERT via SQLAlchemy text() so we can use CURRENT_TIMESTAMP
                # explicitly per the spec (also fine on SQLite).
                stmt = text(
                    """
                    INSERT INTO teams
                      (canonical_name, short_name, team_type, league_id,
                       country, confederation, logo_url, created_at)
                    VALUES
                      (:canonical_name, :short_name, :team_type, :league_id,
                       :country, :confederation, :logo_url, CURRENT_TIMESTAMP)
                    """
                )
                for r in inserted_rows:
                    db.execute(stmt, r)
                db.commit()
                # Refresh club index so the next league sees rows we just inserted.
                club_index = (
                    db.query(Team).filter(Team.team_type == "club").all()
                )

            existing_count_after = (
                db.query(Team)
                .filter(Team.league_id == league_obj.id)
                .filter(Team.team_type == "club")
                .count()
            )

            per_league.append(
                {
                    "league": league_code,
                    "api_returned": len(payload),
                    "existing": existing_count_before,
                    "inserted": 0 if args.dry_run else len(inserted_rows),
                    "would_insert": len(inserted_rows) if args.dry_run else 0,
                    "skipped_existing": len(skipped_existing),
                    "total_now": existing_count_after,
                }
            )

            time.sleep(INTER_CALL_SLEEP_SECONDS)

        print()
        print("=" * 72)
        print("SEED MISSING CLUBS — SUMMARY" + ("  [DRY-RUN]" if args.dry_run else ""))
        print("=" * 72)
        for row in per_league:
            if args.dry_run:
                print(
                    f"  {row['league']:<8} api_returned={row['api_returned']:>3}  "
                    f"existing={row['existing']:>3}  would_insert={row['would_insert']:>3}  "
                    f"skipped_existing={row['skipped_existing']:>3}  total_now={row['total_now']:>3}"
                )
            else:
                print(
                    f"  {row['league']:<8} existing={row['existing']:>3}  "
                    f"inserted={row['inserted']:>3}  total_now={row['total_now']:>3}"
                )
        if skipped_existing_global:
            print()
            print(f"Already-resolved (skipped, {len(skipped_existing_global)}):")
            for lg, api_name, db_name in skipped_existing_global:
                print(f"  [{lg}] {api_name!r:40s} -> {db_name!r}")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(seed_missing_clubs(_parse_args()))
