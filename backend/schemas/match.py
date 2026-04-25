"""
backend/schemas/match.py
=========================
Pydantic response schemas for match-related API endpoints.

MatchSummary: compact representation used in the dashboard match card grid
  Fields: id, match_date, home_team, away_team, league_code,
          home_goals (nullable), away_goals (nullable), result (nullable),
          prediction (nested PredictionSummary or None), status

MatchDetail: full representation used in the match detail page
  All MatchSummary fields + team form stats, H2H history

UpcomingMatchesResponse: list of MatchSummary with metadata
  Fields: matches (list), total, league (filter applied), days_ahead

ResultsResponse: list of completed matches with prediction accuracy
"""

from datetime import date
from typing import Optional
from pydantic import BaseModel


class PredictionSummary(BaseModel):
    prob_home_win: float
    prob_draw: float
    prob_away_win: float
    predicted_result: str
    confidence: float
    is_value_pick: bool
    value_pick_direction: Optional[str] = None
    explanation_text: Optional[str] = None
    was_correct: Optional[bool] = None  # None=not yet played, True/False=after result
    # Bookmaker odds + edge exposed so the dashboard can render a compact
    # H/D/A row next to probabilities on upcoming matches.
    odds_home: Optional[float] = None
    odds_draw: Optional[float] = None
    odds_away: Optional[float] = None
    edge_home: Optional[float] = None
    edge_draw: Optional[float] = None
    edge_away: Optional[float] = None

    model_config = {"from_attributes": True}


class TeamFormStats(BaseModel):
    """Recent form for display on match detail and team pages."""
    team_name: str
    last_5_results: list[str]  # e.g. ['W', 'W', 'D', 'L', 'W']
    goals_scored_avg_5: float
    goals_conceded_avg_5: float
    win_rate_5: float

    model_config = {"from_attributes": True}


class MatchSummary(BaseModel):
    id: int
    match_date: date
    home_team_id: int
    home_team_name: str
    home_team_short_name: Optional[str] = None
    home_team_crest: Optional[str] = None
    home_team_country_code: Optional[str] = None
    away_team_id: int
    away_team_name: str
    away_team_short_name: Optional[str] = None
    away_team_crest: Optional[str] = None
    away_team_country_code: Optional[str] = None
    league_code: str
    league_name: str
    season: Optional[str] = None
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    result: Optional[str] = None
    status: str
    match_minute: Optional[str] = None
    kickoff_time: Optional[str] = None
    tournament: Optional[str] = None
    stage: Optional[str] = None
    group_label: Optional[str] = None
    prediction: Optional[PredictionSummary] = None

    model_config = {"from_attributes": True}


class MatchDetail(MatchSummary):
    """Extended match representation for the detail page."""
    home_shots: Optional[int] = None
    away_shots: Optional[int] = None
    home_shots_on_target: Optional[int] = None
    away_shots_on_target: Optional[int] = None
    home_corners: Optional[int] = None
    away_corners: Optional[int] = None
    home_form: Optional[TeamFormStats] = None
    away_form: Optional[TeamFormStats] = None
    h2h_last_5: list["MatchSummary"] = []

    model_config = {"from_attributes": True}


class UpcomingMatchesResponse(BaseModel):
    matches: list[MatchSummary]
    total: int
    league_filter: Optional[str] = None
    days_ahead: int


class ResultsResponse(BaseModel):
    matches: list[MatchSummary]
    total: int
    prediction_accuracy: Optional[float] = None  # % of predictions that were correct
