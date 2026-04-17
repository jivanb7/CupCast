"""
backend/models/player.py
========================
SQLAlchemy ORM model for the players table.

Tracks key players per team per season, primarily goal scorers.
Used to compute key_player_availability_home/away features for ML predictions.

Key indexes:
  - (team_id, season) — fetch all players for a team in a given season
  - (team_id, is_key_player) — fetch only key players for a team

is_key_player: True for top 2-3 goal scorers per team (set during data sync).
goal_share: goals / team_total_goals — pre-computed ratio, stored for fast reads.
season format: "2025-26"
"""

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Index, Integer, String, UniqueConstraint
)
from sqlalchemy.sql import func
from database import Base


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True)
    api_football_id = Column(Integer, nullable=False)
    name = Column(String(200), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=True)
    season = Column(String(10), nullable=False)
    position = Column(String(50), nullable=True)
    goals = Column(Integer, default=0)
    team_total_goals = Column(Integer, default=0)
    goal_share = Column(Float, default=0.0)
    is_key_player = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_players_team_season", "team_id", "season"),
        Index("ix_players_team_key", "team_id", "is_key_player"),
        UniqueConstraint("api_football_id", "season", name="uq_players_api_id_season"),
    )
