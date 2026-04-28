"""
backend/services/api_football_predictions_service.py
======================================================
Fetches API-Football's proprietary match-win-probability estimates
(/predictions endpoint) and persists them for use as ML features.

Why "prediction in a prediction":
  API-Football's model internally aggregates lineup quality, xG history,
  head-to-head records, and recent form. By ingesting their output we get
  all that signal as a single feature vector without replicating the underlying
  data pipelines ourselves.

Response shape (only the ``percent`` block is extracted as floats):
    {
      "predictions": {
        "percent": {"home": "45%", "draw": "30%", "away": "25%"},
        ...
      },
      ...
    }

Rate-limit contract:
  API-Football paid tier: 7,500 req/day, ~300 req/min.
  The key rotator already enforces a 295 r/m sliding-window cap at the
  get_key() layer. We add a conservative 0.25 s sleep between loop
  iterations (≈ 240/min effective throughput) as a secondary guard and to
  be polite to the upstream server.

Usage:
    from services.api_football_predictions_service import (
        fetch_for_fixture,
        upsert_for_match,
        refresh_for_upcoming,
        backfill_for_recent,
    )
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import requests
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.api_key_rotator import get_api_football_key, mark_key_exhausted

logger = logging.getLogger(__name__)

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

# Seconds to sleep between successive API calls in bulk loops.
# Keeps effective throughput at ~240 req/min — safely under the 295 r/m cap
# that the rotator enforces, giving us a double safety margin.
_INTER_CALL_SLEEP = 0.25

# Log a progress line every N matches in bulk operations so long-running
# backfills aren't silent in Cloud Run logs.
_LOG_EVERY_N = 50

# Reuse a single requests.Session for connection pooling across calls.
_http = requests.Session()
_http.headers.update({"Accept": "application/json"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _api_get(endpoint: str, params: dict) -> Optional[dict]:
    """GET against API-Football with key rotation and one 429 retry.

    Returns the parsed JSON dict on success, None on any error (network,
    HTTP error, JSON decode failure). Callers treat None as "no data available".
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
            logger.error(
                "apifp: network error on %s params=%s: %s", endpoint, params, exc
            )
            return None

        if resp.status_code == 429:
            logger.warning(
                "apifp: 429 on %s (key ...%s) attempt %d/2",
                endpoint, key[-6:], attempt + 1,
            )
            mark_key_exhausted(key)
            if attempt == 0:
                time.sleep(1.0)  # brief back-off before retry with next key
                continue
            return None

        if resp.status_code == 404:
            # Fixture exists in our DB but API-Football has no prediction data.
            # Not an error — just missing coverage. Callers handle None.
            logger.debug("apifp: 404 on %s params=%s", endpoint, params)
            return None

        if resp.status_code != 200:
            logger.error(
                "apifp: HTTP %d on %s params=%s body=%s",
                resp.status_code, endpoint, params, resp.text[:200],
            )
            return None

        try:
            return resp.json()
        except Exception as exc:
            logger.error("apifp: JSON decode error on %s: %s", endpoint, exc)
            return None

    return None


def _parse_percent(value: Any) -> Optional[float]:
    """Convert API-Football percent string '45%' to float 0.45.

    Returns None if the value is absent, empty, or unparseable.
    This is intentionally lenient — upstream sometimes sends '0%' or None.
    """
    if value is None:
        return None
    s = str(value).strip().rstrip("%")
    if not s:
        return None
    try:
        pct = float(s)
        # Clamp to [0, 1] — API-Football occasionally sends values like
        # '100%' for an extreme favourite, which is fine, but guard against
        # data oddities.
        return max(0.0, min(1.0, pct / 100.0))
    except ValueError:
        logger.warning("apifp: could not parse percent value %r", value)
        return None


def _extract_probs(response: dict) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Pull (prob_home, prob_draw, prob_away) from a /predictions API response.

    Returns (None, None, None) when the percent block is absent.
    """
    items = response.get("response") or []
    if not items:
        return None, None, None

    predictions_block = (items[0] or {}).get("predictions") or {}
    percent = predictions_block.get("percent") or {}

    return (
        _parse_percent(percent.get("home")),
        _parse_percent(percent.get("draw")),
        _parse_percent(percent.get("away")),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_for_fixture(fixture_id: int) -> Optional[dict]:
    """Fetch API-Football's prediction for a single fixture.

    Calls GET /predictions?fixture={fixture_id}.

    Returns:
        {
            "prob_home": 0.45,   # float in [0, 1], or None
            "prob_draw": 0.30,
            "prob_away": 0.25,
            "raw_payload": { ... }  # full API response for future extraction
        }
        or None if the API returned no usable data (404, no percent block,
        network error, etc.).
    """
    data = _api_get("predictions", {"fixture": fixture_id})
    if data is None:
        return None

    # API-Football returns an empty response array for fixtures with no
    # prediction data (e.g. very early in the season, or postponed games).
    if not data.get("response"):
        logger.debug("apifp: empty response for fixture_id=%d", fixture_id)
        return None

    prob_home, prob_draw, prob_away = _extract_probs(data)

    return {
        "prob_home": prob_home,
        "prob_draw": prob_draw,
        "prob_away": prob_away,
        "raw_payload": data,
    }


def upsert_for_match(db: Session, match_id: int, fixture_id: int) -> bool:
    """Fetch and upsert the API-Football prediction for a single match.

    Uses PostgreSQL ON CONFLICT ... DO UPDATE so re-running is safe and the
    fetched_at timestamp reflects the most recent refresh.

    Args:
        db:         SQLAlchemy Session (caller owns lifecycle).
        match_id:   Our internal matches.id PK.
        fixture_id: API-Football fixture ID for this match.

    Returns:
        True on a successful fetch + upsert.
        False when the API returns no usable data (None from fetch_for_fixture).
    """
    result = fetch_for_fixture(fixture_id)
    if result is None:
        logger.debug(
            "apifp: no prediction data for match_id=%d fixture_id=%d",
            match_id, fixture_id,
        )
        return False

    now_utc = datetime.now(timezone.utc)

    try:
        db.execute(
            text("""
                INSERT INTO api_football_predictions
                    (match_id, prob_home, prob_draw, prob_away, raw_payload, fetched_at)
                VALUES
                    (:match_id, :prob_home, :prob_draw, :prob_away,
                     CAST(:raw_payload AS jsonb), :fetched_at)
                ON CONFLICT (match_id) DO UPDATE SET
                    prob_home   = EXCLUDED.prob_home,
                    prob_draw   = EXCLUDED.prob_draw,
                    prob_away   = EXCLUDED.prob_away,
                    raw_payload = EXCLUDED.raw_payload,
                    fetched_at  = EXCLUDED.fetched_at
            """),
            {
                "match_id": match_id,
                "prob_home": result["prob_home"],
                "prob_draw": result["prob_draw"],
                "prob_away": result["prob_away"],
                "raw_payload": _jsonb_dumps(result["raw_payload"]),
                "fetched_at": now_utc,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.error(
            "apifp: IntegrityError upserting match_id=%d: %s", match_id, exc
        )
        return False
    except Exception as exc:
        db.rollback()
        logger.error(
            "apifp: unexpected error upserting match_id=%d: %s", match_id, exc
        )
        return False

    return True


def refresh_for_upcoming(db: Session, days_ahead: int = 7) -> dict[str, Any]:
    """Bulk-refresh API-Football predictions for all upcoming scheduled matches.

    Queries matches with status='scheduled' and match_date in
    [today, today + days_ahead]. For each match, looks up the
    API-Football fixture_id via the match's api_football_fixture_id column if
    present, otherwise falls back to a /fixtures lookup by (league, date, teams).

    Args:
        db:         SQLAlchemy Session.
        days_ahead: How many calendar days forward to cover (default 7).

    Returns:
        Summary dict with counts: total, fetched, skipped, errors.
    """
    from models.match import Match
    from models.league import League
    from services.player_availability_service import LEAGUE_API_FOOTBALL_IDS

    today = date.today()
    until = today + timedelta(days=days_ahead)

    matches = (
        db.query(Match, League)
        .join(League, Match.league_id == League.id)
        .filter(
            Match.status == "scheduled",
            Match.match_date >= today,
            Match.match_date <= until,
        )
        .all()
    )

    summary: dict[str, Any] = {
        "mode": "upcoming",
        "days_ahead": days_ahead,
        "total": len(matches),
        "fetched": 0,
        "skipped_no_fixture_id": 0,
        "skipped_no_data": 0,
        "errors": 0,
    }

    counts = {"from_db": 0, "from_resolver": 0, "failed": 0}

    for i, (match, league) in enumerate(matches, start=1):
        if i % _LOG_EVERY_N == 0:
            logger.info(
                "apifp refresh_for_upcoming: %d/%d processed "
                "(fetched=%d skipped=%d errors=%d) [id_src: db=%d resolver=%d failed=%d]",
                i, len(matches),
                summary["fetched"],
                summary["skipped_no_fixture_id"] + summary["skipped_no_data"],
                summary["errors"],
                counts["from_db"], counts["from_resolver"], counts["failed"],
            )

        if match.api_football_id is not None:
            fixture_id = match.api_football_id
            counts["from_db"] += 1
        else:
            fixture_id = _resolve_fixture_id_via_teamnames(db, match, league, LEAGUE_API_FOOTBALL_IDS)
            if fixture_id is not None:
                counts["from_resolver"] += 1
            else:
                counts["failed"] += 1

        if fixture_id is None:
            summary["skipped_no_fixture_id"] += 1
            time.sleep(_INTER_CALL_SLEEP)
            continue

        ok = upsert_for_match(db, match.id, fixture_id)
        if ok:
            summary["fetched"] += 1
        else:
            summary["skipped_no_data"] += 1

        time.sleep(_INTER_CALL_SLEEP)

    summary["fixture_id_source"] = counts
    logger.info("apifp refresh_for_upcoming complete: %s", summary)
    return summary


def backfill_for_recent(
    db: Session,
    days_back: int = 120,
    leagues: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Backfill API-Football predictions for completed/scheduled matches.

    Covers matches with match_date in [today - days_back, today + 1] so that
    matches scheduled for tomorrow are also included when running at end of day.

    Args:
        db:        SQLAlchemy Session.
        days_back: How many calendar days back to cover (default 120).
        leagues:   Optional list of League.code values to restrict to
                   (e.g. ["E0", "SP1", "I1"]). None = all leagues.

    Returns:
        Summary dict with counts.
    """
    from models.match import Match
    from models.league import League
    from services.player_availability_service import LEAGUE_API_FOOTBALL_IDS

    today = date.today()
    cutoff = today - timedelta(days=days_back)
    until = today + timedelta(days=1)

    query = (
        db.query(Match, League)
        .join(League, Match.league_id == League.id)
        .filter(
            Match.match_date >= cutoff,
            Match.match_date <= until,
            Match.status.in_(["completed", "scheduled"]),
        )
    )

    if leagues:
        query = query.filter(League.code.in_(leagues))

    matches = query.order_by(Match.match_date).all()

    summary: dict[str, Any] = {
        "mode": "backfill",
        "days_back": days_back,
        "leagues": leagues,
        "total": len(matches),
        "fetched": 0,
        "skipped_no_fixture_id": 0,
        "skipped_no_data": 0,
        "errors": 0,
    }

    counts = {"from_db": 0, "from_resolver": 0, "failed": 0}

    for i, (match, league) in enumerate(matches, start=1):
        if i % _LOG_EVERY_N == 0:
            logger.info(
                "apifp backfill_for_recent: %d/%d processed "
                "(fetched=%d skipped=%d errors=%d) [id_src: db=%d resolver=%d failed=%d]",
                i, len(matches),
                summary["fetched"],
                summary["skipped_no_fixture_id"] + summary["skipped_no_data"],
                summary["errors"],
                counts["from_db"], counts["from_resolver"], counts["failed"],
            )

        if match.api_football_id is not None:
            fixture_id = match.api_football_id
            counts["from_db"] += 1
        else:
            fixture_id = _resolve_fixture_id_via_teamnames(db, match, league, LEAGUE_API_FOOTBALL_IDS)
            if fixture_id is not None:
                counts["from_resolver"] += 1
            else:
                counts["failed"] += 1

        if fixture_id is None:
            summary["skipped_no_fixture_id"] += 1
            time.sleep(_INTER_CALL_SLEEP)
            continue

        ok = upsert_for_match(db, match.id, fixture_id)
        if ok:
            summary["fetched"] += 1
        else:
            summary["skipped_no_data"] += 1

        time.sleep(_INTER_CALL_SLEEP)

    summary["fixture_id_source"] = counts
    logger.info("apifp backfill_for_recent complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Internal: fixture-ID resolution
# ---------------------------------------------------------------------------

# Cache: (api_league_id, season_str, match_date_iso) → list of API-Football
# fixture dicts. Avoids re-fetching the same league-day page for every match
# in a multi-match day (e.g. a full EPL game-week has 10 matches).
_fixture_cache: dict[tuple, list[dict]] = {}


def _resolve_fixture_id_via_teamnames(
    db: Session,
    match: Any,
    league: Any,
    league_id_map: dict[str, int],
) -> Optional[int]:
    """Fallback: map an internal Match row to an API-Football fixture_id via
    team-name resolution against the /fixtures endpoint.

    Only called when match.api_football_id is NULL (legacy rows from
    football-data.co.uk CSV ingest, or rows seeded before this column existed).

    Strategy:
      1. Look up league.code in LEAGUE_API_FOOTBALL_IDS.
      2. Fetch /fixtures for (api_league_id, season, match_date) — cached per
         (api_league_id, season, date) to save API quota on bulk runs.
      3. Match the returned fixtures to our Match by team-name resolution
         (same fuzzy resolver used by revalidate_recent_scores).
      4. Return the matched fixture's API-Football id, or None if unresolved.

    Callers prefer match.api_football_id when non-NULL; this resolver is the
    last resort for rows that predate the api_football_id column.
    """
    api_league_id = league_id_map.get(league.code)
    if api_league_id is None:
        return None

    season = _current_season()
    cache_key = (api_league_id, season, match.match_date.isoformat())

    if cache_key not in _fixture_cache:
        data = _api_get(
            "fixtures",
            {
                "league": api_league_id,
                "season": season,
                "date": match.match_date.isoformat(),
            },
        )
        time.sleep(_INTER_CALL_SLEEP)  # pace the /fixtures lookup calls too
        _fixture_cache[cache_key] = (data or {}).get("response") or []

    fixtures = _fixture_cache[cache_key]
    if not fixtures:
        return None

    # Resolve each candidate fixture to our Match and return when matched.
    try:
        from services.odds_service import _resolve_team_for_odds
    except ImportError:
        logger.warning("apifp: odds_service not available — cannot resolve teams")
        return None

    for fx in fixtures:
        teams = fx.get("teams") or {}
        home_api = teams.get("home") or {}
        away_api = teams.get("away") or {}

        home_team = _resolve_team_for_odds(
            db,
            home_api.get("name", ""),
            home_api.get("id") or 0,
            match.league_id,
        )
        away_team = _resolve_team_for_odds(
            db,
            away_api.get("name", ""),
            away_api.get("id") or 0,
            match.league_id,
        )

        if home_team and away_team:
            if home_team.id == match.home_team_id and away_team.id == match.away_team_id:
                fx_id = (fx.get("fixture") or {}).get("id")
                if fx_id is not None:
                    return int(fx_id)

    logger.debug(
        "apifp: no fixture match for match_id=%d (%s vs %s on %s)",
        match.id, match.home_team_id, match.away_team_id, match.match_date,
    )
    return None


def _current_season() -> str:
    """API-Football season key (start year). Mirrors odds_service logic."""
    now = datetime.now(timezone.utc)
    return str(now.year if now.month >= 7 else now.year - 1)


def _jsonb_dumps(obj: Any) -> str:
    """Serialize to JSON string for the CAST(:raw_payload AS jsonb) parameter."""
    import json
    return json.dumps(obj, default=str)
