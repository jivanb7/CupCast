"""
backend/services/score_updater.py
===================================
Service for fetching live/final scores and updating match results in the DB.

Data source:
  football-data.co.uk CSV files — same source as the ML pipeline.
  For each league, the current season CSV is re-downloaded and compared
  against scheduled matches in the DB to find newly completed games.

Flow:
  1. Download latest season CSV for each active league
  2. Parse completed matches (rows with FTHG/FTAG scores)
  3. Match against DB records by (home_team, away_team, date)
  4. Update status='completed', set goals, result, and match stats
  5. Mark predictions as correct/incorrect

Called by:
  - refresh_scheduler.py (on a cron schedule)
  - POST /admin/scores/update (manual trigger)
"""

import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

# Module-level Session for connection pooling across scheduler job invocations
_session = requests.Session()
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# football-data.co.uk base URL
FOOTBALL_DATA_UK_BASE = "https://www.football-data.co.uk/mmz4281"

# How long after a match is marked 'completed' we still cross-check incoming
# data against it. Catches the Real-Betis-style bug where an intermediate score
# was locked in and the late equaliser never updated. 6 h covers a match that
# ends at 22:00 local being re-checked by ~04:00 next day before users wake up.
COMPLETED_RECHECK_WINDOW = timedelta(hours=6)

# Minimum minutes after kickoff before we trust a 'FINISHED' signal.
#  - regular league match: 90' + 15' stoppage/HT = 105 min
#  - cup-style match (UCL knockouts, World Cup KO): may go to ET + pens, allow 130 min
FULLTIME_MIN_AFTER_KICKOFF_NORMAL_S = 105 * 60
FULLTIME_MIN_AFTER_KICKOFF_CUP_S = 130 * 60

# League codes whose matches can extend to extra time + penalties. Detection is
# coarse (group-stage WC games can't go to ET, but the cost of waiting an extra
# 25 min before marking them complete is just a delayed update — much cheaper
# than locking in a half-time score on a knockout that ends 2-2 then 4-2 on pens).
_CUP_LEAGUE_CODES = {"ucl", "worldcup"}


def _utc_now_naive() -> datetime:
    """UTC 'now' as a naive datetime (matches SQLite CURRENT_TIMESTAMP storage)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _score_updater_run_id() -> str:
    """Generate a run_id for an in-window correction caught by score_updater.

    Format: ``score_updater:<utc-iso-secs>-<3-byte-hex>``. Lets us group all
    corrections written during a single update_scores() invocation while
    distinguishing them from revalidate() runs.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"score_updater:{ts}-{secrets.token_hex(3)}"


def _record_correction(
    db,
    *,
    match_id: int,
    before_home: Optional[int],
    before_away: Optional[int],
    before_result: Optional[str],
    after_home: int,
    after_away: int,
    after_result: str,
    source: str,
    predictions_reevaluated: int,
    run_id: str,
) -> None:
    """Best-effort audit log insert. Never raises; logs and moves on."""
    from models.score_correction import ScoreCorrection
    try:
        db.add(
            ScoreCorrection(
                match_id=match_id,
                before_home_goals=before_home,
                before_away_goals=before_away,
                before_result=before_result,
                after_home_goals=after_home,
                after_away_goals=after_away,
                after_result=after_result,
                source=source,
                predictions_reevaluated=predictions_reevaluated,
                run_id=run_id,
            )
        )
    except Exception as exc:
        logger.error(
            "score_updater: failed to write audit row for match_id=%d: %s",
            match_id, exc,
        )


def _is_cup_match(match, league_code: Optional[str] = None) -> bool:
    """Return True if this match should use the longer 130-min FT guard."""
    if league_code and league_code in _CUP_LEAGUE_CODES:
        return True
    # Fallback: legacy free-text 'tournament' field on the Match model.
    tournament = (getattr(match, "tournament", None) or "").lower()
    return any(tag in tournament for tag in ("world cup", "champions league", "uefa", "fifa"))


# Map DB league codes to football-data.co.uk division codes
LEAGUE_TO_DIV = {
    "epl": "E0",
    "championship": "E1",
    "league_one": "E2",
    "league_two": "E3",
    "national_league": "EC",
    "laliga": "SP1",
    "seriea": "I1",
    "bundesliga": "D1",
    "ligue1": "F1",
}

# Current season code (e.g., "2526" for 2025-26)
def _current_season_code() -> str:
    today = date.today()
    if today.month >= 7:
        return f"{str(today.year)[2:]}{str(today.year + 1)[2:]}"
    else:
        return f"{str(today.year - 1)[2:]}{str(today.year)[2:]}"


def fetch_latest_results(div_code: str) -> Optional[pd.DataFrame]:
    """Download the current season CSV for a division and return as DataFrame."""
    season = _current_season_code()
    url = f"{FOOTBALL_DATA_UK_BASE}/{season}/{div_code}.csv"
    try:
        resp = _session.get(url, timeout=30)
        if resp.status_code == 404:
            logger.warning("No data for %s season %s", div_code, season)
            return None
        resp.raise_for_status()

        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))
        return df
    except Exception as e:
        logger.error("Failed to fetch %s: %s", url, e)
        return None


def update_scores(db: Session) -> dict:
    """
    Fetch latest scores for all active leagues and update the database.

    Returns dict with counts: {updated: int, already_current: int, errors: int}
    """
    from models.league import League
    from models.match import Match
    from models.prediction import Prediction
    from models.team import Team

    stats = {"updated": 0, "already_current": 0, "not_found": 0, "errors": 0}
    run_id = _score_updater_run_id()

    # Get all active leagues
    leagues = db.query(League).filter(League.is_active == True).all()

    for league in leagues:
        div_code = LEAGUE_TO_DIV.get(league.code)
        if not div_code:
            continue

        df = fetch_latest_results(div_code)
        if df is None or df.empty:
            continue

        # Build team name lookup: canonical_name -> team_id
        teams = db.query(Team).filter(Team.league_id == league.id).all()
        team_lookup = {}
        for t in teams:
            team_lookup[t.canonical_name] = t.id
            if t.short_name:
                team_lookup[t.short_name] = t.id

        # Add aliases to lookup
        from models.team import TeamNameAlias
        aliases = (
            db.query(TeamNameAlias)
            .filter(TeamNameAlias.team_id.in_([t.id for t in teams]))
            .all()
        )
        for a in aliases:
            team_lookup[a.alias] = a.team_id

        # Also try normalizing via the ML team name mapping
        try:
            from ml.src.team_name_mapping import normalize_team_name
        except ImportError:
            normalize_team_name = lambda x, **kw: x

        # Process completed matches from CSV
        for _, row in df.iterrows():
            # Skip rows without final scores
            if pd.isna(row.get("FTHG")) or pd.isna(row.get("FTAG")):
                continue

            home_name = str(row.get("HomeTeam", ""))
            away_name = str(row.get("AwayTeam", ""))

            if not home_name or not away_name:
                continue

            # Normalize names
            home_canonical = normalize_team_name(home_name, league_code=div_code)
            away_canonical = normalize_team_name(away_name, league_code=div_code)

            home_id = team_lookup.get(home_canonical) or team_lookup.get(home_name)
            away_id = team_lookup.get(away_canonical) or team_lookup.get(away_name)

            if not home_id or not away_id:
                continue

            # Parse match date
            try:
                date_str = str(row.get("Date", ""))
                match_date = pd.to_datetime(date_str, dayfirst=True).date()
            except Exception:
                continue

            # Find the matching DB record
            match = (
                db.query(Match)
                .filter(
                    Match.home_team_id == home_id,
                    Match.away_team_id == away_id,
                    Match.league_id == league.id,
                    Match.match_date == match_date,
                )
                .first()
            )

            if not match:
                stats["not_found"] += 1
                continue

            # Re-check window: if a match was completed > 6 h ago, treat it as
            # frozen (no need to keep re-syncing months-old results). Within
            # the window, fall through and re-apply the CSV row in case our
            # earlier write captured an intermediate score (Real-Betis bug).
            if match.status == "completed":
                _now_utc = _utc_now_naive()
                # NULL updated_at = legacy row → treat as stale
                if match.updated_at is None or (_now_utc - match.updated_at) > COMPLETED_RECHECK_WINDOW:
                    if match.result:
                        unevaluated = (
                            db.query(Prediction)
                            .filter(Prediction.match_id == match.id, Prediction.was_correct == None)
                            .all()
                        )
                        for pred in unevaluated:
                            pred.was_correct = (pred.predicted_result == match.result)
                    stats["already_current"] += 1
                    continue
                # else: within re-check window — fall through to re-apply CSV scores

            # Update match with scores
            try:
                home_goals = int(row["FTHG"])
                away_goals = int(row["FTAG"])

                if home_goals > away_goals:
                    result = "H"
                elif home_goals < away_goals:
                    result = "A"
                else:
                    result = "D"

                # Snapshot before-state for the audit log. We only want to log
                # a "correction" when this row was already 'completed' AND the
                # incoming score differs (i.e. we're inside the 6-h re-check
                # window catching a Real-Betis-style late goal).
                was_completed = match.status == "completed"
                prev_home = match.home_goals
                prev_away = match.away_goals
                prev_result = match.result
                is_correction = was_completed and (
                    prev_home != home_goals
                    or prev_away != away_goals
                    or prev_result != result
                )

                match.home_goals = home_goals
                match.away_goals = away_goals
                match.result = result
                match.status = "completed"
                match.updated_at = _utc_now_naive()

                # Update optional stats if available
                if not pd.isna(row.get("HTHG")):
                    match.ht_home_goals = int(row["HTHG"])
                if not pd.isna(row.get("HTAG")):
                    match.ht_away_goals = int(row["HTAG"])
                if not pd.isna(row.get("HS")):
                    match.home_shots = int(row["HS"])
                if not pd.isna(row.get("AS")):
                    match.away_shots = int(row["AS"])
                if not pd.isna(row.get("HST")):
                    match.home_shots_on_target = int(row["HST"])
                if not pd.isna(row.get("AST")):
                    match.away_shots_on_target = int(row["AST"])
                if not pd.isna(row.get("HC")):
                    match.home_corners = int(row["HC"])
                if not pd.isna(row.get("AC")):
                    match.away_corners = int(row["AC"])
                if not pd.isna(row.get("HF")):
                    match.home_fouls = int(row["HF"])
                if not pd.isna(row.get("AF")):
                    match.away_fouls = int(row["AF"])
                if not pd.isna(row.get("HY")):
                    match.home_yellow_cards = int(row["HY"])
                if not pd.isna(row.get("AY")):
                    match.away_yellow_cards = int(row["AY"])
                if not pd.isna(row.get("HR")):
                    match.home_red_cards = int(row["HR"])
                if not pd.isna(row.get("AR")):
                    match.away_red_cards = int(row["AR"])

                # Evaluate predictions for this match
                predictions = (
                    db.query(Prediction)
                    .filter(Prediction.match_id == match.id)
                    .all()
                )
                for pred in predictions:
                    pred.was_correct = (pred.predicted_result == result)

                if is_correction:
                    _record_correction(
                        db,
                        match_id=match.id,
                        before_home=prev_home,
                        before_away=prev_away,
                        before_result=prev_result,
                        after_home=home_goals,
                        after_away=away_goals,
                        after_result=result,
                        source="football-data-csv",
                        predictions_reevaluated=len(predictions),
                        run_id=run_id,
                    )

                stats["updated"] += 1

            except Exception as e:
                logger.error("Error updating match %d: %s", match.id, e)
                stats["errors"] += 1

    try:
        db.commit()
        logger.info(
            "Score update (CSV): %d updated, %d already current, %d not found, %d errors",
            stats["updated"], stats["already_current"], stats["not_found"], stats["errors"],
        )
    except Exception as e:
        db.rollback()
        logger.error("Failed to commit score updates: %s", e)
        stats["errors"] += 1

    # Second pass: use Football-Data.org live API for matches the CSV missed
    live_stats = update_scores_from_live_api(db, run_id=run_id)
    stats["updated"] += live_stats.get("updated", 0)

    # Final pass: backfill was_correct for any unevaluated predictions on completed matches
    # This catches predictions written after scores were already set (e.g., startup race condition)
    try:
        unevaluated = (
            db.query(Prediction)
            .join(Match, Prediction.match_id == Match.id)
            .filter(
                Match.status == "completed",
                Match.result != None,
                Prediction.was_correct == None,
            )
            .all()
        )
        if unevaluated:
            # Batch-fetch matches for all unevaluated predictions in a single query
            match_ids = {pred.match_id for pred in unevaluated}
            matches_by_id = {
                m.id: m
                for m in db.query(Match).filter(Match.id.in_(match_ids)).all()
            }
            for pred in unevaluated:
                match = matches_by_id.get(pred.match_id)
                if match and match.result:
                    pred.was_correct = (pred.predicted_result == match.result)
            db.commit()
            logger.info("Backfilled was_correct for %d unevaluated predictions", len(unevaluated))
    except Exception as e:
        logger.error("Failed to backfill was_correct: %s", e)

    return stats


def update_scores_from_live_api(db: Session, run_id: Optional[str] = None) -> dict:
    """
    Use Football-Data.org API to update finished matches that the CSV missed.
    This catches same-day results before the CSV files are updated.

    ``run_id`` (optional) groups any audit-log rows written by this pass with
    the parent ``update_scores`` invocation. When called standalone the function
    allocates its own.
    """
    if run_id is None:
        run_id = _score_updater_run_id()
    from models.league import League
    from models.match import Match
    from models.prediction import Prediction
    from models.team import Team

    stats = {"updated": 0, "errors": 0}

    try:
        from config import settings
        api_key = settings.football_data_org_api_key
    except Exception:
        api_key = ""

    if not api_key:
        return stats

    try:
        headers = {"X-Auth-Token": api_key}
        resp = _session.get(
            "https://api.football-data.org/v4/matches",
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("Live API returned %d", resp.status_code)
            return stats

        data = resp.json()
        finished = [m for m in data.get("matches", []) if m.get("status") == "FINISHED"]

        if not finished:
            return stats

        # Build flexible team name lookup from DB (handles FC/AFC suffix mismatches)
        all_teams = db.query(Team).all()
        team_by_name = {}
        for t in all_teams:
            team_by_name[t.canonical_name] = t.id
            if t.short_name:
                team_by_name[t.short_name] = t.id
            # Also index without common suffixes
            for suffix in [" FC", " AFC", " F.C."]:
                clean = t.canonical_name.replace(suffix, "").strip()
                if clean != t.canonical_name:
                    team_by_name[clean] = t.id

        def _find_team(api_name):
            if api_name in team_by_name:
                return team_by_name[api_name]
            for suffix in [" FC", " AFC", " F.C."]:
                clean = api_name.replace(suffix, "").strip()
                if clean in team_by_name:
                    return team_by_name[clean]
            return None

        for api_match in finished:
            home_name = api_match.get("homeTeam", {}).get("name", "")
            away_name = api_match.get("awayTeam", {}).get("name", "")
            score = api_match.get("score", {}).get("fullTime", {})
            home_goals = score.get("home")
            away_goals = score.get("away")

            if home_goals is None or away_goals is None:
                continue

            # Try to find this match in our DB
            match_date_str = api_match.get("utcDate", "")[:10]
            try:
                from datetime import datetime
                match_date = datetime.strptime(match_date_str, "%Y-%m-%d").date()
            except Exception:
                continue

            home_id = _find_team(home_name)
            away_id = _find_team(away_name)

            if not home_id or not away_id:
                # Try alias lookup via TeamNameAlias table
                from models.team import TeamNameAlias
                if not home_id:
                    alias = db.query(TeamNameAlias).filter(TeamNameAlias.alias == home_name).first()
                    if alias:
                        home_id = alias.team_id
                if not away_id:
                    alias = db.query(TeamNameAlias).filter(TeamNameAlias.alias == away_name).first()
                    if alias:
                        away_id = alias.team_id

            if not home_id or not away_id:
                continue

            match = (
                db.query(Match)
                .filter(
                    Match.home_team_id == home_id,
                    Match.away_team_id == away_id,
                    Match.match_date == match_date,
                    Match.status.in_(["scheduled", "live"]),
                )
                .first()
            )

            if not match:
                continue

            # Time guard: FD.org occasionally reports FINISHED prematurely. Only
            # trust it once enough time has passed since kickoff to cover full
            # regulation + stoppage (and ET + pens for cup-style matches).
            from datetime import datetime as _dt, timezone as _tz
            past_full_time = False
            if match.kickoff_time and match.match_date:
                try:
                    _dh, _dm = match.kickoff_time.split(":")
                    _ko = _dt.combine(match.match_date, _dt.min.time(), tzinfo=_tz.utc).replace(
                        hour=int(_dh), minute=int(_dm)
                    )
                    # Resolve the league code so cup matches get the longer window
                    league_obj = db.query(League).filter(League.id == match.league_id).first()
                    league_code = league_obj.code if league_obj else None
                    threshold_s = (
                        FULLTIME_MIN_AFTER_KICKOFF_CUP_S
                        if _is_cup_match(match, league_code)
                        else FULLTIME_MIN_AFTER_KICKOFF_NORMAL_S
                    )
                    past_full_time = (_dt.now(_tz.utc) - _ko).total_seconds() >= threshold_s
                except (ValueError, AttributeError):
                    past_full_time = False

            # Update the match
            if home_goals > away_goals:
                result = "H"
            elif home_goals < away_goals:
                result = "A"
            else:
                result = "D"

            match.home_goals = home_goals
            match.away_goals = away_goals
            match.result = result
            match.updated_at = _utc_now_naive()
            if past_full_time:
                match.status = "completed"
                # Evaluate predictions only once we trust the FINISHED signal.
                predictions = db.query(Prediction).filter(Prediction.match_id == match.id).all()
                for pred in predictions:
                    pred.was_correct = (pred.predicted_result == result)
                stats["updated"] += 1
                logger.info("Live API: completed %s %d-%d %s", home_name, home_goals, away_goals, away_name)
            else:
                logger.info(
                    "Live API: FINISHED too early for %s vs %s (kickoff %s) — score synced, status left 'live'",
                    home_name, away_name, match.kickoff_time,
                )

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("Failed to commit live API updates: %s", e)
            stats["errors"] += 1

    except Exception as e:
        logger.error("Live API score update failed: %s", e)
        stats["errors"] += 1

    if stats["updated"]:
        logger.info("Live API: updated %d matches", stats["updated"])
    return stats
