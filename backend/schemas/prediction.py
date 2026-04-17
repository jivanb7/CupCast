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


class ModelPerformanceResponse(BaseModel):
    overall_accuracy: float
    overall_f1_macro: float
    overall_log_loss: float
    accuracy_by_league: dict[str, float]
    accuracy_by_date: list[DailyAccuracy] = []
    accuracy_last_30_days: Optional[float] = None
    total_predictions: int
    correct_predictions: int
    model_version: str
    last_trained: Optional[str] = None
