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
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# football-data.co.uk base URL
FOOTBALL_DATA_UK_BASE = "https://www.football-data.co.uk/mmz4281"

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
        resp = requests.get(url, timeout=30)
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

            if match.status == "completed":
                # Backfill was_correct on predictions that haven't been evaluated yet
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

                match.home_goals = home_goals
                match.away_goals = away_goals
                match.result = result
                match.status = "completed"

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
    live_stats = update_scores_from_live_api(db)
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
            for pred in unevaluated:
                match = db.query(Match).filter(Match.id == pred.match_id).first()
                if match and match.result:
                    pred.was_correct = (pred.predicted_result == match.result)
            db.commit()
            logger.info("Backfilled was_correct for %d unevaluated predictions", len(unevaluated))
    except Exception as e:
        logger.error("Failed to backfill was_correct: %s", e)

    return stats


def update_scores_from_live_api(db: Session) -> dict:
    """
    Use Football-Data.org API to update finished matches that the CSV missed.
    This catches same-day results before the CSV files are updated.
    """
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
        resp = requests.get(
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
            match.status = "completed"

            # Evaluate predictions
            predictions = db.query(Prediction).filter(Prediction.match_id == match.id).all()
            for pred in predictions:
                pred.was_correct = (pred.predicted_result == result)

            stats["updated"] += 1
            logger.info("Live API: updated %s %d-%d %s", home_name, home_goals, away_goals, away_name)

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
