"""
backend/api/leagues.py
=======================
Route handlers for league and standings endpoints.

Endpoints:
  GET /leagues/
    Returns: list[LeagueResponse] — all active leagues

  GET /leagues/{league_code}/standings
    Returns: StandingsResponse
    Logic: Compute standings from completed matches in the current season.
           Count W/D/L, goals for/against, points. Sort by points desc.
           This is computed from the matches table, not stored separately.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.league import League
from models.match import Match
from models.team import Team
from schemas.league import LeagueResponse, StandingsResponse, StandingsEntry

router = APIRouter(prefix="/leagues", tags=["leagues"])


@router.get("/", response_model=list[LeagueResponse])
def get_leagues(db: Session = Depends(get_db)):
    """Return all active supported leagues."""
    leagues = (
        db.query(League)
        .filter(League.is_active == True)
        .order_by(League.name)
        .all()
    )
    return leagues


@router.get("/{league_code}/standings", response_model=StandingsResponse)
def get_standings(
    league_code: str,
    db: Session = Depends(get_db),
):
    """Return current season standings for a league, computed from match results."""
    league = db.query(League).filter(League.code == league_code).first()
    if not league:
        raise HTTPException(status_code=404, detail=f"League '{league_code}' not found")

    # Determine current/latest season for this league
    latest_season_row = (
        db.query(Match.season)
        .filter(
            Match.league_id == league.id,
            Match.status == "completed",
            Match.season != None,
        )
        .order_by(Match.season.desc())
        .first()
    )
    if not latest_season_row:
        return StandingsResponse(
            league_code=league_code,
            league_name=league.name,
            season="N/A",
            standings=[],
        )

    current_season = latest_season_row[0]

    # Fetch all completed matches for this league + season
    matches = (
        db.query(Match)
        .filter(
            Match.league_id == league.id,
            Match.season == current_season,
            Match.status == "completed",
            Match.result != None,
        )
        .all()
    )

    # Aggregate standings per team
    standings_map: dict[int, dict] = {}

    def get_entry(team_id: int) -> dict:
        if team_id not in standings_map:
            standings_map[team_id] = {
                "team_id": team_id,
                "played": 0,
                "won": 0,
                "drawn": 0,
                "lost": 0,
                "goals_for": 0,
                "goals_against": 0,
            }
        return standings_map[team_id]

    for m in matches:
        if m.home_goals is None or m.away_goals is None:
            continue

        home_entry = get_entry(m.home_team_id)
        away_entry = get_entry(m.away_team_id)

        home_entry["played"] += 1
        away_entry["played"] += 1
        home_entry["goals_for"] += m.home_goals
        home_entry["goals_against"] += m.away_goals
        away_entry["goals_for"] += m.away_goals
        away_entry["goals_against"] += m.home_goals

        if m.result == "H":
            home_entry["won"] += 1
            away_entry["lost"] += 1
        elif m.result == "D":
            home_entry["drawn"] += 1
            away_entry["drawn"] += 1
        elif m.result == "A":
            home_entry["lost"] += 1
            away_entry["won"] += 1

    # Load team names in bulk
    team_ids = list(standings_map.keys())
    teams_by_id = {
        t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()
    }

    # Build sorted standings
    entries = []
    for team_id, stats in standings_map.items():
        points = stats["won"] * 3 + stats["drawn"]
        gd = stats["goals_for"] - stats["goals_against"]
        team_name = teams_by_id[team_id].canonical_name if team_id in teams_by_id else f"Team {team_id}"
        entries.append({
            "team_id": team_id,
            "team_name": team_name,
            "points": points,
            "goal_difference": gd,
            "goals_for": stats["goals_for"],
            **stats,
        })

    entries.sort(
        key=lambda e: (e["points"], e["goal_difference"], e["goals_for"]),
        reverse=True,
    )

    standings = [
        StandingsEntry(
            position=i + 1,
            team_id=e["team_id"],
            team_name=e["team_name"],
            played=e["played"],
            won=e["won"],
            drawn=e["drawn"],
            lost=e["lost"],
            goals_for=e["goals_for"],
            goals_against=e["goals_against"],
            goal_difference=e["goal_difference"],
            points=e["points"],
        )
        for i, e in enumerate(entries)
    ]

    return StandingsResponse(
        league_code=league_code,
        league_name=league.name,
        season=current_season,
        standings=standings,
    )
