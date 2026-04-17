"""
backend/api/matches.py
=======================
Route handlers for match-related endpoints.

Endpoints:
  GET /matches/upcoming
    Query params: league (str, optional), days_ahead (int, default=7)
    Returns: UpcomingMatchesResponse
    Logic: Query matches where status='scheduled' AND match_date <= today + days_ahead.
           Join with predictions table to include prediction data.
           Filter by league_code if provided.

  GET /matches/results
    Query params: league (str, optional), days_back (int, default=7)
    Returns: ResultsResponse with prediction accuracy

  GET /matches/{match_id}
    Returns: MatchDetail
    Logic: Query single match + prediction + last 5 H2H matches + team form stats.

All endpoints return 404 if match_id not found.
Pagination is not required for MVP (frontend shows 7-day windows).
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models.league import League
from models.match import Match
from models.prediction import Prediction
from models.team import Team
from schemas.match import (
    MatchDetail,
    MatchSummary,
    PredictionSummary,
    ResultsResponse,
    TeamFormStats,
    UpcomingMatchesResponse,
)

router = APIRouter(prefix="/matches", tags=["matches"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_team_map(db: Session, team_ids: list[int]) -> dict[int, Team]:
    if not team_ids:
        return {}
    return {t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()}


def _build_league_map(db: Session, league_ids: list[int]) -> dict[int, League]:
    if not league_ids:
        return {}
    return {l.id: l for l in db.query(League).filter(League.id.in_(league_ids)).all()}


def _build_prediction_map(db: Session, match_ids: list[int]) -> dict[int, Prediction]:
    """Return the latest prediction per match_id (by created_at DESC)."""
    if not match_ids:
        return {}
    preds = (
        db.query(Prediction)
        .filter(Prediction.match_id.in_(match_ids))
        .order_by(Prediction.created_at.desc())
        .all()
    )
    # Keep only the most recent prediction per match
    result = {}
    for p in preds:
        if p.match_id not in result:
            result[p.match_id] = p
    return result


def _prediction_to_summary(pred: Optional[Prediction]) -> Optional[PredictionSummary]:
    if pred is None:
        return None
    return PredictionSummary(
        prob_home_win=pred.prob_home_win,
        prob_draw=pred.prob_draw,
        prob_away_win=pred.prob_away_win,
        predicted_result=pred.predicted_result,
        confidence=pred.confidence or 0.0,
        is_value_pick=pred.is_value_pick or False,
        value_pick_direction=pred.value_pick_direction,
        explanation_text=pred.explanation_text,
        was_correct=pred.was_correct,
    )


def _get_live_minute(home_name: str, away_name: str) -> Optional[str]:
    """Look up the current match minute from the live score cache."""
    try:
        from services.live_score_service import live_scores
        db_home = home_name.replace(" FC", "").replace(" AFC", "").replace(" F.C.", "").strip()
        db_away = away_name.replace(" FC", "").replace(" AFC", "").replace(" F.C.", "").strip()

        # Check all cache entries, prefer ones with a minute value
        best_minute = None
        for m in live_scores._cache.values():
            if m.get("status") not in ("IN_PLAY", "HALFTIME"):
                continue
            cache_home = (m.get("home_team") or "").replace(" FC", "").replace(" AFC", "").replace(" F.C.", "").strip()
            cache_away = (m.get("away_team") or "").replace(" FC", "").replace(" AFC", "").replace(" F.C.", "").strip()
            if cache_home == db_home and cache_away == db_away:
                minute = m.get("minute")
                if minute:
                    return minute  # Found one with a minute — use it
                best_minute = minute  # Keep looking for one with a minute
        return best_minute
    except Exception:
        pass
    return None


def _match_to_summary(
    m: Match,
    teams: dict[int, Team],
    leagues: dict[int, League],
    predictions: dict[int, Prediction],
) -> MatchSummary:
    home = teams.get(m.home_team_id)
    away = teams.get(m.away_team_id)
    league = leagues.get(m.league_id) if m.league_id else None

    home_name = home.canonical_name if home else f"Team {m.home_team_id}"
    away_name = away.canonical_name if away else f"Team {m.away_team_id}"

    # Get live minute if match is in play
    match_minute = None
    if m.status == "live":
        match_minute = _get_live_minute(home_name, away_name)

    return MatchSummary(
        id=m.id,
        match_date=m.match_date,
        home_team_id=m.home_team_id,
        home_team_name=home_name,
        home_team_short_name=home.short_name if home else None,
        away_team_id=m.away_team_id,
        away_team_name=away_name,
        away_team_short_name=away.short_name if away else None,
        league_code=league.code if league else "unknown",
        league_name=league.name if league else "Unknown League",
        season=m.season,
        home_goals=m.home_goals,
        away_goals=m.away_goals,
        result=m.result,
        status=m.status,
        match_minute=match_minute,
        kickoff_time=m.kickoff_time,
        tournament=m.tournament,
        prediction=_prediction_to_summary(predictions.get(m.id)),
    )


def _get_team_form(db: Session, team_id: int, team_name: str, n: int = 5) -> TeamFormStats:
    """Compute last N completed matches for a team and return form stats."""
    recent = (
        db.query(Match)
        .filter(
            Match.status == "completed",
            Match.result != None,
            (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
        )
        .order_by(Match.match_date.desc())
        .limit(n)
        .all()
    )

    results = []
    goals_scored = []
    goals_conceded = []

    for m in recent:
        is_home = m.home_team_id == team_id
        if is_home:
            gf = m.home_goals or 0
            ga = m.away_goals or 0
            outcome = m.result  # H=win, D=draw, A=loss
        else:
            gf = m.away_goals or 0
            ga = m.home_goals or 0
            # Flip result perspective
            if m.result == "H":
                outcome = "A"
            elif m.result == "A":
                outcome = "H"
            else:
                outcome = "D"

        if outcome == "H":
            results.append("W")
        elif outcome == "D":
            results.append("D")
        else:
            results.append("L")

        goals_scored.append(gf)
        goals_conceded.append(ga)

    wins = results.count("W")
    total = len(results)

    return TeamFormStats(
        team_name=team_name,
        last_5_results=results,
        goals_scored_avg_5=round(sum(goals_scored) / total, 2) if total else 0.0,
        goals_conceded_avg_5=round(sum(goals_conceded) / total, 2) if total else 0.0,
        win_rate_5=round(wins / total, 2) if total else 0.0,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/upcoming", response_model=UpcomingMatchesResponse)
def get_upcoming_matches(
    league: Optional[str] = Query(None, description="Filter by league code"),
    days_ahead: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """Return upcoming scheduled matches with predictions."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    query = (
        db.query(Match)
        .filter(
            Match.status.in_(["scheduled", "live"]),
            Match.match_date >= today,
            Match.match_date <= cutoff,
        )
    )

    if league:
        league_obj = db.query(League).filter(League.code == league).first()
        if not league_obj:
            raise HTTPException(status_code=404, detail=f"League '{league}' not found")
        query = query.filter(Match.league_id == league_obj.id)

    matches = query.order_by(Match.match_date).all()

    team_ids = list({m.home_team_id for m in matches} | {m.away_team_id for m in matches})
    league_ids = list({m.league_id for m in matches if m.league_id})
    match_ids = [m.id for m in matches]

    teams = _build_team_map(db, team_ids)
    leagues_map = _build_league_map(db, league_ids)
    predictions = _build_prediction_map(db, match_ids)

    summaries = [_match_to_summary(m, teams, leagues_map, predictions) for m in matches]

    return UpcomingMatchesResponse(
        matches=summaries,
        total=len(summaries),
        league_filter=league,
        days_ahead=days_ahead,
    )


@router.get("/results", response_model=ResultsResponse)
def get_results(
    league: Optional[str] = Query(None),
    days_back: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Return recent match results with prediction accuracy tracking."""
    today = date.today()
    since = today - timedelta(days=days_back)

    query = (
        db.query(Match)
        .filter(
            Match.status == "completed",
            Match.match_date >= since,
            Match.match_date <= today,
        )
    )

    if league:
        league_obj = db.query(League).filter(League.code == league).first()
        if not league_obj:
            raise HTTPException(status_code=404, detail=f"League '{league}' not found")
        query = query.filter(Match.league_id == league_obj.id)

    matches = query.order_by(Match.match_date.desc()).all()

    team_ids = list({m.home_team_id for m in matches} | {m.away_team_id for m in matches})
    league_ids = list({m.league_id for m in matches if m.league_id})
    match_ids = [m.id for m in matches]

    teams = _build_team_map(db, team_ids)
    leagues_map = _build_league_map(db, league_ids)
    predictions = _build_prediction_map(db, match_ids)

    summaries = [_match_to_summary(m, teams, leagues_map, predictions) for m in matches]

    # Compute accuracy from was_correct column
    evaluated = [p for p in predictions.values() if p.was_correct is not None]
    if evaluated:
        correct = sum(1 for p in evaluated if p.was_correct)
        accuracy = round(correct / len(evaluated), 4)
    else:
        accuracy = None

    return ResultsResponse(
        matches=summaries,
        total=len(summaries),
        prediction_accuracy=accuracy,
    )


@router.get("/{match_id}", response_model=MatchDetail)
def get_match(
    match_id: int,
    db: Session = Depends(get_db),
):
    """Return full match detail with prediction, team form, and H2H history."""
    m = db.query(Match).filter(Match.id == match_id).first()
    if not m:
        raise HTTPException(status_code=404, detail=f"Match {match_id} not found")

    home_team = db.query(Team).filter(Team.id == m.home_team_id).first()
    away_team = db.query(Team).filter(Team.id == m.away_team_id).first()
    league = db.query(League).filter(League.id == m.league_id).first() if m.league_id else None

    pred = (
        db.query(Prediction)
        .filter(Prediction.match_id == m.id)
        .order_by(Prediction.created_at.desc())
        .first()
    )

    # Build team form for each side
    home_name = home_team.canonical_name if home_team else f"Team {m.home_team_id}"
    away_name = away_team.canonical_name if away_team else f"Team {m.away_team_id}"

    home_form = _get_team_form(db, m.home_team_id, home_name)
    away_form = _get_team_form(db, m.away_team_id, away_name)

    # H2H: last 5 matches between these two teams (either direction)
    from sqlalchemy import or_, and_
    h2h_matches = (
        db.query(Match)
        .filter(
            Match.status == "completed",
            Match.id != m.id,
            or_(
                and_(Match.home_team_id == m.home_team_id, Match.away_team_id == m.away_team_id),
                and_(Match.home_team_id == m.away_team_id, Match.away_team_id == m.home_team_id),
            ),
        )
        .order_by(Match.match_date.desc())
        .limit(5)
        .all()
    )

    h2h_team_ids = list(
        {hm.home_team_id for hm in h2h_matches} | {hm.away_team_id for hm in h2h_matches}
    )
    h2h_league_ids = list({hm.league_id for hm in h2h_matches if hm.league_id})
    h2h_teams = _build_team_map(db, h2h_team_ids)
    h2h_leagues = _build_league_map(db, h2h_league_ids)
    h2h_preds = _build_prediction_map(db, [hm.id for hm in h2h_matches])

    h2h_summaries = [
        _match_to_summary(hm, h2h_teams, h2h_leagues, h2h_preds)
        for hm in h2h_matches
    ]

    league_code = league.code if league else "unknown"
    league_name = league.name if league else "Unknown League"

    return MatchDetail(
        id=m.id,
        match_date=m.match_date,
        home_team_id=m.home_team_id,
        home_team_name=home_name,
        home_team_short_name=home_team.short_name if home_team else None,
        away_team_id=m.away_team_id,
        away_team_name=away_name,
        away_team_short_name=away_team.short_name if away_team else None,
        league_code=league_code,
        league_name=league_name,
        season=m.season,
        home_goals=m.home_goals,
        away_goals=m.away_goals,
        result=m.result,
        status=m.status,
        tournament=m.tournament,
        prediction=_prediction_to_summary(pred),
        home_shots=m.home_shots,
        away_shots=m.away_shots,
        home_shots_on_target=m.home_shots_on_target,
        away_shots_on_target=m.away_shots_on_target,
        home_corners=m.home_corners,
        away_corners=m.away_corners,
        home_form=home_form,
        away_form=away_form,
        h2h_last_5=h2h_summaries,
    )
