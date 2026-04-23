"""
backend/services/live_score_service.py
========================================
Live score polling service using Football-Data.org free API.

Free tier: 10 requests/minute, covers:
  - Premier League (PL), Championship (ELC)
  - La Liga (PD), Serie A (SA), Bundesliga (BL1), Ligue 1 (FL1)
  - Champions League (CL), World Cup (WC)

Note: League One, League Two, and National League are NOT on the free tier.
Those require a paid plan. The service gracefully skips unavailable leagues.

Architecture:
  - A background thread polls Football-Data.org every 60 seconds
  - Results are cached in-memory (dict keyed by match ID)
  - The API endpoint reads from cache — no delay, no extra API calls
  - Only polls when explicitly started (during match windows)

Usage:
  from services.live_score_service import live_scores

  live_scores.start()       # Begin polling
  live_scores.stop()        # Stop polling
  live_scores.get_live()    # Get current live match data from cache
  live_scores.get_match(id) # Get specific match
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from threading import Thread, Event
from typing import Optional

import requests

from services.api_key_rotator import get_api_football_key, mark_key_exhausted

logger = logging.getLogger(__name__)

# Module-level Session for connection pooling. Shared across ESPN, FD.org,
# and API-Football pollers so TCP connections are reused across the 10s/20s
# cycles instead of churning fresh sockets every poll.
_session = requests.Session()

# Football-Data.org API
API_BASE = "https://api.football-data.org/v4"

# ESPN undocumented API — no key needed, covers all English leagues
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_LEAGUES = {
    "eng.1": "epl",
    "eng.2": "championship",
    "eng.3": "league_one",
    "eng.4": "league_two",
    "eng.5": "national_league",
    "usa.1": "mls",
    "esp.1": "laliga",
    "ita.1": "seriea",
    "ger.1": "bundesliga",
    "fra.1": "ligue1",
}

# Map our DB league codes to Football-Data.org competition codes
LEAGUE_TO_COMPETITION = {
    "epl": "PL",
    "championship": "ELC",
    "laliga": "PD",
    "seriea": "SA",
    "bundesliga": "BL1",
    "ligue1": "FL1",
}


class LiveScoreService:
    """In-memory live score cache with background polling from two APIs."""

    def __init__(self):
        self._cache: dict = {}           # match_id -> match data
        self._last_poll: Optional[datetime] = None
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._api_key: Optional[str] = None         # Football-Data.org
        self._use_api_football_rotator: bool = False  # True when key rotator is initialized
        self._poll_interval: int = 10
        self._poll_count: int = 0
        self._api_football_poll_count: int = 0  # Track daily usage across all rotated keys
        self._api_football_last_reset: Optional[datetime] = None

    def configure(self, api_key: str, poll_interval: int = 10,
                  use_api_football_rotator: bool = False):
        """Set Football-Data.org API key, poll interval, and API-Football rotator flag.

        api_key: Football-Data.org key (or empty string to skip that source).
        use_api_football_rotator: pass True after calling init_rotator() in main.py.
        """
        self._api_key = api_key
        self._use_api_football_rotator = use_api_football_rotator
        self._poll_interval = max(6, poll_interval)  # Minimum 6s (10 req/min limit)

    def start(self):
        """Start the background polling thread."""
        if not self._api_key:
            logger.warning("Live scores: no API key configured — not starting")
            return

        if self._thread and self._thread.is_alive():
            logger.info("Live scores: already running")
            return

        self._stop_event.clear()
        self._thread = Thread(target=self._poll_loop, daemon=True, name="live-scores")
        self._thread.start()
        logger.info("Live score polling started (interval=%ds)", self._poll_interval)

    def stop(self):
        """Stop the background polling thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Live score polling stopped")

    def get_live(self) -> dict:
        """
        Get all currently live/in-play matches from cache.

        Returns:
            {
                "matches": [...],
                "last_updated": "ISO timestamp",
                "polling_active": bool,
            }
        """
        # Snapshot the cache to avoid RuntimeError from concurrent dict modification
        snapshot = list(self._cache.values())

        live_matches = [
            m for m in snapshot
            if m.get("status") in ("IN_PLAY", "PAUSED", "HALFTIME")
        ]

        finished_recent = [
            m for m in snapshot
            if m.get("status") == "FINISHED"
            and m.get("_finished_at")
            and (datetime.now(timezone.utc) - m["_finished_at"]).total_seconds() < 1800
        ]

        return {
            "matches": live_matches + finished_recent,
            "last_updated": self._last_poll.isoformat() if self._last_poll else None,
            "polling_active": self._thread is not None and self._thread.is_alive(),
        }

    def get_today(self) -> dict:
        """Get all of today's matches (scheduled, live, and finished)."""
        return {
            "matches": list(self._cache.values()),  # list() creates a snapshot
            "last_updated": self._last_poll.isoformat() if self._last_poll else None,
            "polling_active": self._thread is not None and self._thread.is_alive(),
        }

    def get_match(self, match_id: int) -> Optional[dict]:
        """Get a specific match by Football-Data.org match ID."""
        return self._cache.get(match_id)

    def _poll_loop(self):
        """Background loop: poll both APIs on alternating intervals."""
        logger.info("Live score poll loop started (interval=%ds, fd_key=%s, apif_rotator=%s)",
                     self._poll_interval,
                     "configured" if self._api_key else "missing",
                     "enabled" if self._use_api_football_rotator else "disabled")

        self._do_poll()
        self._do_poll_espn()  # Immediate ESPN poll on start
        self._poll_count = 0

        while not self._stop_event.wait(timeout=self._poll_interval):
            self._do_poll()

            self._poll_count += 1

            # ESPN: poll every 20 seconds (every 2nd cycle) — no quota, free
            if self._poll_count % 2 == 0:
                self._do_poll_espn()

            # API-Football: poll every 5 minutes only during match windows (save 100/day quota)
            if self._use_api_football_rotator and self._poll_count % 30 == 0:
                now_utc = datetime.now(timezone.utc)
                hour_utc = now_utc.hour
                if 11 <= hour_utc <= 23:
                    has_games_today = any(
                        m.get("status") in ("TIMED", "IN_PLAY", "HALFTIME", "NS")
                        for m in self._cache.values()
                    )
                    if has_games_today or len(self._cache) == 0:
                        self._do_poll_api_football()
                    else:
                        logger.debug("API-Football: no games in cache, skipping poll")

            # Sync live scores to DB every 30 seconds (every 3rd poll)
            if self._poll_count % 3 == 0:
                self._sync_to_db()

        logger.info("Live score poll loop exited")

    def _do_poll(self):
        """Single poll: fetch today's matches from Football-Data.org."""
        headers = {"X-Auth-Token": self._api_key}

        try:
            # GET /v4/matches — returns today's matches across all competitions
            resp = _session.get(
                f"{API_BASE}/matches",
                headers=headers,
                timeout=15,
            )

            if resp.status_code == 429:
                logger.warning("Live scores: rate limited — backing off")
                return

            if resp.status_code == 403:
                logger.error("Live scores: invalid API key")
                return

            resp.raise_for_status()
            data = resp.json()

            matches = data.get("matches", [])
            now = datetime.now(timezone.utc)

            for match in matches:
                match_id = match.get("id")
                if not match_id:
                    continue

                # Normalize into our format
                home = match.get("homeTeam", {})
                away = match.get("awayTeam", {})
                score = match.get("score", {})
                full_time = score.get("fullTime", {})
                half_time = score.get("halfTime", {})
                competition = match.get("competition", {})

                normalized = {
                    "id": match_id,
                    "status": match.get("status"),
                    "minute": match.get("minute"),
                    "home_team": home.get("name"),
                    "home_team_short": home.get("shortName"),
                    "home_team_crest": home.get("crest"),
                    "away_team": away.get("name"),
                    "away_team_short": away.get("shortName"),
                    "away_team_crest": away.get("crest"),
                    "home_score": full_time.get("home"),
                    "away_score": full_time.get("away"),
                    "ht_home_score": half_time.get("home"),
                    "ht_away_score": half_time.get("away"),
                    "competition": competition.get("name"),
                    "competition_code": competition.get("code"),
                    "competition_emblem": competition.get("emblem"),
                    "match_date": match.get("utcDate"),
                    "matchday": match.get("matchday"),
                    "last_updated": now.isoformat(),
                }

                # Track when a match finishes so we can keep it in cache briefly
                old = self._cache.get(match_id, {})
                if (
                    normalized["status"] == "FINISHED"
                    and old.get("status") != "FINISHED"
                ):
                    normalized["_finished_at"] = now
                elif old.get("_finished_at"):
                    normalized["_finished_at"] = old["_finished_at"]

                self._cache[match_id] = normalized

            self._last_poll = now

            # Prune stale finished matches (older than 3 hours) to prevent unbounded growth
            stale_ids = [
                mid for mid, m in self._cache.items()
                if (
                    # Finished matches older than 3 hours
                    (m.get("status") == "FINISHED"
                     and m.get("_finished_at")
                     and (now - m["_finished_at"]).total_seconds() > 10800)
                    or
                    # Non-live matches that haven't been updated in 24 hours
                    # (e.g., yesterday's TIMED matches that never started)
                    (m.get("status") not in ("IN_PLAY", "PAUSED", "HALFTIME", "FINISHED")
                     and m.get("last_updated")
                     and (now - datetime.fromisoformat(m["last_updated"])).total_seconds() > 86400)
                )
            ]
            for mid in stale_ids:
                del self._cache[mid]

            live_count = sum(
                1 for m in self._cache.values()
                if m.get("status") in ("IN_PLAY", "PAUSED", "HALFTIME")
            )
            logger.debug(
                "Live scores polled: %d matches total, %d live",
                len(matches), live_count,
            )

        except requests.RequestException as e:
            logger.error("Live score poll failed: %s", e)
        except Exception as e:
            logger.error("Live score poll error: %s", e)

    def _do_poll_espn(self):
        """Poll ESPN undocumented API for all our leagues. No key needed, no quota."""
        now = datetime.now(timezone.utc)

        for espn_slug, db_league_code in ESPN_LEAGUES.items():
            try:
                resp = _session.get(
                    f"{ESPN_BASE}/{espn_slug}/scoreboard",
                    timeout=10,
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                events = data.get("events", [])

                for event in events:
                    comp = event.get("competitions", [{}])[0]
                    competitors = comp.get("competitors", [])
                    status_obj = comp.get("status", {})
                    status_type = status_obj.get("type", {}).get("name", "")
                    clock = status_obj.get("displayClock", "")

                    home = next((t for t in competitors if t.get("homeAway") == "home"), {})
                    away = next((t for t in competitors if t.get("homeAway") == "away"), {})

                    if not home or not away:
                        continue

                    # Map ESPN status to our format
                    status_map = {
                        "STATUS_FULL_TIME": "FINISHED",
                        "STATUS_IN_PROGRESS": "IN_PLAY",
                        "STATUS_FIRST_HALF": "IN_PLAY",
                        "STATUS_SECOND_HALF": "IN_PLAY",
                        "STATUS_HALFTIME": "HALFTIME",
                        "STATUS_SCHEDULED": "TIMED",
                        "STATUS_POSTPONED": "POSTPONED",
                        "STATUS_CANCELED": "CANCELLED",
                        "STATUS_FINAL_AET": "FINISHED",
                        "STATUS_FINAL_PEN": "FINISHED",
                        "STATUS_END_OF_REGULATION": "FINISHED",
                    }
                    status = status_map.get(status_type, status_type)

                    home_team = home.get("team", {})
                    away_team = away.get("team", {})
                    cache_key = f"espn_{event.get('id', '')}"

                    home_score = home.get("score")
                    away_score = away.get("score")
                    # ESPN returns score as string
                    try:
                        home_score = int(home_score) if home_score is not None else None
                    except (ValueError, TypeError):
                        home_score = None
                    try:
                        away_score = int(away_score) if away_score is not None else None
                    except (ValueError, TypeError):
                        away_score = None

                    normalized = {
                        "id": cache_key,
                        "status": status,
                        "minute": clock if status in ("IN_PLAY", "HALFTIME") else None,
                        "home_team": home_team.get("displayName"),
                        "home_team_short": home_team.get("shortDisplayName"),
                        "home_team_crest": home_team.get("logo"),
                        "away_team": away_team.get("displayName"),
                        "away_team_short": away_team.get("shortDisplayName"),
                        "away_team_crest": away_team.get("logo"),
                        "home_score": home_score,
                        "away_score": away_score,
                        "ht_home_score": None,
                        "ht_away_score": None,
                        "competition": espn_slug.replace(".", " ").title(),
                        "competition_code": db_league_code,
                        "competition_emblem": None,
                        "match_date": event.get("date"),
                        "matchday": None,
                        "last_updated": now.isoformat(),
                        "source": "espn",
                    }

                    # Track finish time
                    old = self._cache.get(cache_key, {})
                    if status == "FINISHED" and old.get("status") != "FINISHED":
                        normalized["_finished_at"] = now
                    elif old.get("_finished_at"):
                        normalized["_finished_at"] = old["_finished_at"]

                    self._cache[cache_key] = normalized

            except Exception as e:
                logger.debug("ESPN poll failed for %s: %s", espn_slug, e)

        live_count = sum(
            1 for m in self._cache.values()
            if m.get("status") in ("IN_PLAY", "PAUSED", "HALFTIME")
        )
        logger.debug("ESPN polled: %d total cached, %d live", len(self._cache), live_count)

    def _do_poll_api_football(self):
        """Poll API-Football (api-sports.io) for lower leagues + MLS.

        Retrieves a key from the global rotator on each call. If the key returns
        a 429, marks it exhausted and retries once with the next key.
        """
        if not self._use_api_football_rotator:
            return

        # Reset daily counter at midnight (across all rotated keys combined)
        now = datetime.now(timezone.utc)
        if self._api_football_last_reset is None or now.date() != self._api_football_last_reset.date():
            self._api_football_poll_count = 0
            self._api_football_last_reset = now
            logger.info("API-Football: daily quota counter reset")

        # Track daily usage across all keys — 600 req/day combined budget
        self._api_football_poll_count += 1
        if self._api_football_poll_count > 540:  # 90% of 600
            logger.warning("API-Football: approaching combined daily limit (%d/600), skipping",
                           self._api_football_poll_count)
            return

        try:
            key = get_api_football_key()
        except RuntimeError as e:
            logger.error("API-Football: rotator error — %s", e)
            return

        headers = {"x-apisports-key": key}

        try:
            # Get all live fixtures in one call
            resp = _session.get(
                "https://v3.football.api-sports.io/fixtures",
                headers=headers,
                params={"live": "all"},
                timeout=15,
            )

            if resp.status_code == 429:
                logger.warning("API-Football: key ...%s rate limited — marking exhausted and retrying", key[-8:])
                mark_key_exhausted(key)
                # Retry once with next key
                try:
                    key = get_api_football_key()
                except RuntimeError:
                    return
                headers = {"x-apisports-key": key}
                resp = _session.get(
                    "https://v3.football.api-sports.io/fixtures",
                    headers=headers,
                    params={"live": "all"},
                    timeout=15,
                )
                if resp.status_code == 429:
                    logger.warning("API-Football: retry key also rate limited — skipping poll")
                    mark_key_exhausted(key)
                    return

            if resp.status_code != 200:
                logger.warning("API-Football: status %d", resp.status_code)
                return

            data = resp.json()
            fixtures = data.get("response", [])
            now = datetime.now(timezone.utc)

            for fix in fixtures:
                fixture_info = fix.get("fixture", {})
                league_info = fix.get("league", {})
                teams_info = fix.get("teams", {})
                goals_info = fix.get("goals", {})
                score_info = fix.get("score", {})

                fix_id = fixture_info.get("id")
                if not fix_id:
                    continue

                # Use a prefixed ID to avoid collision with Football-Data.org IDs
                cache_key = f"apif_{fix_id}"

                status_short = fixture_info.get("status", {}).get("short", "")
                elapsed = fixture_info.get("status", {}).get("elapsed")

                # Map API-Football status to our format
                status_map = {
                    "1H": "IN_PLAY", "2H": "IN_PLAY", "ET": "IN_PLAY",
                    "HT": "HALFTIME", "BT": "HALFTIME",
                    "FT": "FINISHED", "AET": "FINISHED", "PEN": "FINISHED",
                    "NS": "TIMED", "TBD": "TIMED",
                    "PST": "POSTPONED", "CANC": "CANCELLED",
                    "SUSP": "SUSPENDED", "INT": "SUSPENDED",
                    "P": "IN_PLAY", "LIVE": "IN_PLAY",
                }
                status = status_map.get(status_short, status_short)

                normalized = {
                    "id": cache_key,
                    "status": status,
                    "minute": elapsed,
                    "home_team": teams_info.get("home", {}).get("name"),
                    "home_team_short": teams_info.get("home", {}).get("name", "")[:20],
                    "home_team_crest": teams_info.get("home", {}).get("logo"),
                    "away_team": teams_info.get("away", {}).get("name"),
                    "away_team_short": teams_info.get("away", {}).get("name", "")[:20],
                    "away_team_crest": teams_info.get("away", {}).get("logo"),
                    "home_score": goals_info.get("home"),
                    "away_score": goals_info.get("away"),
                    "ht_home_score": score_info.get("halftime", {}).get("home"),
                    "ht_away_score": score_info.get("halftime", {}).get("away"),
                    "competition": league_info.get("name"),
                    "competition_code": league_info.get("country", ""),
                    "competition_emblem": league_info.get("logo"),
                    "match_date": fixture_info.get("date"),
                    "matchday": league_info.get("round"),
                    "last_updated": now.isoformat(),
                    "source": "api-football",
                }

                # Track finish time
                old = self._cache.get(cache_key, {})
                if status == "FINISHED" and old.get("status") != "FINISHED":
                    normalized["_finished_at"] = now
                elif old.get("_finished_at"):
                    normalized["_finished_at"] = old["_finished_at"]

                self._cache[cache_key] = normalized

            live_count = sum(
                1 for m in self._cache.values()
                if m.get("status") in ("IN_PLAY", "PAUSED", "HALFTIME")
            )
            logger.debug(
                "API-Football polled: %d fixtures, %d total cached, %d live",
                len(fixtures), len(self._cache), live_count,
            )

        except Exception as e:
            logger.error("API-Football poll error: %s", e)

    def _sync_to_db(self):
        """
        Sync live scores from cache into the database.
        Updates scheduled matches with live/finished scores so the dashboard
        reflects real-time data without a separate page.
        """
        try:
            from database import SessionLocal
            from models.match import Match
            from models.team import Team
            from models.prediction import Prediction
            from datetime import date as date_type

            # Snapshot cache to avoid RuntimeError from concurrent modification
            cache_snapshot = list(self._cache.values())
            live_or_finished = [
                m for m in cache_snapshot
                if m.get("status") in ("IN_PLAY", "HALFTIME", "FINISHED")
                and m.get("home_score") is not None
            ]

            if not live_or_finished:
                return

            db = SessionLocal()
            try:
                # Build flexible team name lookup
                all_teams = db.query(Team).all()
                team_by_name = {}
                for t in all_teams:
                    team_by_name[t.canonical_name] = t.id
                    team_by_name[t.canonical_name.lower()] = t.id
                    if t.short_name:
                        team_by_name[t.short_name] = t.id
                        team_by_name[t.short_name.lower()] = t.id
                    # Strip common suffixes
                    for suffix in [" FC", " AFC", " F.C.", " Town", " City", " United", " Rovers", " Wanderers", " Moors"]:
                        clean = t.canonical_name.replace(suffix, "").strip()
                        if clean and clean != t.canonical_name:
                            team_by_name[clean] = t.id
                            team_by_name[clean.lower()] = t.id

                # Common abbreviations in football-data.co.uk CSVs
                ABBREVS = {"Utd": "United", "Rvs": "Rovers", "Cty": "City"}
                # Also index expanded abbreviations
                for t in all_teams:
                    expanded = t.canonical_name
                    for abbr, full in ABBREVS.items():
                        expanded = expanded.replace(abbr, full)
                    if expanded != t.canonical_name:
                        team_by_name[expanded] = t.id
                        team_by_name[expanded.lower()] = t.id

                def _find_team(name):
                    if not name:
                        return None
                    # Direct match
                    if name in team_by_name:
                        return team_by_name[name]
                    # Case-insensitive
                    if name.lower() in team_by_name:
                        return team_by_name[name.lower()]
                    # Strip suffixes from the API name
                    for suffix in [" FC", " AFC", " F.C.", " Town", " City", " United", " Rovers", " Wanderers", " Moors"]:
                        clean = name.replace(suffix, "").strip()
                        if clean in team_by_name:
                            return team_by_name[clean]
                        if clean.lower() in team_by_name:
                            return team_by_name[clean.lower()]
                    # Expand abbreviations in API name
                    expanded = name
                    for abbr, full in ABBREVS.items():
                        expanded = expanded.replace(full, abbr)
                    if expanded != name and expanded in team_by_name:
                        return team_by_name[expanded]
                    # Try substring containment (e.g., "Salford" in "Salford City")
                    name_lower = name.lower()
                    for db_name, tid in team_by_name.items():
                        if isinstance(db_name, str) and len(db_name) > 3:
                            if db_name.lower() in name_lower or name_lower in db_name.lower():
                                return tid
                    return None

                today = date_type.today()
                updated = 0

                for live_match in live_or_finished:
                    home_name = live_match.get("home_team", "")
                    away_name = live_match.get("away_team", "")
                    home_score = live_match.get("home_score")
                    away_score = live_match.get("away_score")

                    if home_score is None or away_score is None:
                        continue

                    # Find team IDs (flexible matching)
                    home_id = _find_team(home_name)
                    away_id = _find_team(away_name)

                    if not home_id or not away_id:
                        continue

                    # Find the DB match (today's scheduled or live)
                    db_match = (
                        db.query(Match)
                        .filter(
                            Match.home_team_id == home_id,
                            Match.away_team_id == away_id,
                            Match.match_date == today,
                            Match.status.in_(["scheduled", "live"]),
                        )
                        .first()
                    )

                    if not db_match:
                        continue

                    # Determine result
                    if home_score > away_score:
                        result = "H"
                    elif home_score < away_score:
                        result = "A"
                    else:
                        result = "D"

                    # Update match
                    reported_finished = live_match.get("status") == "FINISHED"
                    was_completed = db_match.status == "completed"

                    # Time guard: don't trust a FINISHED status from any source
                    # unless at least 100 min have elapsed since kickoff (regulation
                    # 90 min + ~10 min stoppage). Sources (especially FD.org) are
                    # known to briefly/prematurely report FINISHED for still-live
                    # games — that was the root cause of "Wrong" badges appearing
                    # on games still in the 70th minute.
                    past_full_time = False
                    if db_match.kickoff_time and db_match.match_date:
                        try:
                            dh, dm = db_match.kickoff_time.split(":")
                            kickoff_dt = datetime.combine(
                                db_match.match_date,
                                datetime.min.time(),
                                tzinfo=timezone.utc,
                            ).replace(hour=int(dh), minute=int(dm))
                            past_full_time = (
                                datetime.now(timezone.utc) - kickoff_dt
                            ).total_seconds() >= 6000  # 100 min
                        except (ValueError, AttributeError):
                            past_full_time = False

                    is_finished = reported_finished and past_full_time

                    db_match.home_goals = int(home_score)
                    db_match.away_goals = int(away_score)
                    db_match.result = result

                    # Guard: once a match is completed, don't let a conflicting
                    # source (ESPN vs FD.org reporting different statuses for the
                    # same match) revert it to 'live'. Only demote on first
                    # transition or when we're certain the game is still in play.
                    if is_finished:
                        db_match.status = "completed"
                    elif not was_completed:
                        db_match.status = "live"

                    # Evaluate predictions only on the *transition* into completed.
                    # Combined with the time guard above, this ensures the "Correct"/
                    # "Wrong" badge only appears once the game has genuinely ended.
                    if is_finished and not was_completed:
                        preds = db.query(Prediction).filter(
                            Prediction.match_id == db_match.id
                        ).all()
                        for pred in preds:
                            pred.was_correct = (pred.predicted_result == result)

                    updated += 1

                # --- Kickoff schedule corrections for TIMED/SCHEDULED matches ---
                # ESPN/FD.org/API-Football may revise kickoff times (broadcast shifts,
                # weather, etc). Propagate the authoritative UTC timestamp into the DB
                # so match cards don't display stale times (e.g. West Ham vs Palace
                # showing 1pm when actual kickoff is 12pm).
                # Include TIMED/SCHEDULED (pre-match) AND live (game started earlier
                # than the stored kickoff suggests — stale seed detected mid-game).
                scheduled_cache = [
                    m for m in cache_snapshot
                    if m.get("status") in ("TIMED", "SCHEDULED", "IN_PLAY", "HALFTIME")
                    and m.get("match_date")
                ]
                now_utc = datetime.now(timezone.utc)
                for sched in scheduled_cache:
                    home_name = sched.get("home_team", "")
                    away_name = sched.get("away_team", "")
                    home_id = _find_team(home_name)
                    away_id = _find_team(away_name)
                    if not home_id or not away_id:
                        continue

                    raw = sched.get("match_date")
                    try:
                        cache_dt = datetime.fromisoformat(
                            str(raw).replace("Z", "+00:00")
                        )
                        if cache_dt.tzinfo is None:
                            cache_dt = cache_dt.replace(tzinfo=timezone.utc)
                        cache_dt = cache_dt.astimezone(timezone.utc)
                    except (ValueError, AttributeError):
                        continue

                    cache_date = cache_dt.date()
                    cache_kickoff = cache_dt.strftime("%H:%M")

                    # Only touch near-term matches (avoids churn on far-future
                    # fixtures where times routinely change)
                    if cache_date < today - timedelta(days=1) or cache_date > today + timedelta(days=14):
                        continue

                    cache_is_live = sched.get("status") in ("IN_PLAY", "HALFTIME")

                    # For scheduled matches find by scheduled status; for live
                    # matches we also accept 'live' DB rows (stale seed correction)
                    status_filter = ["scheduled"]
                    if cache_is_live:
                        status_filter.append("live")

                    db_match = (
                        db.query(Match)
                        .filter(
                            Match.home_team_id == home_id,
                            Match.away_team_id == away_id,
                            Match.status.in_(status_filter),
                        )
                        .order_by(Match.match_date.asc())
                        .first()
                    )
                    if not db_match:
                        continue

                    # Parse stored kickoff for guard checks
                    existing_dt = None
                    if db_match.kickoff_time and db_match.match_date:
                        try:
                            dh, dm = db_match.kickoff_time.split(":")
                            existing_dt = datetime.combine(
                                db_match.match_date,
                                datetime.min.time(),
                                tzinfo=timezone.utc,
                            ).replace(hour=int(dh), minute=int(dm))
                        except (ValueError, AttributeError):
                            pass

                    if cache_is_live:
                        # Stale-seed correction for live matches: only overwrite
                        # if stored kickoff differs from cache by >10 min AND the
                        # cache-reported kickoff is at least 5 min in the past
                        # (match has actually started per the source).
                        drift_ok = existing_dt is None or abs(
                            (existing_dt - cache_dt).total_seconds()
                        ) > 600
                        started_ok = (now_utc - cache_dt).total_seconds() > 300
                        if not (drift_ok and started_ok):
                            continue
                    else:
                        # Pre-match: don't overwrite within 30 min of existing
                        # kickoff (prevents flicker as the game is about to start).
                        if existing_dt is not None and abs(
                            (existing_dt - now_utc).total_seconds()
                        ) < 1800:
                            continue

                    changed = False
                    if db_match.match_date != cache_date:
                        db_match.match_date = cache_date
                        changed = True
                    if db_match.kickoff_time != cache_kickoff:
                        db_match.kickoff_time = cache_kickoff
                        changed = True
                    if changed:
                        updated += 1
                        logger.info(
                            "Kickoff updated: match_id=%d %s vs %s -> %s %sZ (src=%s, was_live=%s)",
                            db_match.id, home_name, away_name,
                            cache_date, cache_kickoff,
                            sched.get("source", "fdorg"),
                            cache_is_live,
                        )

                # Also finalize any DB matches stuck as "live" that are no longer in cache
                # (game ended, cache pruned, but DB never got the FINISHED status)
                stale_live = (
                    db.query(Match)
                    .filter(
                        Match.status == "live",
                        Match.match_date <= today,
                        Match.home_goals != None,
                    )
                    .all()
                )
                teams_by_id = {t.id: t for t in all_teams}
                for stale in stale_live:
                    # Check if this match is still actively live in cache by team name (not score)
                    stale_home = teams_by_id.get(stale.home_team_id)
                    stale_away = teams_by_id.get(stale.away_team_id)
                    stale_h_name = (stale_home.canonical_name if stale_home else "").lower()
                    stale_a_name = (stale_away.canonical_name if stale_away else "").lower()

                    still_live = False
                    for m in cache_snapshot:
                        if m.get("status") not in ("IN_PLAY", "HALFTIME"):
                            continue
                        cache_h = (m.get("home_team") or "").lower().replace(" fc", "").replace(" afc", "").strip()
                        cache_a = (m.get("away_team") or "").lower().replace(" fc", "").replace(" afc", "").strip()
                        if ((stale_h_name in cache_h or cache_h in stale_h_name) and
                            (stale_a_name in cache_a or cache_a in stale_a_name)):
                            still_live = True
                            break
                    if not still_live:
                        # Game is over — finalize it
                        if stale.home_goals > stale.away_goals:
                            result = "H"
                        elif stale.home_goals < stale.away_goals:
                            result = "A"
                        else:
                            result = "D"
                        stale.result = result
                        stale.status = "completed"
                        # Evaluate predictions
                        preds = db.query(Prediction).filter(
                            Prediction.match_id == stale.id
                        ).all()
                        for pred in preds:
                            pred.was_correct = (pred.predicted_result == result)
                        updated += 1
                        logger.info("Finalized stale live match: id=%d (%d-%d)",
                                    stale.id, stale.home_goals, stale.away_goals)

                if updated:
                    try:
                        db.commit()
                        logger.info("Synced %d live/finished matches to DB", updated)
                    except Exception as commit_err:
                        db.rollback()
                        logger.error("DB sync commit failed: %s", commit_err)

            finally:
                db.close()

        except Exception as e:
            logger.error("DB sync error: %s", e)


# Module-level singleton
live_scores = LiveScoreService()
