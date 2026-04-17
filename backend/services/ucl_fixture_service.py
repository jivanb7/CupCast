"""
backend/services/ucl_fixture_service.py
==========================================
Fetch upcoming UCL fixtures from API-Football and seed them into the database.

API endpoint: GET https://v3.football.api-sports.io/fixtures?league=2&season=2024&status=NS
(NS = Not Started — gives us upcoming fixtures)

Also handles fetching recent UCL results for score updates.
"""

import logging
import time
from datetime import date, datetime
from typing import Optional

import requests
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# API-Football base URL
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

# UCL league ID in API-Football
UCL_LEAGUE_ID = 2

# Seconds to wait between API calls (rate-limit politeness)
REQUEST_DELAY = 0.5


def _current_ucl_season() -> int:
    """
    Compute the current UCL season year for API-Football.

    API-Football uses the calendar year the season STARTS.
    UCL seasons straddle two years (e.g., 2025-26 → season=2025).

    - If current month is July or later → season = current year
      (e.g., August 2025 → 2025 for the 2025-26 season)
    - If current month is before July → season = current year - 1
      (e.g., April 2026 → 2025 for the 2025-26 season)
    """
    today = date.today()
    if today.month >= 7:
        return today.year
    else:
        return today.year - 1


def _make_api_football_request(
    endpoint: str,
    params: dict,
    timeout: int = 20,
) -> Optional[dict]:
    """
    Make a single request to API-Football using the key rotator.

    Handles 429 by marking the key exhausted and retrying with the next key.
    Returns the parsed JSON body or None on failure.
    """
    from services.api_key_rotator import get_api_football_key, mark_key_exhausted

    url = f"{API_FOOTBALL_BASE}/{endpoint.lstrip('/')}"

    # Try up to 3 keys before giving up
    for attempt in range(3):
        try:
            key = get_api_football_key()
        except RuntimeError:
            logger.error("UCL fixture service: key rotator not initialized")
            return None

        headers = {"x-apisports-key": key}
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        except requests.RequestException as exc:
            logger.error("UCL API request failed (%s): %s", url, exc)
            return None

        if resp.status_code == 429:
            logger.warning(
                "UCL fixture service: 429 rate limit on key ...%s — marking exhausted", key[-8:]
            )
            mark_key_exhausted(key)
            continue

        if resp.status_code != 200:
            logger.error("UCL API returned %d for %s", resp.status_code, url)
            return None

        try:
            return resp.json()
        except Exception as exc:
            logger.error("UCL API response parse error: %s", exc)
            return None

    logger.error("UCL fixture service: all key attempts exhausted for %s", url)
    return None


def _parse_fixture(raw: dict) -> Optional[dict]:
    """
    Parse a single API-Football fixture dict into our internal schema.

    Returns a dict with:
      match_date, home_team, away_team, kickoff_time,
      league_code, round, status, home_goals, away_goals, result
    Returns None if the fixture is malformed.
    """
    try:
        from ml.src.team_name_mapping import resolve_team_name

        fixture = raw.get("fixture", {})
        teams = raw.get("teams", {})
        goals = raw.get("goals", {})
        league = raw.get("league", {})

        # Date / kickoff
        kickoff_iso = fixture.get("date")  # e.g. "2025-09-17T21:00:00+00:00"
        if not kickoff_iso:
            return None

        try:
            dt = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
            match_date = dt.date()
            kickoff_time = dt.strftime("%H:%M")
        except ValueError:
            logger.warning("UCL: could not parse date %r", kickoff_iso)
            return None

        # Team names — resolve through canonical mapping
        home_raw = teams.get("home", {}).get("name", "")
        away_raw = teams.get("away", {}).get("name", "")
        if not home_raw or not away_raw:
            return None

        home_team = resolve_team_name(home_raw, source="api_football_ucl")
        away_team = resolve_team_name(away_raw, source="api_football_ucl")

        # Goals (None when match not yet played)
        home_goals = goals.get("home")
        away_goals = goals.get("away")

        # Result
        result = None
        if home_goals is not None and away_goals is not None:
            if home_goals > away_goals:
                result = "H"
            elif home_goals < away_goals:
                result = "A"
            else:
                result = "D"

        # API-Football status short codes:
        # NS=Not Started, FT=Finished, 1H/HT/2H=In Progress, PST=Postponed, CANC=Cancelled
        api_status = fixture.get("status", {}).get("short", "NS")
        if api_status == "FT":
            internal_status = "completed"
        elif api_status == "NS":
            internal_status = "scheduled"
        elif api_status in ("1H", "HT", "2H", "ET", "PEN"):
            internal_status = "live"
        else:
            internal_status = "scheduled"

        return {
            "match_date": match_date,
            "home_team": home_team,
            "away_team": away_team,
            "kickoff_time": kickoff_time,
            "league_code": "UCL",
            "round": league.get("round", ""),
            "status": internal_status,
            "home_goals": home_goals,
            "away_goals": away_goals,
            "result": result,
        }
    except Exception as exc:
        logger.warning("UCL: failed to parse fixture: %s — %r", exc, raw)
        return None


def fetch_upcoming_ucl_fixtures() -> list[dict]:
    """
    Fetch the next 20 UCL fixtures from API-Football (status = Not Started).

    Returns a list of parsed fixture dicts. Empty list on failure.
    """
    season = _current_ucl_season()
    logger.info("Fetching upcoming UCL fixtures for season %d", season)

    data = _make_api_football_request(
        "fixtures",
        params={"league": UCL_LEAGUE_ID, "season": season, "next": 20},
    )
    if data is None:
        return []

    raw_fixtures = data.get("response", [])
    logger.info("UCL: received %d upcoming fixtures from API-Football", len(raw_fixtures))

    parsed = []
    for raw in raw_fixtures:
        fixture = _parse_fixture(raw)
        if fixture is not None:
            parsed.append(fixture)

    logger.info("UCL: parsed %d valid upcoming fixtures", len(parsed))
    return parsed


def fetch_recent_ucl_results() -> list[dict]:
    """
    Fetch the last 20 completed UCL matches from API-Football.

    Used for score backfill / result updates.
    Returns a list of parsed fixture dicts. Empty list on failure.
    """
    season = _current_ucl_season()
    logger.info("Fetching recent UCL results for season %d", season)

    data = _make_api_football_request(
        "fixtures",
        params={"league": UCL_LEAGUE_ID, "season": season, "last": 20},
    )
    if data is None:
        return []

    raw_fixtures = data.get("response", [])
    logger.info("UCL: received %d recent results from API-Football", len(raw_fixtures))

    parsed = []
    for raw in raw_fixtures:
        fixture = _parse_fixture(raw)
        if fixture is not None:
            parsed.append(fixture)

    logger.info("UCL: parsed %d valid recent results", len(parsed))
    return parsed


def seed_ucl_fixtures_to_db(db: Session) -> int:
    """
    Fetch upcoming UCL fixtures and insert them into the matches table.

    Logic:
    - Fetch upcoming fixtures via fetch_upcoming_ucl_fixtures()
    - Resolve each team to an existing Team record by canonical_name
      (UCL teams are already in the DB from their domestic leagues)
    - Find the UCL league entry (code="ucl")
    - Create Match records with status="scheduled"
    - Skip duplicates: same home_team + away_team + match_date already exists

    Returns the count of new fixtures seeded (skipped duplicates not counted).
    """
    from models.match import Match
    from models.team import Team
    from models.league import League

    fixtures = fetch_upcoming_ucl_fixtures()
    if not fixtures:
        logger.warning("UCL fixture seeding: no fixtures fetched")
        return 0

    # Find the UCL league record
    ucl_league = db.query(League).filter(League.code == "ucl").first()
    if ucl_league is None:
        logger.error(
            "UCL fixture seeding: league with code='ucl' not found in DB — "
            "run seed_database.py first to create the UCL league entry"
        )
        return 0

    # Determine current season label (e.g., "2025-26")
    season_year = _current_ucl_season()
    season_label = f"{season_year}-{str(season_year + 1)[2:]}"

    seeded = 0
    skipped = 0

    for fx in fixtures:
        match_date = fx["match_date"]
        home_name = fx["home_team"]
        away_name = fx["away_team"]

        # Check for existing match (dedup guard)
        existing = (
            db.query(Match)
            .join(Team, Match.home_team_id == Team.id)
            .filter(
                Match.match_date == match_date,
                Team.canonical_name == home_name,
            )
            .first()
        )
        if existing:
            # Verify away team also matches before calling it a true duplicate
            away_team_obj = db.query(Team).filter_by(id=existing.away_team_id).first()
            if away_team_obj and away_team_obj.canonical_name == away_name:
                skipped += 1
                continue

        # Resolve home team (must be a club — UCL has no national teams)
        home_team = db.query(Team).filter(
            Team.canonical_name == home_name,
            Team.team_type == "club",
        ).first()
        if home_team is None:
            logger.warning(
                "UCL fixture seeding: home team %r not found as club in DB — skipping match %s vs %s on %s",
                home_name, home_name, away_name, match_date,
            )
            continue

        # Resolve away team (must be a club — UCL has no national teams)
        away_team = db.query(Team).filter(
            Team.canonical_name == away_name,
            Team.team_type == "club",
        ).first()
        if away_team is None:
            logger.warning(
                "UCL fixture seeding: away team %r not found as club in DB — skipping match %s vs %s on %s",
                away_name, home_name, away_name, match_date,
            )
            continue

        match = Match(
            league_id=ucl_league.id,
            season=season_label,
            match_date=match_date,
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            kickoff_time=fx.get("kickoff_time"),
            tournament=fx.get("round", "UEFA Champions League"),
            match_importance="knockout",
            status="scheduled",
        )
        db.add(match)
        seeded += 1

    if seeded > 0:
        try:
            db.commit()
            logger.info("UCL fixture seeding: committed %d new fixtures (%d skipped)", seeded, skipped)
        except Exception as exc:
            db.rollback()
            logger.error("UCL fixture seeding: DB commit failed: %s", exc)
            return 0
    else:
        logger.info("UCL fixture seeding: no new fixtures to seed (%d already exist)", skipped)

    return seeded
