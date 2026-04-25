"""
backend/models/team_elo.py
===========================
SQLAlchemy ORM model for the team_elo table.

Stores per-team ELO ratings over time, sourced from either historical
backfill or live updates. One row per (team, date, source) triplet.

  source values: 'historical_backfill', 'live_update'
  rating: ELO score as a real number (typically 1000–2000 range)
  as_of_date: the date this rating was current as of

Key indexes (created in Alembic migration):
  - (team_id, as_of_date) — fetch latest rating for a team efficiently
  - UNIQUE (team_id, as_of_date, source) — prevents duplicate inserts
"""

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class TeamElo(Base):
    __tablename__ = "team_elo"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    rating = Column(Float, nullable=False)
    as_of_date = Column(Date, nullable=False)
    source = Column(String(30), nullable=False)  # 'historical_backfill' or 'live_update'
    created_at = Column(DateTime, server_default=func.now())

    team = relationship("Team", back_populates="elo_ratings")

    # Composite index — defined here, created in Alembic migration
    __table_args__ = (
        Index("ix_team_elo_team_date", "team_id", "as_of_date"),
    )
