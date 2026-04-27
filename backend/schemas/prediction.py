"""
backend/schemas/prediction.py
===============================
Pydantic schemas for prediction-specific endpoints.

ValuePickResponse: one value pick entry
  Fields: match (MatchSummary), model_prob_home/draw/away,
          bookmaker_prob_home/draw/away, edge_home/draw/away,
          max_edge, direction

ModelPerformanceResponse: accuracy metrics for the model performance page
"""

from typing import Optional
from pydantic import BaseModel


class ValuePickResponse(BaseModel):
    match_id: int
    home_team_name: str
    away_team_name: str
    match_date: str
    league_name: str
    model_prob_home: float
    model_prob_draw: float
    model_prob_away: float
    bookmaker_prob_home: float
    bookmaker_prob_draw: float
    bookmaker_prob_away: float
    edge_home: float
    edge_draw: float
    edge_away: float
    max_edge: float
    value_pick_direction: str   # 'H', 'D', or 'A'
    odds_home: float
    odds_draw: float
    odds_away: float


class DailyAccuracy(BaseModel):
    date: str
    correct: int
    wrong: int
    total: int
    accuracy: float


class LeagueWindowDelta(BaseModel):
    """Per-league accuracy in the recent vs prior window plus the signed delta.

    `recent` and `prior` are accuracy fractions (0..1) over the last 7 and the
    7 days before that. `delta_pp` is `(recent - prior) * 100` rounded to one
    decimal so the frontend can render the up/down arrow without re-doing the
    arithmetic. `null` on any field means insufficient sample in that window.
    """
    recent: Optional[float] = None
    prior: Optional[float] = None
    delta_pp: Optional[float] = None
    n_recent: int = 0
    n_prior: int = 0


class BaselineComparison(BaseModel):
    """Reference baselines on the same evaluated set the model is scored on.

    All fields are accuracy fractions (0..1) over the rows that have a
    completed result. ``random`` is the trivial 1/3 floor for a 3-way pick;
    ``naive_home`` is "always predict home team wins"; ``market_implied``
    is the bookmaker's pick (the outcome with the shortest odds), only
    populated for rows where odds_home/draw/away exist.
    """
    random: float = 0.3333
    naive_home: Optional[float] = None
    market_implied: Optional[float] = None
    n_naive_home: int = 0
    n_market: int = 0


class ModelPerformanceResponse(BaseModel):
    overall_accuracy: float
    overall_f1_macro: float
    overall_log_loss: float
    accuracy_by_league: dict[str, float]
    accuracy_by_league_window: dict[str, LeagueWindowDelta] = {}
    accuracy_by_date: list[DailyAccuracy] = []
    accuracy_last_30_days: Optional[float] = None
    total_predictions: int
    correct_predictions: int
    model_version: str
    last_trained: Optional[str] = None
    baselines: BaselineComparison = BaselineComparison()
