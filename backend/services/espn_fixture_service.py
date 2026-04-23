"""
backend/services/espn_fixture_service.py
==========================================
Seed upcoming matches from ESPN's public scoreboard API.

Why ESPN?
  - Public, no auth, no rate limit keying — useful redundancy alongside
    Football-Data.org (rate-limited free tier) and football-data.co.uk CSV.
  - Fills gaps in coverage: lower English divisions, MLS, WC, and sometimes
    picks up fixtures earlier than FDORG publishes them.

Endpoint (documented via community reverse-engineering; stable for years):
    GET https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard
        ?dates=YYYYMMDD-YYYYMMDD

Response shape (only fields we consume):
    {
      "events": [
        {
          "date": "2026-04-26T14:00Z",
          "competitions": [{
            "competitors": [
              {"homeAway": "home", "team": {"displayName": "Arsenal",
                                            "shortDisplayName": "Arsenal",
                                            "name": "Arsenal"}},
              {"homeAway": "away", "team": {...}}
            ]
          }]
        },
        ...
      ]
    }

Team name resolution piggybacks on fixture_seeder._resolve_team, which handles
exact/alias/normalized/fuzzy matching. ESPN's display names usually align with
Football-Data.org's (Arsenal, Chelsea, Real Madrid, etc.), so resolution hit
rate is high once the DB has canonical teams seeded.

Safe to re-run: matches are deduped on (home_team, away_team, league, date).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import requests
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_session = requests.Session()
_session.headers.update({
    # ESPN occasionally returns empty bodies for default python-requests UA.
    "User-Agent": "Mozilla/5.0 (cupcast-ingest)",
    "Accept": "application/json",
})

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# ESPN slug → our DB league code.
# NOTE: ESPN uses different slugs than football-data.org. These are stable.
ESPN_LEAGUES = {
    "eng.1": "epl",
    "eng.2": "championship",
    "eng.3": "league_one",
    "eng.4": "league_two",
    "eng.5": "national_league",
    "esp.1": "laliga",
    "ita.1": "seriea",
    "ger.1": "bundesliga",
    "fra.1": "ligue1",
    "uefa.champions": "ucl",
    "usa.1": "mls",
    "fifa.world": "worldcup",
}

# How far ahead to ask ESPN for fixtures. Most leagues only publish a few
# weeks out, so 30 days is plenty; larger windows slow the call without return.
LOOKAHEAD_DAYS = 30


def _current_season_str() -> str:
    # Same format as fixture_seeder._current_season_str.
    today = date.today()
    if today.month >= 7:
        return f"{today.year}-{str(today.year + 1)[2:]}"
    return f"{today.year - 1}-{str(today.year)[2:]}"


def _fetch_scoreboard(slug: str, start: date, end: date) -> list[dict]:
    """Fetch ESPN scoreboard events between start and end (inclusive).

    Returns the raw `events` list. Empty list on any error — ESPN is a
    best-effort source, so we never let a 500 here break the whole seed run.
    """
    url = f"{ESPN_BASE}/{slug}/scoreboard"
    params = {"dates": f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"}
    try:
        resp = _session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("events", []) or []
    except Exception as e:
        logger.warning("ESPN fetch failed for %s: %s", slug, e)
        return []


def _extract_teams(event: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (home_name, away_name) or (None, None) if malformed.

    Prefers `displayName` — ESPN's fullest form (e.g. "Manchester United") —
    since it aligns best with our DB's canonical_name.
    """
    competitions = event.get("competitions") or []
    if not competitions:
        return None, None
    competitors = competitions[0].get("competitors") or []
    home = away = None
    for c in competitors:
        team_block = c.get("team") or {}
        name = (
            team_block.get("displayName")
            or team_block.get("name")
            or team_block.get("shortDisplayName")
        )
        if c.get("homeAway") == "home":
            home = name
        elif c.get("homeAway") == "away":
            away = name
    return home, away


def seed_from_espn(db: Session) -> dict:
    """Fetch scheduled matches from ESPN for each mapped league and insert new ones.

    Delegates team resolution to fixture_seeder._resolve_team so name-normalization
    stays in one place. Dedupes on (home, away, league, date) to play nicely with
    Football-Data.org seeds that may have landed earlier in the same run.
    """
    from models.league import League
    from models.match import Match
    from services.fixture_seeder import _resolve_team

    stats = {"seeded": 0, "already_exists": 0, "skipped": 0, "unresolved": 0}

    start = date.today()
    end = start + timedelta(days=LOOKAHEAD_DAYS)

    for slug, db_league_code in ESPN_LEAGUES.items():
        league = db.query(League).filter(League.code == db_league_code).first()
        if not league:
            continue

        events = _fetch_scoreboard(slug, start, end)
        logger.info("ESPN %s (%s): %d events", slug, db_league_code, len(events))

        for ev in events:
            iso = ev.get("date") or ""
            if not iso:
                stats["skipped"] += 1
                continue

            # ESPN dates: "2026-04-26T14:00Z"
            try:
                # Python <3.11 handles "Z" via replace; cheap and explicit.
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                stats["skipped"] += 1
                continue

            match_date = dt.date()
            kickoff_time = dt.strftime("%H:%M")

            home_name, away_name = _extract_teams(ev)
            if not home_name or not away_name:
                stats["skipped"] += 1
                continue

            home_id = _resolve_team(db, home_name, db_league_code)
            away_id = _resolve_team(db, away_name, db_league_code)
            if not home_id or not away_id:
                stats["unresolved"] += 1
                logger.debug(
                    "ESPN unresolved: %s vs %s in %s", home_name, away_name, db_league_code
                )
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
                if kickoff_time and not existing.kickoff_time:
                    existing.kickoff_time = kickoff_time
                stats["already_exists"] += 1
                continue

            db.add(
                Match(
                    home_team_id=home_id,
                    away_team_id=away_id,
                    league_id=league.id,
                    match_date=match_date,
                    kickoff_time=kickoff_time,
                    status="scheduled",
                    season=_current_season_str(),
                )
            )
            stats["seeded"] += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to commit ESPN fixtures: %s", e)
        stats["error"] = str(e)

    logger.info("ESPN fixture seeder done: %s", stats)
    return stats
