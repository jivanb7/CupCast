"""
backend/services/fixture_seeder.py
====================================
Seed upcoming (scheduled) matches into the database.

Sources:
  1. Football-Data.org API (free tier) — EPL, La Liga, Serie A, Bundesliga,
     Ligue 1, Champions League, Championship
  2. football-data.co.uk fixtures.csv — League One, League Two, National League

This runs on a schedule (3x daily) to ensure upcoming matches are always
populated before predictions are generated.

Rate limits: Football-Data.org free tier = 10 req/min. We space calls 7s apart.
"""

import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import requests
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Module-level Session for connection pooling across scheduler job invocations
_session = requests.Session()

# Football-Data.org competition codes → our DB league codes
FDORG_COMPETITIONS = {
    "PL": "epl",
    "ELC": "championship",
    "PD": "laliga",
    "SA": "seriea",
    "BL1": "bundesliga",
    "FL1": "ligue1",
    "CL": "ucl",
}

# football-data.co.uk division codes → our DB league codes
FDUK_DIVISIONS = {
    "E2": "league_one",
    "E3": "league_two",
    "EC": "national_league",
}

FDORG_BASE = "https://api.football-data.org/v4"
FDUK_FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"


def _get_fdorg_key() -> Optional[str]:
    key = os.environ.get("FOOTBALL_DATA_ORG_API_KEY", "")
    if not key:
        # Fall back to pydantic Settings (which loads saas/.env automatically)
        try:
            from config import settings
            key = settings.football_data_org_api_key or ""
        except Exception:
            pass
    return key or None


def _resolve_team(db: Session, team_name: str, league_code: str) -> Optional[int]:
    """Resolve a team name to a team ID via exact match, alias, normalization, or fuzzy match.

    For cross-league competitions (UCL), searches across ALL leagues since
    teams belong to their domestic league in the DB.
    """
    from models.team import Team, TeamNameAlias
    from models.league import League

    if not team_name:
        return None

    league = db.query(League).filter(League.code == league_code).first()
    if not league:
        return None

    # For cup competitions, search across all leagues
    cross_league = league_code in ("ucl",)

    # Try exact match on canonical_name
    q = db.query(Team).filter(Team.canonical_name == team_name)
    if not cross_league:
        q = q.filter(Team.league_id == league.id)
    team = q.first()
    if team:
        return team.id

    # Try alias table
    alias = db.query(TeamNameAlias).filter(TeamNameAlias.alias == team_name).first()
    if alias:
        return alias.team_id

    # Try ML team name normalization
    try:
        from ml.src.team_name_mapping import normalize_team_name
        ml_league_map = {
            "epl": "E0", "championship": "E1", "laliga": "SP1",
            "seriea": "I1", "bundesliga": "D1", "ligue1": "F1", "ucl": "UCL",
            "league_one": "E2", "league_two": "E3", "national_league": "EC",
        }
        ml_code = ml_league_map.get(league_code, "E0")
        normalized = normalize_team_name(team_name, league_code=ml_code)
        if normalized:
            q = db.query(Team).filter(Team.canonical_name == normalized)
            if not cross_league:
                q = q.filter(Team.league_id == league.id)
            team = q.first()
            if team:
                return team.id
    except (ImportError, Exception):
        pass

    # Fuzzy: substring matching on canonical_name and short_name
    if cross_league:
        all_teams = db.query(Team).all()
    else:
        all_teams = db.query(Team).filter(Team.league_id == league.id).all()
    name_lower = team_name.lower().strip()
    for t in all_teams:
        cn = (t.canonical_name or "").lower()
        sn = (t.short_name or "").lower()
        if name_lower in cn or cn in name_lower:
            return t.id
        if sn and (name_lower in sn or sn in name_lower):
            return t.id

    logger.debug("Could not resolve team '%s' in league '%s'", team_name, league_code)
    return None


def seed_from_football_data_org(db: Session) -> dict:
    """
    Fetch scheduled matches from Football-Data.org and seed into DB.
    Returns {seeded: int, already_exists: int, skipped: int}.
    """
    from models.league import League
    from models.match import Match

    api_key = _get_fdorg_key()
    if not api_key:
        logger.warning("No Football-Data.org API key — skipping fixture seeding")
        return {"seeded": 0, "already_exists": 0, "skipped": 0, "error": "no_api_key"}

    headers = {"X-Auth-Token": api_key}
    stats = {"seeded": 0, "already_exists": 0, "skipped": 0}

    for comp_code, db_league_code in FDORG_COMPETITIONS.items():
        league = db.query(League).filter(League.code == db_league_code).first()
        if not league:
            logger.debug("League '%s' not found in DB, skipping", db_league_code)
            continue

        try:
            resp = _session.get(
                f"{FDORG_BASE}/competitions/{comp_code}/matches",
                headers=headers,
                params={"status": "SCHEDULED"},
                timeout=15,
            )
            if resp.status_code == 429:
                logger.warning("Rate limited on %s — sleeping 30s", comp_code)
                time.sleep(30)
                resp = _session.get(
                    f"{FDORG_BASE}/competitions/{comp_code}/matches",
                    headers=headers,
                    params={"status": "SCHEDULED"},
                    timeout=15,
                )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Failed to fetch %s fixtures: %s", comp_code, e)
            time.sleep(7)
            continue

        matches = data.get("matches", [])
        logger.info("Fixture seeder: %s (%s) — %d scheduled matches from API",
                     comp_code, db_league_code, len(matches))

        for m in matches:
            home_name = m["homeTeam"]["name"]
            away_name = m["awayTeam"]["name"]
            utc_date_str = m["utcDate"]  # e.g. "2026-04-10T19:45:00Z"
            match_date_str = utc_date_str[:10]

            try:
                match_date = datetime.strptime(match_date_str, "%Y-%m-%d").date()
            except ValueError:
                stats["skipped"] += 1
                continue

            # Extract kickoff time (HH:MM) from the UTC timestamp
            kickoff_time = None
            if len(utc_date_str) >= 16 and "T" in utc_date_str:
                kickoff_time = utc_date_str[11:16]  # e.g. "19:45"

            home_id = _resolve_team(db, home_name, db_league_code)
            away_id = _resolve_team(db, away_name, db_league_code)

            if not home_id or not away_id:
                stats["skipped"] += 1
                continue

            # Check if match already exists
            existing = db.query(Match).filter(
                Match.home_team_id == home_id,
                Match.away_team_id == away_id,
                Match.league_id == league.id,
                Match.match_date == match_date,
            ).first()

            if existing:
                # Backfill kickoff_time if missing
                if kickoff_time and not existing.kickoff_time:
                    existing.kickoff_time = kickoff_time
                stats["already_exists"] += 1
                continue

            # Create new scheduled match
            new_match = Match(
                home_team_id=home_id,
                away_team_id=away_id,
                league_id=league.id,
                match_date=match_date,
                kickoff_time=kickoff_time,
                status="scheduled",
                season=_current_season_str(),
            )

            # Add odds if available
            bookmakers = m.get("odds", {}).get("homeWin")
            # Football-Data.org v4 doesn't always include odds in match list

            db.add(new_match)
            stats["seeded"] += 1

        # Rate limit: 10 req/min on free tier
        time.sleep(7)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to commit seeded fixtures: %s", e)
        stats["error"] = str(e)

    logger.info("Fixture seeder done: %s", stats)
    return stats


def seed_from_fixtures_csv(db: Session) -> dict:
    """
    Fetch upcoming fixtures from football-data.co.uk fixtures.csv.
    Covers League One, League Two, National League (not in FDORG free tier).
    """
    from models.league import League
    from models.match import Match

    stats = {"seeded": 0, "already_exists": 0, "skipped": 0}

    try:
        df = pd.read_csv(FDUK_FIXTURES_URL, encoding="utf-8-sig")
    except Exception as e:
        logger.error("Failed to download fixtures.csv: %s", e)
        return stats

    if df.empty:
        return stats

    for _, row in df.iterrows():
        div = row.get("Div", "")
        db_league_code = FDUK_DIVISIONS.get(div)
        if not db_league_code:
            continue  # Not a league we track via this source

        league = db.query(League).filter(League.code == db_league_code).first()
        if not league:
            continue

        home_name = str(row.get("HomeTeam", ""))
        away_name = str(row.get("AwayTeam", ""))
        date_str = str(row.get("Date", ""))

        if not home_name or not away_name or not date_str:
            stats["skipped"] += 1
            continue

        try:
            match_date = pd.to_datetime(date_str, dayfirst=True).date()
        except Exception:
            stats["skipped"] += 1
            continue

        home_id = _resolve_team(db, home_name, db_league_code)
        away_id = _resolve_team(db, away_name, db_league_code)

        if not home_id or not away_id:
            stats["skipped"] += 1
            continue

        existing = db.query(Match).filter(
            Match.home_team_id == home_id,
            Match.away_team_id == away_id,
            Match.league_id == league.id,
            Match.match_date == match_date,
        ).first()

        if existing:
            stats["already_exists"] += 1
            continue

        new_match = Match(
            home_team_id=home_id,
            away_team_id=away_id,
            league_id=league.id,
            match_date=match_date,
            status="scheduled",
            season=_current_season_str(),
        )
        db.add(new_match)
        stats["seeded"] += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to commit CSV fixtures: %s", e)

    logger.info("CSV fixture seeder done: %s", stats)
    return stats


def seed_all_fixtures(db: Session) -> dict:
    """Run all fixture seeders. Called by scheduler and admin endpoint.

    Sources run in order so the cheapest/most-authoritative seed first and
    ESPN fills remaining gaps. Each is independent — a failure in one does
    not block the others.
    """
    from services.espn_fixture_service import seed_from_espn

    logger.info("Starting fixture seeding...")
    fdorg = seed_from_football_data_org(db)
    csv = seed_from_fixtures_csv(db)
    espn = seed_from_espn(db)
    combined = {
        "fdorg_seeded": fdorg.get("seeded", 0),
        "csv_seeded": csv.get("seeded", 0),
        "espn_seeded": espn.get("seeded", 0),
        "espn_unresolved": espn.get("unresolved", 0),
        "already_exists": (
            fdorg.get("already_exists", 0)
            + csv.get("already_exists", 0)
            + espn.get("already_exists", 0)
        ),
        "skipped": (
            fdorg.get("skipped", 0)
            + csv.get("skipped", 0)
            + espn.get("skipped", 0)
        ),
    }
    logger.info("All fixture seeding complete: %s", combined)
    return combined


def _current_season_str() -> str:
    today = date.today()
    if today.month >= 7:
        return f"{today.year}-{str(today.year + 1)[2:]}"
    else:
        return f"{today.year - 1}-{str(today.year)[2:]}"
