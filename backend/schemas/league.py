"""
backend/schemas/league.py
==========================
Pydantic schemas for league and standings endpoints.
"""

from typing import Optional
from pydantic import BaseModel


class LeagueResponse(BaseModel):
    id: int
    code: str
    name: str
    country: Optional[str] = None
    season_format: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class StandingsEntry(BaseModel):
    position: int
    team_id: int
    team_name: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int


class StandingsResponse(BaseModel):
    league_code: str
    league_name: str
    season: str
    standings: list[StandingsEntry]
