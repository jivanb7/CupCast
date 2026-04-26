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
from sqlalchemy.exc import IntegrityError
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
#
# UCL is intentionally OFF this list. On 2026-04-25 ESPN's `uefa.champions`
# slug returned six bogus "semifinal" fixtures pairing real UCL semifinalists
# (PSG, Bayern, Arsenal) against teams that don't belong in this round
# (DC United from MLS, plus preliminary-round clubs Drita and Inter Club
# d'Escaldes). Whatever combination of upstream API drift, slug overload, or
# our cross-league fuzzy team-resolution caused the mismatch — FDORG's `CL`
# competition already covers UCL correctly, so ESPN was pure noise here.
# If we ever need ESPN as a UCL backup we can re-enable with strict stage
# filtering (only `qf`/`sf`/`final`) and a UEFA-country sanity check on the
# resolved teams.
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
    "usa.1": "mls",
    "fifa.world": "worldcup",
}

# How far ahead to ask ESPN for fixtures. Most leagues only publish a few
# weeks out, so 30 days is plenty; larger windows slow the call without return.
LOOKAHEAD_DAYS = 30

# Per-slug overrides for leagues that publish long windows. The 2026 World Cup
# has all 100 group-stage + knockout fixtures on ESPN already (from ~7 weeks
# before kickoff), and a 30-day default window misses the entire tournament
# until mid-May. Longer windows are only cheap on ESPN — no rate limit — so we
# can safely ask for the full tournament.
LOOKAHEAD_OVERRIDES = {
    "fifa.world": 120,
}

# Map ESPN season.slug (scoreboard) → our stage enum. season.slug is the most
# reliable stage signal in the scoreboard payload: it's populated on every
# event we've seen (group-stage, round-of-32, round-of-16, quarterfinals, etc.)
# and does not require a second API call.
_ESPN_SLUG_TO_STAGE = {
    "group-stage": "group",
    "round-of-32": "r32",
    "round-of-16": "r16",
    "quarterfinals": "qf",
    "quarter-finals": "qf",
    "semifinals": "sf",
    "semi-finals": "sf",
    "third-place": "3rd-place",
    "3rd-place-match": "3rd-place",
    "final": "final",
}

# The scoreboard payload does NOT carry the group letter for individual events.
# To get "Group A" we must hit /summary?event=<id>, which exposes
# header.competitions[0].competitors[*].groups.abbreviation. We only do this
# for group-stage matches we're about to insert — knockout events have no group
# and existing rows are skipped, so steady-state cost is ~zero.
_ESPN_SUMMARY_URL = f"{ESPN_BASE}/{{slug}}/summary"


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


def _extract_stage(event: dict) -> Optional[str]:
    """Map an ESPN scoreboard event to our stage enum.

    Primary signal: `season.slug` (e.g. "group-stage", "round-of-32"). We also
    fall back to parsing the event name for the knockout slug patterns ESPN
    occasionally varies (e.g. a "Final" event whose slug still reads "finals").

    Returns None for unrecognized formats; caller logs a warning so we catch
    novel stage names as ESPN adds them.
    """
    slug = ((event.get("season") or {}).get("slug") or "").strip().lower()
    if slug in _ESPN_SLUG_TO_STAGE:
        return _ESPN_SLUG_TO_STAGE[slug]

    # Fallback: scan event.name. Order matters — "Semifinal" contains "Final".
    name = (event.get("name") or "").lower()
    if "3rd place" in name or "third place" in name:
        return "3rd-place"
    if "semifinal" in name or "semi-final" in name:
        return "sf"
    if "quarterfinal" in name or "quarter-final" in name:
        return "qf"
    if "round of 16" in name:
        return "r16"
    if "round of 32" in name:
        return "r32"
    if "group" in name:  # e.g. "Group A 2nd Place at Group B Winner" shouldn't hit here; group-stage events use season.slug
        return None
    if "final" in name:
        return "final"

    if slug:
        logger.warning("ESPN: unrecognized season.slug=%r on event %r", slug, event.get("name"))
    return None


def _fetch_event_summary(slug: str, event_id: str) -> Optional[dict]:
    """Fetch the per-event summary payload. Returns None on error."""
    url = _ESPN_SUMMARY_URL.format(slug=slug)
    try:
        resp = _session.get(url, params={"event": event_id}, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug("ESPN summary fetch failed for event %s: %s", event_id, e)
        return None


def _extract_group_label(summary_payload: dict) -> Optional[str]:
    """Pull the group letter from an event's summary payload.

    ESPN exposes it at header.competitions[0].competitors[*].groups.abbreviation
    as "Group A", "Group B", ... We take the first non-empty competitor value
    (both competitors always carry the same group for group-stage matches) and
    strip the "Group " prefix. Returns None for knockout events (no groups).
    """
    try:
        comps = summary_payload["header"]["competitions"][0]["competitors"]
    except (KeyError, IndexError, TypeError):
        return None
    for c in comps:
        abbr = ((c.get("groups") or {}).get("abbreviation") or "").strip()
        if abbr.lower().startswith("group "):
            label = abbr.split(" ", 1)[1].strip().upper()
            # DB column is CHAR(2). Only accept 1–2 char labels.
            if 1 <= len(label) <= 2 and label.isalpha():
                return label
    return None


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

    for slug, db_league_code in ESPN_LEAGUES.items():
        league = db.query(League).filter(League.code == db_league_code).first()
        if not league:
            continue

        lookahead = LOOKAHEAD_OVERRIDES.get(slug, LOOKAHEAD_DAYS)
        end = start + timedelta(days=lookahead)
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
                # Backfill stage/group for rows that pre-date this change.
                if existing.stage is None:
                    existing.stage = _extract_stage(ev)
                if existing.stage == "group" and existing.group_label is None:
                    summary = _fetch_event_summary(slug, str(ev.get("id") or ""))
                    if summary:
                        existing.group_label = _extract_group_label(summary)
                stats["already_exists"] += 1
                continue

            stage = _extract_stage(ev)
            group_label = None
            if stage == "group":
                summary = _fetch_event_summary(slug, str(ev.get("id") or ""))
                if summary:
                    group_label = _extract_group_label(summary)

            # Race-safe insert. ESPN runs after FDORG + CSV in seed_all_fixtures,
            # so most of these collide with the uq_match_fixture UC and turn into
            # silent already_exists counts; keep the savepoint regardless to
            # tolerate any future re-ordering or concurrent trigger.
            new_match = Match(
                home_team_id=home_id,
                away_team_id=away_id,
                league_id=league.id,
                match_date=match_date,
                kickoff_time=kickoff_time,
                status="scheduled",
                season=_current_season_str(),
                stage=stage,
                group_label=group_label,
            )
            try:
                with db.begin_nested():
                    db.add(new_match)
                    db.flush()
                stats["seeded"] += 1
            except IntegrityError:
                stats["already_exists"] += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to commit ESPN fixtures: %s", e)
        stats["error"] = str(e)

    logger.info("ESPN fixture seeder done: %s", stats)
    return stats
