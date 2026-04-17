"""
backend/models/prediction.py
==============================
SQLAlchemy ORM model for the predictions table.

One row per (match, model_version). The match_id + model_version combination
is unique — re-running predictions for the same match with the same model
version should upsert, not create duplicates.

was_correct is set NULL until the match completes, then set True/False by
the data refresh pipeline after downloading results.

value_pick logic:
  is_value_pick = True when abs(edge_home OR edge_draw OR edge_away) > threshold
  value_pick_direction = the direction ('H', 'D', 'A') with the highest edge
"""

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint
)
from sqlalchemy.sql import func
from database import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    model_version = Column(String(50), nullable=False)
    prob_home_win = Column(Float, nullable=False)
    prob_draw = Column(Float, nullable=False)
    prob_away_win = Column(Float, nullable=False)
    predicted_result = Column(String(1), nullable=False)
    predicted_home_goals = Column(Float)
    predicted_away_goals = Column(Float)
    confidence = Column(Float)
    explanation_text = Column(Text)
    # Bookmaker comparison
    odds_home = Column(Float)
    odds_draw = Column(Float)
    odds_away = Column(Float)
    edge_home = Column(Float)
    edge_draw = Column(Float)
    edge_away = Column(Float)
    is_value_pick = Column(Boolean, default=False)
    value_pick_direction = Column(String(1))
    # Post-match tracking
    was_correct = Column(Boolean)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("match_id", "model_version", name="uq_prediction_match_model"),
        Index("ix_predictions_match_id", "match_id"),
        Index("ix_predictions_is_value_pick", "is_value_pick"),
    )
