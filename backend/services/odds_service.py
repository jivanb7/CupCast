"""
backend/services/odds_service.py
===================================
Fetches match-winner (1X2) odds from API-Football and stamps them onto
upcoming Prediction rows, then recomputes edges + is_value_pick flags.

Why this exists
  generate_batch_predictions creates predictions with odds_home/draw/away = None,
  which means compute_edge() returns None and no prediction ever gets flagged
  as a value pick. This service fills that gap by running *after* predictions.

Flow per league
  1. GET /fixtures?league=X&season=Y&from=today&to=today+14d
     → map fixture_id → (home_team_name, away_team_name, date)
  2. GET /odds?league=X&season=Y&bookmaker=8&bet=1 (paginated)
     → filter to the fixture_ids we just fetched, extract H/D/A odds
  3. Resolve API team names to DB Team rows (reuses name resolution from
     player_availability_service)
  4. For each matched DB Match, update every Prediction row:
     - set odds_home, odds_draw, odds_away
     - run compute_edge() and refresh edge_home/draw/away,
       is_value_pick, value_pick_direction

API cost
  ~5 calls/league (1 fixtures + ~4 odds pages). 10 leagues × 5 = ~50/refresh.
  Running 07:30 + 15:00 UTC daily = ~100/day, ~1% of Pro plan (7,500/day).

Usage
    from services.odds_service import refresh_all_leagues_odds, refresh_odds_for_league

    stats = refresh_all_leagues_odds(db)
    # or single league:
    stats = refresh_odds_for_league(db, "epl")
"""

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests
from sqlalchemy.orm import Session

from sqlalchemy import func

# Module-level Session for connection pooling across scheduler job invocations
_session = requests.Session()

from models.league import League
from models.match import Match
from models.prediction import Prediction
from models.team import Team
from services.api_key_rotator import get_api_football_key, mark_key_exhausted
from services.edge_service import compute_edge
from services.player_availability_service import (
    LEAGUE_API_FOOTBALL_IDS,
    _find_or_resolve_team,
)


def _resolve_team_for_odds(db: Session, api_name: str, api_id: int, league_id: int) -> Optional[Team]:
    """Team resolver tuned for API-Football odds responses.

    API-Football returns short names (e.g. "Crystal Palace") while our DB uses
    canonical names (e.g. "Crystal Palace FC"). We first delegate to the shared
    resolver (canonical + alias lookups), then fall back to a scoped scan that
    treats the API name as either a prefix of or equal to the DB short_name.

    The scan is scoped to ``league_id`` to avoid cross-league collisions like
    "Manchester City" matching "Manchester City WFC".
    """
    team = _find_or_resolve_team(db, api_name, api_id)
    if team is not None:
        return team

    if not api_name:
        return None

    # Scope to league teams only
    candidates = db.query(Team).filter(Team.league_id == league_id).all()
    if not candidates:
        # Some leagues have cross-league teams (UCL etc.); fall back to global scan
        candidates = db.query(Team).all()

    api_lower = api_name.strip().lower()

    # 1) exact short_name match
    for t in candidates:
        if t.short_name and t.short_name.strip().lower() == api_lower:
            return t

    # 2) canonical_name startswith api_name + boundary
    for t in candidates:
        if t.canonical_name and t.canonical_name.lower().startswith(api_lower + " "):
            return t

    # 3) canonical_name == api_name case-insensitive
    for t in candidates:
        if t.canonical_name and t.canonical_name.lower() == api_lower:
            return t

    # 4) api_name startswith short_name (e.g. API "Brighton" vs short "Brighton")
    for t in candidates:
        sn = (t.short_name or "").strip().lower()
        if sn and api_lower.startswith(sn):
            return t

    # 5) substring contains (last resort — may over-match, but league-scoped)
    for t in candidates:
        cn = (t.canonical_name or "").lower()
        if cn and api_lower in cn:
            return t

    logger.warning(
        "odds_service: cannot resolve API team '%s' (id=%d) in league_id=%d",
        api_name, api_id, league_id,
    )
    return None


def _current_season() -> str:
    """Current API-Football season as a string (e.g. '2025' for the 2025-26 season).

    API-Football keys seasons by their *start* year:
      - 2025-26 season → '2025'
      - 2026-27 season → '2026'

    The cutover is July (month >= 7 means a new season just started).

    Note: a Pro-plan account has no cap on recent seasons, unlike the free tier
    helper in player_availability_service (_current_season) which caps at 2024.
    We keep our own copy here because odds only make sense for the *current*
    season.
    """
    now = datetime.now(timezone.utc)
    year = now.year if now.month >= 7 else now.year - 1
    return str(year)

logger = logging.getLogger(__name__)

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

# Bet365 is the most consistently populated bookmaker across leagues.
# We fall back to "any available" if Bet365 is missing for a given fixture.
BOOKMAKER_ID_BET365 = 8
BET_ID_MATCH_WINNER = 1  # 1X2 (Home / Draw / Away)

DEFAULT_DAYS_AHEAD = 14

# Safety cap on pagination to avoid runaway requests if the API misreports paging.
MAX_ODDS_PAGES = 20


def _api_get(endpoint: str, params: dict) -> Optional[dict]:
    """GET against API-Football with 429 → rotate-key retry logic."""
    for attempt in range(2):
        key = get_api_football_key()
        url = f"{API_FOOTBALL_BASE}/{endpoint}"
        try:
            resp = _session.get(
                url, headers={"x-apisports-key": key}, params=params, timeout=15
            )
        except requests.RequestException as exc:
            logger.error("odds_service: %s request failed params=%s: %s", endpoint, params, exc)
            return None

        if resp.status_code == 429:
            logger.warning(
                "odds_service: 429 on %s (key ...%s) attempt %d/2",
                endpoint, key[-6:], attempt + 1,
            )
            mark_key_exhausted(key)
            if attempt == 0:
                continue
            return None

        if resp.status_code != 200:
            logger.error(
                "odds_service: HTTP %d on %s params=%s body=%s",
                resp.status_code, endpoint, params, resp.text[:200],
            )
            return None

        try:
            return resp.json()
        except Exception as exc:
            logger.error("odds_service: JSON decode error on %s: %s", endpoint, exc)
            return None

    return None


def _extract_hda_odds(odds_entry: dict) -> Optional[tuple[float, float, float]]:
    """Pull (home, draw, away) decimal odds from one /odds response entry.

    Prefers Bet365 (id=8); falls back to the first bookmaker that has a
    complete H/D/A triple on bet id=1 (Match Winner).
    """
    def _triple_from_bookmaker(bm: dict) -> Optional[tuple[float, float, float]]:
        for bet in bm.get("bets", []):
            if bet.get("id") != BET_ID_MATCH_WINNER:
                continue
            h = d = a = None
            for v in bet.get("values", []):
                label = (v.get("value") or "").strip().lower()
                try:
                    odd = float(v.get("odd"))
                except (TypeError, ValueError):
                    continue
                if label == "home":
                    h = odd
                elif label == "draw":
                    d = odd
                elif label == "away":
                    a = odd
            if h and d and a and h > 1.0 and d > 1.0 and a > 1.0:
                return h, d, a
        return None

    bookmakers = odds_entry.get("bookmakers", []) or []

    # First pass: Bet365
    for bm in bookmakers:
        if bm.get("id") == BOOKMAKER_ID_BET365:
            triple = _triple_from_bookmaker(bm)
            if triple:
                return triple

    # Fallback: any bookmaker with a complete H/D/A triple
    for bm in bookmakers:
        triple = _triple_from_bookmaker(bm)
        if triple:
            return triple

    return None


def _fetch_upcoming_fixtures(api_league_id: int, season: str, days_ahead: int) -> dict[int, dict]:
    """Return fixture_id → fixture payload for upcoming matches in [today, today+days_ahead]."""
    today = date.today()
    until = today + timedelta(days=days_ahead)
    resp = _api_get(
        "fixtures",
        {
            "league": api_league_id,
            "season": season,
            "from": today.isoformat(),
            "to": until.isoformat(),
        },
    )
    if resp is None:
        return {}

    fixture_map: dict[int, dict] = {}
    for fx in resp.get("response", []):
        fx_id = fx.get("fixture", {}).get("id")
        if fx_id is not None:
            fixture_map[int(fx_id)] = fx
    return fixture_map


def _fetch_odds_for_league(api_league_id: int, season: str, fixture_ids: set[int]) -> dict[int, tuple[float, float, float]]:
    """Paginate /odds for the league/season, return fixture_id → (H, D, A) for
    fixtures present in ``fixture_ids``."""
    odds_by_fixture: dict[int, tuple[float, float, float]] = {}
    page = 1
    while page <= MAX_ODDS_PAGES:
        resp = _api_get(
            "odds",
            {
                "league": api_league_id,
                "season": season,
                "bookmaker": BOOKMAKER_ID_BET365,
                "bet": BET_ID_MATCH_WINNER,
                "page": page,
            },
        )
        if resp is None:
            break

        entries = resp.get("response", []) or []
        for entry in entries:
            fx_id = entry.get("fixture", {}).get("id")
            if fx_id is None or int(fx_id) not in fixture_ids:
                continue
            triple = _extract_hda_odds(entry)
            if triple is not None:
                odds_by_fixture[int(fx_id)] = triple

        paging = resp.get("paging", {}) or {}
        total_pages = int(paging.get("total") or 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.2)  # gentle pacing; rotator enforces the hard 295 r/min cap

    return odds_by_fixture


def _apply_odds_to_predictions(
    db: Session,
    match: Match,
    odds_home: float,
    odds_draw: float,
    odds_away: float,
) -> int:
    """Stamp odds + recomputed edges onto every Prediction for ``match``.
    Returns the number of prediction rows updated."""
    preds = db.query(Prediction).filter(Prediction.match_id == match.id).all()
    if not preds:
        return 0

    for pred in preds:
        pred.odds_home = odds_home
        pred.odds_draw = odds_draw
        pred.odds_away = odds_away
        edge = compute_edge(
            prob_home=float(pred.prob_home_win),
            prob_draw=float(pred.prob_draw),
            prob_away=float(pred.prob_away_win),
            odds_home=odds_home,
            odds_draw=odds_draw,
            odds_away=odds_away,
        )
        if edge is not None:
            pred.edge_home = edge.edge_home
            pred.edge_draw = edge.edge_draw
            pred.edge_away = edge.edge_away
            pred.is_value_pick = edge.is_value_pick
            pred.value_pick_direction = edge.value_pick_direction

    return len(preds)


def refresh_odds_for_league(
    db: Session,
    league_code: str,
    days_ahead: int = DEFAULT_DAYS_AHEAD,
) -> dict:
    """Fetch odds for upcoming matches in one league and update predictions."""
    api_league_id = LEAGUE_API_FOOTBALL_IDS.get(league_code)
    if api_league_id is None:
        logger.warning("refresh_odds_for_league: unknown league_code '%s'", league_code)
        return {
            "league": league_code,
            "fixtures_upcoming": 0,
            "fixtures_with_odds": 0,
            "predictions_updated": 0,
            "matches_updated": 0,
        }

    league_obj = db.query(League).filter(League.code == league_code).first()
    if league_obj is None:
        logger.warning("refresh_odds_for_league: league code '%s' missing in DB", league_code)
        return {
            "league": league_code,
            "fixtures_upcoming": 0,
            "fixtures_with_odds": 0,
            "predictions_updated": 0,
            "matches_updated": 0,
        }

    season = _current_season()
    logger.info(
        "refresh_odds_for_league: %s (api_league=%d season=%s)",
        league_code, api_league_id, season,
    )

    # Step 1: upcoming fixtures
    fixture_map = _fetch_upcoming_fixtures(api_league_id, season, days_ahead)
    if not fixture_map:
        logger.info("refresh_odds_for_league %s: no upcoming fixtures", league_code)
        return {
            "league": league_code,
            "fixtures_upcoming": 0,
            "fixtures_with_odds": 0,
            "predictions_updated": 0,
            "matches_updated": 0,
        }

    # Step 2: odds for those fixtures
    odds_by_fixture = _fetch_odds_for_league(api_league_id, season, set(fixture_map.keys()))
    logger.info(
        "refresh_odds_for_league %s: %d upcoming fixtures, %d with odds",
        league_code, len(fixture_map), len(odds_by_fixture),
    )

    # Step 3: resolve fixture → DB match, update predictions
    matches_updated = 0
    predictions_updated = 0

    for fx_id, hda in odds_by_fixture.items():
        fx = fixture_map.get(fx_id)
        if not fx:
            continue

        fx_date_str = fx.get("fixture", {}).get("date")
        teams = fx.get("teams", {}) or {}
        home_api = teams.get("home", {}) or {}
        away_api = teams.get("away", {}) or {}

        try:
            fx_dt = datetime.fromisoformat(fx_date_str.replace("Z", "+00:00"))
            fx_date = fx_dt.astimezone(timezone.utc).date()
        except (ValueError, AttributeError, TypeError):
            logger.debug("odds_service: bad date on fixture %s", fx_id)
            continue

        home_team = _resolve_team_for_odds(
            db, home_api.get("name", ""), home_api.get("id") or 0, league_obj.id
        )
        away_team = _resolve_team_for_odds(
            db, away_api.get("name", ""), away_api.get("id") or 0, league_obj.id
        )
        if not home_team or not away_team:
            continue

        match = (
            db.query(Match)
            .filter(
                Match.home_team_id == home_team.id,
                Match.away_team_id == away_team.id,
                Match.match_date == fx_date,
                Match.league_id == league_obj.id,
            )
            .first()
        )
        if not match:
            # Allow ±1 day tolerance for UTC-vs-local boundary mismatches
            match = (
                db.query(Match)
                .filter(
                    Match.home_team_id == home_team.id,
                    Match.away_team_id == away_team.id,
                    Match.match_date.between(fx_date - timedelta(days=1), fx_date + timedelta(days=1)),
                    Match.league_id == league_obj.id,
                )
                .first()
            )
        if not match:
            continue

        # Opportunistically backfill api_football_id. The odds service already
        # holds the confirmed fixture ID at this point — stamping it here means
        # domestic-league rows (EPL, La Liga, etc.) will accumulate their IDs
        # over normal odds-refresh runs without a dedicated backfill pass.
        if match.api_football_id is None:
            match.api_football_id = fx_id

        oh, od, oa = hda
        n = _apply_odds_to_predictions(db, match, oh, od, oa)
        if n:
            matches_updated += 1
            predictions_updated += n

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("refresh_odds_for_league %s: commit failed: %s", league_code, exc)
        raise

    return {
        "league": league_code,
        "fixtures_upcoming": len(fixture_map),
        "fixtures_with_odds": len(odds_by_fixture),
        "predictions_updated": predictions_updated,
        "matches_updated": matches_updated,
    }


def refresh_all_leagues_odds(db: Session) -> dict:
    """Refresh odds for every league in LEAGUE_API_FOOTBALL_IDS."""
    per_league = []
    total_preds = 0
    total_matches = 0
    for league_code in LEAGUE_API_FOOTBALL_IDS:
        try:
            stats = refresh_odds_for_league(db, league_code)
            per_league.append(stats)
            total_preds += stats.get("predictions_updated", 0)
            total_matches += stats.get("matches_updated", 0)
        except Exception as exc:
            logger.error("refresh_all_leagues_odds: %s failed: %s", league_code, exc)
            per_league.append({"league": league_code, "error": str(exc)})
        time.sleep(0.5)  # light inter-league pacing

    return {
        "leagues": per_league,
        "total_predictions_updated": total_preds,
        "total_matches_updated": total_matches,
    }
