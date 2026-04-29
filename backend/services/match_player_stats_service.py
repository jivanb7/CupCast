"""
backend/services/match_player_stats_service.py
================================================
Pull per-match per-player statistics from API-Football's
``/fixtures/players?fixture={id}`` endpoint and upsert them into
match_player_stats.

Why this exists:
  Team-level stats (services/match_stats_service) tell you "Atlético had
  18 shots". Player-level stats tell you who scored, who got booked, who
  played, who started, and who's been the in-form goalscorer this month —
  signal both the UI (goal-scorer attribution next to the score) and the
  ML pipeline (player form features) need.

Cron contract:
  Same 5-min cron tick as match_stats_service. The two services share a
  candidate pool (matches with api_football_id that are live OR finalised
  in the last ``_RECENT_FT_HOURS`` hours) so we don't double-query the
  matches table. ``sync_player_stats_for_live_and_recent`` mirrors the
  signature of its team-stats sibling.

Cost profile:
  +1 API-Football call per match per cycle on top of the team-stats sync.
  At peak (~5 simultaneous live matches × 12 ticks/hr × 1 call) that's
  ~60 calls/hr — combined with team stats we're at ~180/hr ≈ 4,300/day,
  comfortably under the 7,500/day paid-tier quota.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.api_key_rotator import get_api_football_key, mark_key_exhausted

logger = logging.getLogger(__name__)

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

# Politeness delay; same as the team-stats service so the rotator's
# 295 r/min cap stays comfortable when both syncs interleave.
_INTER_CALL_SLEEP = 0.25

# Match window — matches kept active for sync this many hours after FT.
# Keep aligned with match_stats_service so the two cron sweeps target the
# same set of rows on every tick.
_RECENT_FT_HOURS = 2

_http = requests.Session()
_http.headers.update({"Accept": "application/json"})


# ---------------------------------------------------------------------------
# API-Football transport (mirrors match_stats_service._api_get)
# ---------------------------------------------------------------------------

def _api_get(endpoint: str, params: dict) -> Optional[dict]:
    """GET against API-Football with key rotation + one 429 retry."""
    for attempt in range(2):
        key = get_api_football_key()
        url = f"{API_FOOTBALL_BASE}/{endpoint}"
        try:
            resp = _http.get(
                url,
                headers={"x-apisports-key": key},
                params=params,
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.error("player_stats: network error on %s: %s", endpoint, exc)
            return None

        if resp.status_code == 429:
            logger.warning(
                "player_stats: 429 on %s (key ...%s) attempt %d/2",
                endpoint, key[-6:], attempt + 1,
            )
            mark_key_exhausted(key)
            if attempt == 0:
                time.sleep(1.0)
                continue
            return None

        if resp.status_code == 404:
            logger.debug("player_stats: 404 on %s params=%s", endpoint, params)
            return None

        if resp.status_code != 200:
            logger.error(
                "player_stats: HTTP %d on %s params=%s body=%s",
                resp.status_code, endpoint, params, resp.text[:200],
            )
            return None

        try:
            return resp.json()
        except Exception as exc:
            logger.error("player_stats: JSON decode error on %s: %s", endpoint, exc)
            return None

    return None


# ---------------------------------------------------------------------------
# Stat parsing
# ---------------------------------------------------------------------------

def _coerce_int(value, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _coerce_rating(value) -> Optional[float]:
    """API-Football returns rating as string like '7.8'. Coerce to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Single-match update
# ---------------------------------------------------------------------------

def update_player_stats(db: Session, match) -> int:
    """Fetch + upsert player stats for a single match. Returns rows touched.

    Pre-conditions: ``match.api_football_id`` set; otherwise no-op.

    Side effects: upserts into match_player_stats. Caller commits.

    Failure modes (return 0, don't raise):
      - api_football_id missing.
      - /fixtures lookup fails (network, 404).
      - /fixtures/players returns empty (early kickoff — players haven't
        started accumulating stats yet).
      - Team-id mapping fails for some reason.
    """
    if not match.api_football_id:
        return 0

    fixture_id = match.api_football_id

    # Step 1 — resolve home/away team IDs (we need the API-Football team
    # IDs to map each /fixtures/players block onto our DB team_id).
    fixture_payload = _api_get("fixtures", {"id": fixture_id})
    if not fixture_payload or not fixture_payload.get("response"):
        return 0
    fixture = fixture_payload["response"][0]
    teams = fixture.get("teams") or {}
    home_api_id = (teams.get("home") or {}).get("id")
    away_api_id = (teams.get("away") or {}).get("id")
    if home_api_id is None or away_api_id is None:
        return 0

    api_to_db_team = {
        int(home_api_id): match.home_team_id,
        int(away_api_id): match.away_team_id,
    }

    # Step 2 — pull the player stats blocks.
    players_payload = _api_get("fixtures/players", {"fixture": fixture_id})
    if not players_payload or not players_payload.get("response"):
        return 0

    # Step 3 — flatten into upsert rows. Skip any block whose team_id
    # we can't map (defensive — shouldn't happen for well-formed fixtures).
    rows: list[dict] = []
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    for team_block in players_payload["response"]:
        team_info = team_block.get("team") or {}
        team_api_id = team_info.get("id")
        if team_api_id is None:
            continue
        db_team_id = api_to_db_team.get(int(team_api_id))
        if db_team_id is None:
            continue

        for entry in team_block.get("players", []) or []:
            player_info = entry.get("player") or {}
            player_api_id = player_info.get("id")
            player_name = (player_info.get("name") or "").strip()
            if not player_api_id or not player_name:
                continue

            # /fixtures/players nests stats inside a single-element list
            # (one stat-line per player per match).
            stat_lines = entry.get("statistics") or []
            if not stat_lines:
                continue
            stat = stat_lines[0] or {}

            games = stat.get("games") or {}
            shots = stat.get("shots") or {}
            goals = stat.get("goals") or {}
            cards = stat.get("cards") or {}

            rows.append({
                "match_id": match.id,
                "team_id": db_team_id,
                "player_api_football_id": int(player_api_id),
                "player_name": player_name,
                "player_photo_url": player_info.get("photo"),
                "position": (games.get("position") or None),
                "jersey_number": _coerce_int(games.get("number")),
                "minutes_played": _coerce_int(games.get("minutes")),
                "rating": _coerce_rating(games.get("rating")),
                "goals": _coerce_int(goals.get("total"), default=0) or 0,
                "assists": _coerce_int(goals.get("assists"), default=0) or 0,
                "shots_total": _coerce_int(shots.get("total"), default=0) or 0,
                "shots_on": _coerce_int(shots.get("on"), default=0) or 0,
                "yellow_cards": _coerce_int(cards.get("yellow"), default=0) or 0,
                "red_cards": _coerce_int(cards.get("red"), default=0) or 0,
                "is_starter": not bool(games.get("substitute")),
                "fetched_at": now_naive,
            })

    if not rows:
        return 0

    # Step 4 — upsert via PostgreSQL ON CONFLICT. Re-running mid-match
    # overwrites running totals (goals tick up, minutes climb, rating
    # refines) without inserting duplicate rows.
    upsert_sql = text("""
        INSERT INTO match_player_stats (
            match_id, team_id, player_api_football_id, player_name,
            player_photo_url, position, jersey_number, minutes_played,
            rating, goals, assists, shots_total, shots_on,
            yellow_cards, red_cards, is_starter, fetched_at
        ) VALUES (
            :match_id, :team_id, :player_api_football_id, :player_name,
            :player_photo_url, :position, :jersey_number, :minutes_played,
            :rating, :goals, :assists, :shots_total, :shots_on,
            :yellow_cards, :red_cards, :is_starter, :fetched_at
        )
        ON CONFLICT (match_id, player_api_football_id) DO UPDATE SET
            team_id = EXCLUDED.team_id,
            player_name = EXCLUDED.player_name,
            player_photo_url = EXCLUDED.player_photo_url,
            position = EXCLUDED.position,
            jersey_number = EXCLUDED.jersey_number,
            minutes_played = EXCLUDED.minutes_played,
            rating = EXCLUDED.rating,
            goals = EXCLUDED.goals,
            assists = EXCLUDED.assists,
            shots_total = EXCLUDED.shots_total,
            shots_on = EXCLUDED.shots_on,
            yellow_cards = EXCLUDED.yellow_cards,
            red_cards = EXCLUDED.red_cards,
            is_starter = EXCLUDED.is_starter,
            fetched_at = EXCLUDED.fetched_at
    """)

    for row in rows:
        try:
            db.execute(upsert_sql, row)
        except Exception as exc:
            # Single-row failure shouldn't kill the whole batch.
            logger.warning(
                "player_stats: upsert failed for match=%d player=%d: %s",
                row["match_id"], row["player_api_football_id"], exc,
            )

    return len(rows)


# ---------------------------------------------------------------------------
# Bulk sweep — driven by the cron job
# ---------------------------------------------------------------------------

def sync_player_stats_for_live_and_recent(db: Session) -> dict:
    """Pull player stats for live + recently-completed matches.

    Mirrors match_stats_service.sync_stats_for_live_and_recent's candidate
    selection so a single cron tick covers both team and player stats.

    Returns counters dict for logging / admin response.
    """
    from models.match import Match

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ft_cutoff = now - timedelta(hours=_RECENT_FT_HOURS)

    candidates = (
        db.query(Match)
        .filter(
            Match.api_football_id.isnot(None),
            (
                (Match.status == "live")
                | (
                    (Match.status == "completed")
                    & (Match.updated_at >= ft_cutoff)
                )
            ),
        )
        .all()
    )

    counters = {
        "candidates": len(candidates),
        "rows_upserted": 0,
        "no_data": 0,
        "errors": 0,
    }

    for m in candidates:
        try:
            n = update_player_stats(db, m)
        except Exception as exc:
            logger.exception(
                "player_stats: unexpected error for match %d (fixture %s): %s",
                m.id, m.api_football_id, exc,
            )
            counters["errors"] += 1
            continue

        if n == 0:
            counters["no_data"] += 1
        else:
            counters["rows_upserted"] += n

        time.sleep(_INTER_CALL_SLEEP)

    if counters["rows_upserted"] > 0:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("player_stats: commit failed: %s", exc)
            counters["error"] = str(exc)

    logger.info("player_stats sync: %s", counters)
    return counters
