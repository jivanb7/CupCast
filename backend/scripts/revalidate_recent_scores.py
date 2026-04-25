"""
backend/scripts/revalidate_recent_scores.py
============================================
Cross-check recent completed match scores against API-Football and fix
discrepancies (and re-evaluate predictions) where our DB locked in an
intermediate score.

Why this exists
  score_updater previously had ``if match.status == 'completed': continue``
  which permanently froze whatever score happened to be written first.
  Real Betis vs Real Madrid (La Liga, 2026-04-24) is the canonical example:
  Madrid scored first, our updater wrote 0-1 / status='completed', and the
  late Betis equaliser (final 1-1) was never seen.

What it does
  For every match with status='completed' AND match_date in [today - N days, today]:
    1. Map our league_id → API-Football league_id (skip leagues with no mapping).
    2. GET /fixtures?league=X&season=Y&date=YYYY-MM-DD on API-Football.
    3. Match the fixture by team names (canonical/alias/short-name fuzz, scoped
       to the league — same resolver odds_service uses).
    4. Compare API-Football's full-time goals to ours.
    5. If different:
         severity = 'MISMATCH' when API-Football status code is FT/AET/PEN
         severity = 'STALE'    when API-Football still says LIVE/HT/etc.
       UPDATE matches SET home_goals, away_goals, result, updated_at=CURRENT_TIMESTAMP.
       UPDATE predictions SET was_correct = (predicted_result == new_result).

Usage (CLI)
  conda run -n ml python -m scripts.revalidate_recent_scores --days 3
  conda run -n ml python -m scripts.revalidate_recent_scores --days 3 --dry-run

Programmatic (admin endpoint)
  from scripts.revalidate_recent_scores import revalidate
  result = revalidate(db, days=2, dry_run=False)
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import requests
from sqlalchemy.orm import Session

# Allow `python scripts/...` invocation as well as `python -m scripts.revalidate_recent_scores`
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

logger = logging.getLogger(__name__)

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
DEFAULT_DAYS = 3

# API-Football status codes that mean "this is the actual final score":
#   FT  = Full Time
#   AET = After Extra Time
#   PEN = Penalty Shootout finished
#   AWD = Technical loss / awarded
#   WO  = Walkover
_FINAL_STATUS_CODES = {"FT", "AET", "PEN", "AWD", "WO"}

# Anomaly thresholds for structured logging at the end of each run.
# Tuned against the ~6 % silent-error baseline observed before this hardening:
# 5 mismatches over a 2-day window is noisy-but-normal upstream churn; 15 is a
# strong signal that either the upstream feed regressed or our updater wrote
# a bad value en-masse.
_WARN_MISMATCH_THRESHOLD = 5
_ERROR_MISMATCH_THRESHOLD = 15

_session = requests.Session()


def _generate_run_id() -> str:
    """Short, sortable, unique-enough id for grouping a single revalidation pass.

    Format: ``YYYYMMDDTHHMMSSZ-XXXXXX`` (UTC ISO basic + 6 hex).
    Fits in the 40-char run_id column with room to spare.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{secrets.token_hex(3)}"


def _current_season() -> str:
    """API-Football season key (start year). Same logic as odds_service."""
    now = datetime.now(timezone.utc)
    year = now.year if now.month >= 7 else now.year - 1
    return str(year)


def _api_football_get(endpoint: str, params: dict) -> Optional[dict]:
    """Single GET against API-Football with rotating-key + 429 retry.

    Pulled apart from odds_service so this script can run standalone (CLI)
    without importing the whole odds module.
    """
    from services.api_key_rotator import get_api_football_key, mark_key_exhausted

    for attempt in range(2):
        key = get_api_football_key()
        url = f"{API_FOOTBALL_BASE}/{endpoint}"
        try:
            resp = _session.get(
                url, headers={"x-apisports-key": key}, params=params, timeout=15
            )
        except requests.RequestException as exc:
            logger.error("revalidate: %s request failed params=%s: %s", endpoint, params, exc)
            return None

        if resp.status_code == 429:
            logger.warning(
                "revalidate: 429 on %s (key ...%s) attempt %d/2",
                endpoint, key[-6:], attempt + 1,
            )
            mark_key_exhausted(key)
            if attempt == 0:
                continue
            return None

        if resp.status_code != 200:
            logger.error(
                "revalidate: HTTP %d on %s params=%s body=%s",
                resp.status_code, endpoint, params, resp.text[:200],
            )
            return None

        try:
            return resp.json()
        except Exception as exc:
            logger.error("revalidate: JSON decode error on %s: %s", endpoint, exc)
            return None

    return None


def _fetch_fixtures_for_date(api_league_id: int, season: str, match_date: date) -> list[dict]:
    """Return the raw list of fixtures API-Football reports for (league, season, date)."""
    resp = _api_football_get(
        "fixtures",
        {
            "league": api_league_id,
            "season": season,
            "date": match_date.isoformat(),
        },
    )
    if resp is None:
        return []
    return resp.get("response", []) or []


def _result_letter(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


def _match_fixture_to_db_match(db: Session, fx: dict, league_id: int):
    """Resolve an API-Football fixture row to our DB Match in the same league.

    Reuses the odds_service resolver because it already handles the canonical/
    alias/short_name/substring fuzz for API-Football team names.
    """
    from models.match import Match
    from services.odds_service import _resolve_team_for_odds

    teams = fx.get("teams", {}) or {}
    home_api = teams.get("home", {}) or {}
    away_api = teams.get("away", {}) or {}

    home_team = _resolve_team_for_odds(
        db, home_api.get("name", ""), home_api.get("id") or 0, league_id
    )
    away_team = _resolve_team_for_odds(
        db, away_api.get("name", ""), away_api.get("id") or 0, league_id
    )
    if not home_team or not away_team:
        return None

    fx_date_str = (fx.get("fixture", {}) or {}).get("date") or ""
    try:
        fx_dt = datetime.fromisoformat(fx_date_str.replace("Z", "+00:00"))
        fx_date = fx_dt.astimezone(timezone.utc).date()
    except (ValueError, AttributeError, TypeError):
        return None

    # Allow ±1 day tolerance for UTC vs local-day boundary
    return (
        db.query(Match)
        .filter(
            Match.home_team_id == home_team.id,
            Match.away_team_id == away_team.id,
            Match.league_id == league_id,
            Match.match_date.between(fx_date - timedelta(days=1), fx_date + timedelta(days=1)),
        )
        .first()
    )


def revalidate(db: Session, days: int = DEFAULT_DAYS, dry_run: bool = False) -> dict[str, Any]:
    """Cross-check the last ``days`` of completed matches against API-Football.

    Returns a summary dict (counts + the list of mismatches found). Caller is
    responsible for the DB session lifecycle; this function commits on success
    unless ``dry_run`` is True.
    """
    from models.league import League
    from models.match import Match
    from models.prediction import Prediction
    from models.score_correction import ScoreCorrection
    from services.player_availability_service import LEAGUE_API_FOOTBALL_IDS

    today = date.today()
    cutoff = today - timedelta(days=days)
    season = _current_season()
    run_id = _generate_run_id()

    # Group matches by (league_code, match_date) so we make one /fixtures call
    # per (league, day) — the cheapest way to cover N days × 10 leagues.
    matches = (
        db.query(Match)
        .join(League, Match.league_id == League.id)
        .filter(
            Match.status == "completed",
            Match.match_date >= cutoff,
            Match.match_date <= today,
        )
        .all()
    )

    summary: dict[str, Any] = {
        "run_id": run_id,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "dry_run": dry_run,
        "total_checked": 0,
        "skipped_no_league_mapping": 0,
        "skipped_no_api_fixture": 0,
        "agreed": 0,
        "mismatches_found": 0,
        "mismatches_fixed": 0,
        "predictions_reevaluated": 0,
        "audit_log_failures": 0,
        "skipped_leagues": [],
        "discrepancies": [],
    }

    # Group: (league_id, league_code, api_id, match_date) -> list[Match]
    # Skip leagues with no API-Football mapping up front and log them once.
    league_rows = {l.id: l for l in db.query(League).all()}
    skipped_codes: set[str] = set()
    grouped: dict[tuple[int, str, int, date], list[Match]] = {}
    for m in matches:
        league = league_rows.get(m.league_id)
        if not league:
            continue
        api_id = LEAGUE_API_FOOTBALL_IDS.get(league.code)
        if api_id is None:
            skipped_codes.add(league.code)
            summary["skipped_no_league_mapping"] += 1
            continue
        grouped.setdefault((league.id, league.code, api_id, m.match_date), []).append(m)

    if skipped_codes:
        summary["skipped_leagues"] = sorted(skipped_codes)
        logger.info("revalidate: leagues without API-Football mapping: %s", sorted(skipped_codes))

    for (league_id, league_code, api_id, match_date), match_group in grouped.items():
        fixtures = _fetch_fixtures_for_date(api_id, season, match_date)
        if not fixtures:
            summary["skipped_no_api_fixture"] += len(match_group)
            logger.info(
                "revalidate: no API-Football fixtures for %s on %s (%d matches skipped)",
                league_code, match_date, len(match_group),
            )
            continue

        # Index API fixtures by (home_team_id, away_team_id) at our DB level so
        # we don't repeat the resolver for every match.
        api_by_match_id: dict[int, dict] = {}
        for fx in fixtures:
            db_match = _match_fixture_to_db_match(db, fx, league_id)
            if db_match is not None:
                api_by_match_id[db_match.id] = fx

        for match in match_group:
            summary["total_checked"] += 1
            fx = api_by_match_id.get(match.id)
            if fx is None:
                summary["skipped_no_api_fixture"] += 1
                continue

            goals = (fx.get("goals") or {})
            api_home = goals.get("home")
            api_away = goals.get("away")
            api_status = ((fx.get("fixture") or {}).get("status") or {}).get("short") or ""

            if api_home is None or api_away is None:
                # API hasn't settled the score yet — nothing to compare
                continue

            db_home = match.home_goals
            db_away = match.away_goals

            if db_home == api_home and db_away == api_away:
                summary["agreed"] += 1
                continue

            severity = "MISMATCH" if api_status in _FINAL_STATUS_CODES else "STALE"
            new_result = _result_letter(api_home, api_away)

            disc = {
                "match_id": match.id,
                "league": league_code,
                "match_date": match.match_date.isoformat(),
                "kickoff_time": match.kickoff_time,
                "db_score": f"{db_home}-{db_away}",
                "api_score": f"{api_home}-{api_away}",
                "api_status": api_status,
                "severity": severity,
                "old_result": match.result,
                "new_result": new_result,
            }
            summary["mismatches_found"] += 1

            logger.warning(
                "revalidate: %s match_id=%d %s on %s — DB %s vs API %s (api_status=%s)",
                severity, match.id, league_code, match.match_date,
                disc["db_score"], disc["api_score"], api_status,
            )

            if not dry_run:
                # Snapshot the BEFORE state before mutating the row, otherwise
                # the audit log captures the post-write values.
                before_home = db_home
                before_away = db_away
                before_result = match.result

                match.home_goals = api_home
                match.away_goals = api_away
                match.result = new_result
                match.updated_at = datetime.now(timezone.utc)

                preds = (
                    db.query(Prediction)
                    .filter(Prediction.match_id == match.id)
                    .all()
                )
                for pred in preds:
                    pred.was_correct = (pred.predicted_result == new_result)
                disc["predictions_reevaluated"] = len(preds)
                summary["predictions_reevaluated"] += len(preds)
                summary["mismatches_fixed"] += 1

                # Best-effort audit log: never undo the score fix on failure.
                try:
                    db.add(
                        ScoreCorrection(
                            match_id=match.id,
                            before_home_goals=before_home,
                            before_away_goals=before_away,
                            before_result=before_result,
                            after_home_goals=api_home,
                            after_away_goals=api_away,
                            after_result=new_result,
                            source="api-football",
                            predictions_reevaluated=len(preds),
                            run_id=run_id,
                        )
                    )
                except Exception as exc:
                    summary["audit_log_failures"] += 1
                    logger.error(
                        "revalidate: failed to write audit row for match_id=%d: %s",
                        match.id, exc,
                    )

            summary["discrepancies"].append(disc)

        # gentle pacing between league/day API calls
        time.sleep(0.2)

    if not dry_run:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("revalidate: commit failed: %s", exc)
            summary["commit_error"] = str(exc)

    _emit_anomaly_log(summary)

    return summary


def _emit_anomaly_log(summary: dict[str, Any]) -> None:
    """Structured WARNING/ERROR log when mismatches exceed normal noise.

    Cloud Logging in production picks these up by severity and they're the
    natural hook for future alerting (e.g. PagerDuty/Discord on >15).

    A small sample of discrepancies is included so the on-call engineer can
    quickly spot which league or day looks suspicious without a DB roundtrip.
    """
    found = summary.get("mismatches_found", 0)
    if found <= _WARN_MISMATCH_THRESHOLD:
        return

    sample = [
        {
            "match_id": d["match_id"],
            "league": d["league"],
            "match_date": d["match_date"],
            "db_score": d["db_score"],
            "api_score": d["api_score"],
            "severity": d["severity"],
        }
        for d in summary.get("discrepancies", [])[:5]
    ]
    payload = {
        "event": "score_revalidation_anomaly",
        "run_id": summary.get("run_id"),
        "days": summary.get("days"),
        "mismatches_found": found,
        "mismatches_fixed": summary.get("mismatches_fixed", 0),
        "predictions_reevaluated": summary.get("predictions_reevaluated", 0),
        "sample": sample,
    }
    if found > _ERROR_MISMATCH_THRESHOLD:
        logger.error("revalidate: ANOMALY (severe) %s", payload)
    else:
        logger.warning("revalidate: ANOMALY %s", payload)


def _print_summary(summary: dict[str, Any]) -> None:
    print()
    print("=" * 60)
    print("Revalidation summary")
    print("=" * 60)
    print(f"  run id                : {summary.get('run_id', '?')}")
    print(f"  days window           : {summary['days']}")
    print(f"  dry-run               : {summary['dry_run']}")
    print(f"  total checked         : {summary['total_checked']}")
    print(f"  skipped (no mapping)  : {summary['skipped_no_league_mapping']}")
    print(f"  skipped (no fixture)  : {summary['skipped_no_api_fixture']}")
    print(f"  agreed                : {summary['agreed']}")
    print(f"  mismatches found      : {summary['mismatches_found']}")
    print(f"  mismatches fixed      : {summary['mismatches_fixed']}")
    print(f"  predictions re-eval'd : {summary['predictions_reevaluated']}")
    if summary.get("skipped_leagues"):
        print(f"  leagues w/o mapping   : {summary['skipped_leagues']}")
    if summary["discrepancies"]:
        print()
        print("Discrepancies:")
        for d in summary["discrepancies"]:
            print(
                f"  [{d['severity']}] match_id={d['match_id']} {d['league']} "
                f"{d['match_date']} {d['kickoff_time']}  "
                f"DB {d['db_score']} ({d['old_result']}) vs API {d['api_score']} "
                f"({d['new_result']})  api_status={d['api_status']}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-check recent scores vs API-Football.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help="Look back N days (default %(default)d)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Initialise the API key rotator from env (same pattern as main.py lifespan)
    from services.api_key_rotator import init_rotator
    raw_keys = os.getenv("API_FOOTBALL_KEYS", "")
    keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
    if not keys:
        print("ERROR: API_FOOTBALL_KEYS env var is empty — cannot revalidate", file=sys.stderr)
        return 2
    init_rotator(keys)

    from database import SessionLocal
    db = SessionLocal()
    try:
        summary = revalidate(db, days=args.days, dry_run=args.dry_run)
    finally:
        db.close()

    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
