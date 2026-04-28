"""
backend/models/api_football_prediction.py
==========================================
SQLAlchemy ORM model for the api_football_predictions table.

Stores API-Football's own proprietary match win-probability estimates
(home / draw / away percentages) for each fixture. These are ingested as
model features — their internal model already aggregates lineup quality,
xG history, and recent form, so we get all that signal indirectly.

One row per match (unique FK to matches.id). The row is upserted on every
refresh so prob_ columns always reflect the latest API-Football estimate.
raw_payload preserves the full /predictions response for future feature
extraction (goals estimate, advice string, etc.) without requiring another
API call.

fetched_at is server-defaulted on insert but can be refreshed on upsert
by the service layer so we know how stale the estimate is at inference time.
"""

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON
from sqlalchemy.sql import func

from database import Base


class APIFootballPrediction(Base):
    __tablename__ = "api_football_predictions"

    id = Column(Integer, primary_key=True)
    match_id = Column(
        Integer,
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # one prediction row per match
        index=True,
    )
    # Probabilities parsed from API-Football's "percent" block, converted to
    # floats in [0, 1] (e.g. "45%" → 0.45). NULL when the API does not return
    # a percent block for this fixture (rare — happens for postponed fixtures).
    prob_home = Column(Float, nullable=True)
    prob_draw = Column(Float, nullable=True)
    prob_away = Column(Float, nullable=True)
    # Full API-Football /predictions response stored as JSONB for forward
    # compatibility. Feature engineering can later extract goals estimate,
    # advice string, winner prediction, etc. without re-fetching.
    raw_payload = Column(JSON, nullable=True)
    # Wall-clock timestamp of the last successful fetch. Updated on every
    # upsert so staleness is visible at inference time.
    fetched_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # match_id already has index=True above; __table_args__ is defined here
    # only as a hook for future composite indexes.
    __table_args__ = ()
