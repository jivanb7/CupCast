"""
backend/api/teams.py
=====================
Route handlers for team-related endpoints.

Endpoints:
  GET /teams/{team_id}/form
    Returns: TeamFormResponse — last 10 matches + upcoming 3 fixtures + form stats
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.league import League
from models.match import Match
from models.prediction import Prediction
from models.team import Team

router = APIRouter(prefix="/teams", tags=["teams"])


# Inline response schema — no existing schema file for this endpoint
class MatchRef(BaseModel):
    match_id: int
    match_date: date
    opponent_name: str
    is_home: bool
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    result_for_team: Optional[str] = None  # 'W', 'D', 'L'
    league_code: Optional[str] = None
    status: str


class TeamFormResponse(BaseModel):
    team_id: int
    team_name: str
    short_name: Optional[str] = None
    team_type: str
    last_10_matches: list[MatchRef]
    next_3_fixtures: list[MatchRef]
    # Aggregated form stats from last 10 matches
    form_string: str  # e.g. "WWDLW..."
    wins: int
    draws: int
    losses: int
    goals_scored: int
    goals_conceded: int
    win_rate: float


@router.get("/{team_id}/form", response_model=TeamFormResponse)
def get_team_form(
    team_id: int,
    db: Session = Depends(get_db),
):
    """Return recent form stats and upcoming fixtures for a team."""
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")

    # Last 10 completed matches (home or away)
    recent_matches = (
        db.query(Match)
        .filter(
            Match.status == "completed",
            (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
        )
        .order_by(Match.match_date.desc())
        .limit(10)
        .all()
    )

    # Next 3 scheduled fixtures
    today = date.today()
    upcoming_matches = (
        db.query(Match)
        .filter(
            Match.status == "scheduled",
            Match.match_date >= today,
            (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
        )
        .order_by(Match.match_date)
        .limit(3)
        .all()
    )

    # Collect all opponent IDs and league IDs for batch load
    all_matches = recent_matches + upcoming_matches
    opponent_ids = set()
    for m in all_matches:
        opp_id = m.away_team_id if m.home_team_id == team_id else m.home_team_id
        opponent_ids.add(opp_id)
    league_ids = {m.league_id for m in all_matches if m.league_id}

    opponents_by_id = (
        {t.id: t for t in db.query(Team).filter(Team.id.in_(opponent_ids)).all()}
        if opponent_ids else {}
    )
    leagues_by_id = (
        {l.id: l for l in db.query(League).filter(League.id.in_(league_ids)).all()}
        if league_ids else {}
    )

    def _match_to_ref(m: Match) -> MatchRef:
        is_home = m.home_team_id == team_id
        opp_id = m.away_team_id if is_home else m.home_team_id
        opp = opponents_by_id.get(opp_id)
        league = leagues_by_id.get(m.league_id) if m.league_id else None

        result_for_team = None
        if m.result:
            if m.result == "D":
                result_for_team = "D"
            elif (m.result == "H" and is_home) or (m.result == "A" and not is_home):
                result_for_team = "W"
            else:
                result_for_team = "L"

        return MatchRef(
            match_id=m.id,
            match_date=m.match_date,
            opponent_name=opp.canonical_name if opp else f"Team {opp_id}",
            is_home=is_home,
            home_goals=m.home_goals,
            away_goals=m.away_goals,
            result_for_team=result_for_team,
            league_code=league.code if league else None,
            status=m.status,
        )

    last_10 = [_match_to_ref(m) for m in recent_matches]
    next_3 = [_match_to_ref(m) for m in upcoming_matches]

    # Aggregate stats from last 10
    wins = sum(1 for r in last_10 if r.result_for_team == "W")
    draws = sum(1 for r in last_10 if r.result_for_team == "D")
    losses = sum(1 for r in last_10 if r.result_for_team == "L")

    goals_scored = sum(
        (m.home_goals or 0) if m.home_team_id == team_id else (m.away_goals or 0)
        for m in recent_matches
    )
    goals_conceded = sum(
        (m.away_goals or 0) if m.home_team_id == team_id else (m.home_goals or 0)
        for m in recent_matches
    )

    form_chars = [r.result_for_team or "?" for r in last_10]
    form_string = "".join(reversed(form_chars))  # chronological order

    total = len(last_10)
    win_rate = round(wins / total, 2) if total else 0.0

    return TeamFormResponse(
        team_id=team.id,
        team_name=team.canonical_name,
        short_name=team.short_name,
        team_type=team.team_type,
        last_10_matches=last_10,
        next_3_fixtures=next_3,
        form_string=form_string,
        wins=wins,
        draws=draws,
        losses=losses,
        goals_scored=goals_scored,
        goals_conceded=goals_conceded,
        win_rate=win_rate,
    )
