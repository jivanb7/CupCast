"""
backend/services/player_availability_service.py
================================================
Fetches and caches key player data (top scorers + injuries) from API-Football.
Computes a key_player_availability score (0.0–1.0) for use as an ML feature.

Data flow:
  1. refresh_top_scorers(db, league_code) — fetch /players/topscorers for the
     current season, upsert top 3 scorers per team as is_key_player=True.
  2. refresh_injuries(db, league_code) — fetch /injuries for the current season,
     upsert active injuries, mark old ones inactive.
  3. compute_key_player_availability(db, team_id, season) — query key players +
     their injury status; return fraction of goal-share that's available.
  4. refresh_all_leagues(db) — call (1) + (2) for all tracked leagues with a
     1-second delay between calls.

API cost: 2 calls per league × 10 leagues = 20 req/refresh run.
Daily budget: ~31 total calls — well within 600/day limit.

Usage:
    from services.player_availability_service import (
        refresh_all_leagues,
        refresh_top_scorers,
        refresh_injuries,
        compute_key_player_availability,
    )
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from sqlalchemy.orm import Session

from services.api_key_rotator import get_api_football_key, mark_key_exhausted
from models.player import Player
from models.player_injury import PlayerInjury
from models.team import Team
from models.league import League

logger = logging.getLogger(__name__)

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

# API-Football league IDs for all tracked leagues.
# National League uses 699 (Vanarama National League), not 43.
LEAGUE_API_FOOTBALL_IDS: dict[str, int] = {
    "epl": 39,
    "championship": 40,
    "league_one": 41,
    "league_two": 42,
    "national_league": 699,
    "laliga": 140,
    "seriea": 135,
    "bundesliga": 78,
    "ligue1": 61,
    "ucl": 2,
}


def _current_season() -> str:
    """Compute current API-Football season year as a string.

    API-Football uses the season *start* year:
      - 2025-26 season → "2025"
      - 2026-27 season → "2026"

    If month >= 7 (July onwards) we're in a new season that started this year.
    If month < 7 we're still in the season that started last year.

    NOTE: API-Football free tier caps at 2024. If the computed season exceeds
    the free tier limit, we fall back to 2024 (latest available).
    """
    now = datetime.now(timezone.utc)
    year = now.year if now.month >= 7 else now.year - 1
    # Free tier limit — cap at 2024
    FREE_TIER_MAX_SEASON = 2024
    if year > FREE_TIER_MAX_SEASON:
        logger.info(
            "API-Football free tier capped at season %d (computed %d), using %d",
            FREE_TIER_MAX_SEASON, year, FREE_TIER_MAX_SEASON,
        )
        year = FREE_TIER_MAX_SEASON
    return str(year)


def _api_get(endpoint: str, params: dict) -> Optional[dict]:
    """Make a single GET request to API-Football with 429 retry logic.

    Returns parsed JSON dict on success, or None on failure.
    Handles 429 by marking the key exhausted and retrying once with a new key.
    """
    for attempt in range(2):
        key = get_api_football_key()
        headers = {"x-apisports-key": key}
        url = f"{API_FOOTBALL_BASE}/{endpoint}"

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException as exc:
            logger.error("API-Football request failed (%s %s): %s", endpoint, params, exc)
            return None

        if resp.status_code == 429:
            logger.warning(
                "API-Football 429 on %s (key ...%s) — marking exhausted, attempt %d/2",
                endpoint, key[-8:], attempt + 1,
            )
            mark_key_exhausted(key)
            if attempt == 0:
                continue  # retry with new key
            logger.error("API-Football 429 on both attempts for %s — giving up", endpoint)
            return None

        if resp.status_code != 200:
            logger.error(
                "API-Football %d on %s params=%s", resp.status_code, endpoint, params
            )
            return None

        try:
            return resp.json()
        except Exception as exc:
            logger.error("API-Football JSON decode error on %s: %s", endpoint, exc)
            return None

    return None


def _find_league_id(db: Session, league_code: str) -> Optional[int]:
    """Look up the internal DB league.id for a given league code."""
    # Our DB uses codes like "epl", "ucl" etc.
    # But the seed may use the football-data.co.uk codes too — try both.
    league = db.query(League).filter(League.code == league_code).first()
    if league is None:
        logger.warning("League code '%s' not found in DB", league_code)
    return league.id if league else None


def _find_or_resolve_team(db: Session, api_team_name: str, api_team_id: int) -> Optional[Team]:
    """Find a Team record by canonical name, falling back to TeamNameAlias lookup.

    Strategy:
    1. Exact match on canonical_name
    2. Case-insensitive match on canonical_name
    3. Lookup via TeamNameAlias (source='api_football_ucl' or others)
    4. Return None and log warning if unresolvable
    """
    # Exact canonical match
    team = db.query(Team).filter(Team.canonical_name == api_team_name).first()
    if team:
        return team

    # Try TeamNameAlias
    try:
        from models.team import TeamNameAlias
        alias_row = (
            db.query(TeamNameAlias)
            .filter(TeamNameAlias.alias == api_team_name)
            .first()
        )
        if alias_row:
            return db.query(Team).filter(Team.id == alias_row.team_id).first()
    except Exception:
        pass

    # Try the team_name_mapping module (same logic as UCL fixture service)
    try:
        import sys
        from pathlib import Path
        ml_src = Path(__file__).resolve().parents[3] / "ml" / "src"
        if str(ml_src) not in sys.path:
            sys.path.insert(0, str(ml_src))
        from team_name_mapping import resolve_team_name
        canonical = resolve_team_name(api_team_name, source="api_football_ucl")
        if canonical != api_team_name:
            team = db.query(Team).filter(Team.canonical_name == canonical).first()
            if team:
                return team
    except Exception as exc:
        logger.debug("team_name_mapping import failed: %s", exc)

    logger.warning(
        "Cannot resolve API-Football team '%s' (id=%d) to a DB team — skipping",
        api_team_name, api_team_id,
    )
    return None


def refresh_top_scorers(db: Session, league_code: str) -> int:
    """Fetch top scorers from API-Football and upsert into the players table.

    Marks the top 3 goal scorers per team as is_key_player=True.
    All other players for the same team+season are set is_key_player=False.

    Returns:
        Number of player rows upserted.
    """
    api_league_id = LEAGUE_API_FOOTBALL_IDS.get(league_code)
    if api_league_id is None:
        logger.warning("refresh_top_scorers: unknown league_code '%s'", league_code)
        return 0

    season = _current_season()
    db_league_id = _find_league_id(db, league_code)

    logger.info("refresh_top_scorers: %s (API league %d, season %s)", league_code, api_league_id, season)

    data = _api_get("players/topscorers", {"league": api_league_id, "season": season})
    if data is None:
        return 0

    response_list = data.get("response", [])
    if not response_list:
        logger.info("refresh_top_scorers: empty response for %s season %s", league_code, season)
        return 0

    # Build a dict: team_id_api → list of (player_entry) sorted by goals desc
    # player_entry has: player.id, player.name, statistics[0].goals.total, statistics[0].team.*
    team_players: dict[int, list[dict]] = {}
    for entry in response_list:
        try:
            stats = entry.get("statistics", [{}])[0]
            team_api = stats.get("team", {})
            team_api_id = team_api.get("id")
            goals = stats.get("goals", {}).get("total") or 0
            if team_api_id is None:
                continue
            if team_api_id not in team_players:
                team_players[team_api_id] = []
            team_players[team_api_id].append({
                "player_api_id": entry.get("player", {}).get("id"),
                "player_name": entry.get("player", {}).get("name", "Unknown"),
                "goals": goals,
                "team_api_id": team_api_id,
                "team_name": team_api.get("name", ""),
            })
        except (KeyError, IndexError, TypeError) as exc:
            logger.debug("refresh_top_scorers: skipping malformed entry: %s", exc)
            continue

    upserted = 0

    for team_api_id, players_list in team_players.items():
        # Sort by goals descending; top 3 are key players
        players_list.sort(key=lambda p: p["goals"], reverse=True)
        team_total_goals = sum(p["goals"] for p in players_list)

        # Resolve team to DB record
        team_name = players_list[0]["team_name"] if players_list else ""
        db_team = _find_or_resolve_team(db, team_name, team_api_id)
        if db_team is None:
            continue

        # Top 3 are key players (or fewer if team has fewer scorers)
        key_player_api_ids = {
            p["player_api_id"]
            for p in players_list[:3]
            if p["player_api_id"] is not None
        }

        for rank, player_entry in enumerate(players_list):
            player_api_id = player_entry["player_api_id"]
            if player_api_id is None:
                continue

            is_key = player_api_id in key_player_api_ids
            goals = player_entry["goals"]
            goal_share = (goals / team_total_goals) if team_total_goals > 0 else 0.0

            # Upsert: match on api_football_id + season (enforced by UniqueConstraint)
            existing = (
                db.query(Player)
                .filter(
                    Player.api_football_id == player_api_id,
                    Player.season == season,
                )
                .first()
            )

            if existing:
                existing.name = player_entry["player_name"]
                existing.team_id = db_team.id
                existing.league_id = db_league_id
                existing.goals = goals
                existing.team_total_goals = team_total_goals
                existing.goal_share = goal_share
                existing.is_key_player = is_key
            else:
                new_player = Player(
                    api_football_id=player_api_id,
                    name=player_entry["player_name"],
                    team_id=db_team.id,
                    league_id=db_league_id,
                    season=season,
                    goals=goals,
                    team_total_goals=team_total_goals,
                    goal_share=goal_share,
                    is_key_player=is_key,
                )
                db.add(new_player)

            upserted += 1

    try:
        db.commit()
    except Exception as exc:
        logger.error("refresh_top_scorers: commit failed for %s: %s", league_code, exc)
        db.rollback()
        return 0

    logger.info("refresh_top_scorers: upserted %d players for %s", upserted, league_code)
    return upserted


def refresh_injuries(db: Session, league_code: str) -> int:
    """Fetch current injuries for a league from API-Football and sync to DB.

    One API call returns ALL current injuries for the entire league.
    Players no longer in the injury list have their records marked is_active=False.

    Returns:
        Number of injury rows created or updated.
    """
    api_league_id = LEAGUE_API_FOOTBALL_IDS.get(league_code)
    if api_league_id is None:
        logger.warning("refresh_injuries: unknown league_code '%s'", league_code)
        return 0

    season = _current_season()
    db_league_id = _find_league_id(db, league_code)

    logger.info("refresh_injuries: %s (API league %d, season %s)", league_code, api_league_id, season)

    data = _api_get("injuries", {"league": api_league_id, "season": season})
    if data is None:
        return 0

    response_list = data.get("response", [])

    # Build set of API player IDs currently injured, for deactivating stale records
    currently_injured_api_ids: set[int] = set()
    injury_by_api_id: dict[int, dict] = {}

    for entry in response_list:
        try:
            player_info = entry.get("player", {})
            api_player_id = player_info.get("id")
            if api_player_id is None:
                continue
            currently_injured_api_ids.add(api_player_id)
            injury_by_api_id[api_player_id] = {
                "injury_type": player_info.get("type"),
                "reason": player_info.get("reason"),
            }
        except (KeyError, TypeError) as exc:
            logger.debug("refresh_injuries: skipping malformed entry: %s", exc)
            continue

    updated = 0

    # Deactivate injuries for players no longer in the API response
    # Only look at players we actually track (those in our players table)
    if currently_injured_api_ids:
        tracked_player_api_ids_subquery = (
            db.query(Player.api_football_id, Player.id)
            .filter(Player.season == season)
            .all()
        )
        api_id_to_player_id = {row[0]: row[1] for row in tracked_player_api_ids_subquery}
    else:
        api_id_to_player_id = {}

    # For all tracked players with active injuries this season, deactivate if not in current list
    active_injuries = (
        db.query(PlayerInjury)
        .join(Player, PlayerInjury.player_id == Player.id)
        .filter(Player.season == season, PlayerInjury.is_active == True)  # noqa: E712
        .all()
    )

    for injury_record in active_injuries:
        # Find the api_football_id for this player
        player_row = db.query(Player).filter(Player.id == injury_record.player_id).first()
        if player_row and player_row.api_football_id not in currently_injured_api_ids:
            injury_record.is_active = False
            updated += 1

    # Upsert injuries for currently injured players that we track
    for api_player_id, injury_data in injury_by_api_id.items():
        player_id = api_id_to_player_id.get(api_player_id)
        if player_id is None:
            # This player isn't in our players table — skip (we only track key players)
            continue

        # Check for an existing active injury record for this player
        existing = (
            db.query(PlayerInjury)
            .filter(
                PlayerInjury.player_id == player_id,
                PlayerInjury.is_active == True,  # noqa: E712
            )
            .first()
        )

        if existing:
            # Update existing record
            existing.injury_type = injury_data["injury_type"]
            existing.reason = injury_data["reason"]
        else:
            # Create new injury record
            new_injury = PlayerInjury(
                player_id=player_id,
                injury_type=injury_data["injury_type"],
                reason=injury_data["reason"],
                is_active=True,
            )
            db.add(new_injury)

        updated += 1

    try:
        db.commit()
    except Exception as exc:
        logger.error("refresh_injuries: commit failed for %s: %s", league_code, exc)
        db.rollback()
        return 0

    logger.info(
        "refresh_injuries: %d records updated for %s (currently_injured=%d)",
        updated, league_code, len(currently_injured_api_ids),
    )
    return updated


def compute_key_player_availability(db: Session, team_id: int, season: str) -> float:
    """Compute the fraction of key-player goal-share currently available.

    Queries is_key_player=True players for the given team+season, checks which
    ones have an active injury, and returns the available goal-share fraction.

    Args:
        db: SQLAlchemy session.
        team_id: Internal DB team ID.
        season: Season string, e.g. "2025".

    Returns:
        Float in [0.0, 1.0].
        - 1.0 if no key players are tracked (optimistic default — no data).
        - 0.0 if all key players are injured.
        - Fraction otherwise.
    """
    key_players = (
        db.query(Player)
        .filter(
            Player.team_id == team_id,
            Player.season == season,
            Player.is_key_player == True,  # noqa: E712
        )
        .all()
    )

    if not key_players:
        return 1.0

    # Build a set of player_ids with active injuries for quick lookup
    key_player_ids = [p.id for p in key_players]
    injured_player_ids: set[int] = set(
        row[0]
        for row in db.query(PlayerInjury.player_id)
        .filter(
            PlayerInjury.player_id.in_(key_player_ids),
            PlayerInjury.is_active == True,  # noqa: E712
        )
        .all()
    )

    total_goal_share = sum(p.goal_share for p in key_players)
    if total_goal_share <= 0.0:
        # All goal_shares are 0 — fall back to counting available players
        available_count = sum(1 for p in key_players if p.id not in injured_player_ids)
        return available_count / len(key_players)

    available_goal_share = sum(
        p.goal_share for p in key_players if p.id not in injured_player_ids
    )

    return available_goal_share / total_goal_share


def refresh_all_leagues(db: Session) -> dict:
    """Refresh top scorers and injuries for all tracked leagues.

    Iterates LEAGUE_API_FOOTBALL_IDS, calls refresh_top_scorers() then
    refresh_injuries() for each league. Adds a 1-second delay between API
    calls to stay within rate limits. Wraps each league in try/except so
    one failure doesn't stop the rest.

    Returns:
        Dict mapping league_code → {"scorers_updated": int, "injuries_updated": int}.
    """
    summary: dict[str, dict] = {}

    for league_code in LEAGUE_API_FOOTBALL_IDS:
        try:
            scorers = refresh_top_scorers(db, league_code)
            time.sleep(1)
            injuries = refresh_injuries(db, league_code)
            time.sleep(1)
            summary[league_code] = {
                "scorers_updated": scorers,
                "injuries_updated": injuries,
            }
            logger.info(
                "refresh_all_leagues: %s done — scorers=%d injuries=%d",
                league_code, scorers, injuries,
            )
        except Exception as exc:
            logger.error("refresh_all_leagues: failed for %s: %s", league_code, exc)
            summary[league_code] = {"scorers_updated": 0, "injuries_updated": 0, "error": str(exc)}

    total_scorers = sum(v.get("scorers_updated", 0) for v in summary.values())
    total_injuries = sum(v.get("injuries_updated", 0) for v in summary.values())
    logger.info(
        "refresh_all_leagues: complete — total scorers=%d injuries=%d across %d leagues",
        total_scorers, total_injuries, len(summary),
    )

    return summary
