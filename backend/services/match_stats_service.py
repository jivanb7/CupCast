"""
backend/services/match_stats_service.py
========================================
Pull in-play match statistics (shots, shots on target, corners, fouls, cards)
from API-Football and persist them onto the matches row so the MatchDetail
"Key Stats" panel can render them while the game is being played and after
full time.

Why API-Football (not ESPN / FD.org):
  - ESPN exposes only a subset of stats and only after FT.
  - Football-Data.org's free tier doesn't return stats at all.
  - API-Football's /fixtures/statistics?fixture={id} returns the full set
    (Total Shots, Shots on Goal, Corner Kicks, Fouls, Yellow/Red Cards,
    Possession, Pass accuracy, expected_goals) and refreshes every ~5 min
    during the match. Coverage spans the same league set we already pull
    predictions + odds from, so nothing new to authorize.

Cost profile:
  Per match per sync = 2 API calls (1 to /fixtures for home/away team mapping,
  1 to /fixtures/statistics). With ~5 simultaneously live matches at peak and
  a 5-min cron cadence, that's ~12 cycles/hr × 5 matches × 2 calls = ~120
  calls/hr ≈ 2880/day, well under the 7500/day paid-tier quota. The shared
  api_key_rotator already sliding-window caps at 295 r/min so we won't burst.

Idempotency:
  ``update_match_stats`` overwrites whatever's currently in the stats columns
  with the latest API response. That's the desired behaviour during in-play
  (numbers tick up) and at FT (final snapshot lands). For matches with no
  api_football_id (older domestic-league rows whose stats already came from
  the football-data.co.uk CSV path) we skip — those columns are already
  populated by score_updater's CSV branch.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from sqlalchemy.orm import Session

from services.api_key_rotator import get_api_football_key, mark_key_exhausted

logger = logging.getLogger(__name__)

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

# Politeness delay between calls inside a bulk loop. Below the rotator's
# 295 r/min cap with comfortable margin so concurrent crons (live-sync,
# odds refresh) don't trip the limiter.
_INTER_CALL_SLEEP = 0.25

# Recently-completed window — sweep to catch the final snapshot for matches
# that flipped to FT in the last hour even if the score_updater already
# finalized them. Keeps the in-play→FT transition smooth without re-pulling
# stats for week-old matches every cron tick.
_RECENT_FT_HOURS = 2

_http = requests.Session()
_http.headers.update({"Accept": "application/json"})


# ---------------------------------------------------------------------------
# API-Football transport
# ---------------------------------------------------------------------------

def _api_get(endpoint: str, params: dict) -> Optional[dict]:
    """GET against API-Football with key rotation + one 429 retry.

    Mirrors the helper in api_football_predictions_service so this module can
    be lifted/dropped without depending on private symbols there. Returns the
    parsed JSON dict on success, None on any error (network, HTTP error, JSON
    decode failure). Callers treat None as "no data available".
    """
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
            logger.error("match_stats: network error on %s: %s", endpoint, exc)
            return None

        if resp.status_code == 429:
            logger.warning(
                "match_stats: 429 on %s (key ...%s) attempt %d/2",
                endpoint, key[-6:], attempt + 1,
            )
            mark_key_exhausted(key)
            if attempt == 0:
                time.sleep(1.0)
                continue
            return None

        if resp.status_code == 404:
            logger.debug("match_stats: 404 on %s params=%s", endpoint, params)
            return None

        if resp.status_code != 200:
            logger.error(
                "match_stats: HTTP %d on %s params=%s body=%s",
                resp.status_code, endpoint, params, resp.text[:200],
            )
            return None

        try:
            return resp.json()
        except Exception as exc:
            logger.error("match_stats: JSON decode error on %s: %s", endpoint, exc)
            return None

    return None


# ---------------------------------------------------------------------------
# Stat parsing
# ---------------------------------------------------------------------------

def _coerce_int(value) -> Optional[int]:
    """API-Football sends ints, ``None``, or strings like '5'. Coerce safely."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _stats_blocks_to_dict(stats_response: dict) -> dict[int, dict[str, object]]:
    """Reshape ``/fixtures/statistics`` payload into ``{team_api_id: {type: value}}``.

    The raw response is::

        {"response": [
            {"team": {"id": 85, ...}, "statistics": [
                {"type": "Total Shots", "value": 12}, ...
            ]},
            {"team": {"id": 157, ...}, "statistics": [...]},
        ]}

    We don't trust the order (home-first vs away-first isn't documented as
    guaranteed). Keying by team_api_id and matching against a separate
    /fixtures lookup is the only reliable mapping.
    """
    out: dict[int, dict[str, object]] = {}
    for block in stats_response.get("response", []) or []:
        team = block.get("team") or {}
        team_api_id = team.get("id")
        if team_api_id is None:
            continue
        type_to_value = {
            (s.get("type") or ""): s.get("value")
            for s in block.get("statistics", []) or []
        }
        out[int(team_api_id)] = type_to_value
    return out


# ---------------------------------------------------------------------------
# Single-match update
# ---------------------------------------------------------------------------

def update_match_stats(db: Session, match) -> bool:
    """Fetch + persist stats for a single match. Returns True iff any stat changed.

    Pre-conditions:
      - ``match.api_football_id`` must be set. Without it we can't address
        the fixture in API-Football. Callers should skip otherwise.

    Side effects:
      - Mutates ``match`` in place. Does NOT commit — caller controls the
        transaction so a sweep loop can batch many matches into one commit.

    Failure modes (all return False without raising):
      - api_football_id missing.
      - /fixtures lookup fails (network, 404).
      - /fixtures/statistics returns empty (match too early to have any
        stats yet — happens in the first ~5 min of kickoff).
      - team-id mapping fails (API-Football returns stats for teams whose
        IDs don't match the fixture's home/away — shouldn't happen, but
        guard against it).
    """
    if not match.api_football_id:
        return False

    fixture_id = match.api_football_id

    # Step 1 — resolve home/away team IDs from the fixture metadata.
    fixture_payload = _api_get("fixtures", {"id": fixture_id})
    if not fixture_payload or not fixture_payload.get("response"):
        return False

    fixture = fixture_payload["response"][0]
    teams = fixture.get("teams") or {}
    home_api_id = (teams.get("home") or {}).get("id")
    away_api_id = (teams.get("away") or {}).get("id")
    if home_api_id is None or away_api_id is None:
        logger.warning(
            "match_stats: fixture %d missing home/away team ids in /fixtures payload",
            fixture_id,
        )
        return False

    # Step 2 — pull the stats blocks.
    stats_payload = _api_get("fixtures/statistics", {"fixture": fixture_id})
    if not stats_payload or not stats_payload.get("response"):
        # Common during the first few minutes of kickoff when API-Football
        # hasn't published any stats yet. Not an error.
        return False

    stats_by_team = _stats_blocks_to_dict(stats_payload)
    home_stats = stats_by_team.get(int(home_api_id), {})
    away_stats = stats_by_team.get(int(away_api_id), {})
    if not home_stats and not away_stats:
        return False

    # Step 3 — map API-Football stat names to our DB columns. Only update
    # when the new value is non-None so a partial response doesn't wipe
    # earlier good data (some stats appear later than others — e.g.
    # Goalkeeper Saves only show up after the keeper's first touch).
    changed = False

    def _set(attr: str, new_value):
        nonlocal changed
        coerced = _coerce_int(new_value)
        if coerced is None:
            return
        if getattr(match, attr) != coerced:
            setattr(match, attr, coerced)
            changed = True

    _set("home_shots", home_stats.get("Total Shots"))
    _set("away_shots", away_stats.get("Total Shots"))
    _set("home_shots_on_target", home_stats.get("Shots on Goal"))
    _set("away_shots_on_target", away_stats.get("Shots on Goal"))
    _set("home_corners", home_stats.get("Corner Kicks"))
    _set("away_corners", away_stats.get("Corner Kicks"))
    _set("home_fouls", home_stats.get("Fouls"))
    _set("away_fouls", away_stats.get("Fouls"))
    _set("home_yellow_cards", home_stats.get("Yellow Cards"))
    _set("away_yellow_cards", away_stats.get("Yellow Cards"))
    _set("home_red_cards", home_stats.get("Red Cards"))
    _set("away_red_cards", away_stats.get("Red Cards"))

    return changed


# ---------------------------------------------------------------------------
# Bulk sweep — driven by the cron job
# ---------------------------------------------------------------------------

def sync_stats_for_live_and_recent(db: Session) -> dict:
    """Pull stats for every currently-live match plus matches that just FT'd.

    Targets:
      - status='live' rows: the in-play case. Stats refresh roughly every
        5 min upstream so we re-pull on every cron tick.
      - status='completed' AND updated_at within the last
        ``_RECENT_FT_HOURS``: catches the FT snapshot for matches that
        flipped between cron ticks (score_updater also calls
        update_match_stats inline on flip, but a second pass here is cheap
        and guards against a network blip on the inline call).

    Returns a stats dict for logging / admin response.
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
        "updated": 0,
        "no_change": 0,
        "no_stats": 0,
    }

    for m in candidates:
        try:
            changed = update_match_stats(db, m)
        except Exception as exc:
            logger.exception(
                "match_stats: unexpected error updating match %d (fixture %s): %s",
                m.id, m.api_football_id, exc,
            )
            counters["no_stats"] += 1
            continue

        if changed:
            counters["updated"] += 1
        elif (
            m.home_shots is None and m.away_shots is None
            and m.home_corners is None and m.away_corners is None
        ):
            counters["no_stats"] += 1
        else:
            counters["no_change"] += 1

        time.sleep(_INTER_CALL_SLEEP)

    if counters["updated"] > 0:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("match_stats: commit failed: %s", exc)
            counters["error"] = str(exc)

    logger.info("match_stats sync: %s", counters)
    return counters
