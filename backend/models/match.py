"""
backend/models/match.py
========================
SQLAlchemy ORM model for the matches table.

Stores both completed historical matches (used for feature engineering and
displaying past results) and scheduled upcoming matches (status='scheduled').

Key indexes (must be created in Alembic migration):
  - (match_date, status) — most common API query: upcoming matches in next N days
  - (home_team_id, match_date) — team form lookups
  - (away_team_id, match_date)

status values: 'completed', 'scheduled', 'live'
result values: 'H', 'D', 'A', or NULL if not yet played
match_importance values: 'group', 'knockout', 'qualifier', 'league', 'cup', 'friendly'

Tournament bracket columns (all NULL for non-tournament matches):
  stage: 'group', 'r32', 'r16', 'qf', 'sf', 'final', '3rd-place'
  group_label: 'A'–'L' for WC group stage, NULL otherwise
  bracket_position: knockout slot index (1–32 for R32, etc.)
"""

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey,
    Index, Integer, SmallInteger, String, UniqueConstraint,
)
from sqlalchemy.sql import func
from database import Base


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, ForeignKey("leagues.id"))
    season = Column(String(10))
    match_date = Column(Date, nullable=False)
    home_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    home_goals = Column(Integer)
    away_goals = Column(Integer)
    result = Column(String(1))
    ht_home_goals = Column(Integer)
    ht_away_goals = Column(Integer)
    home_shots = Column(Integer)
    away_shots = Column(Integer)
    home_shots_on_target = Column(Integer)
    away_shots_on_target = Column(Integer)
    home_corners = Column(Integer)
    away_corners = Column(Integer)
    home_fouls = Column(Integer)
    away_fouls = Column(Integer)
    home_yellow_cards = Column(Integer)
    away_yellow_cards = Column(Integer)
    home_red_cards = Column(Integer)
    away_red_cards = Column(Integer)
    kickoff_time = Column(String(10))  # e.g. "15:00", "19:45"
    tournament = Column(String(100))   # legacy free-text field — do not remove
    is_neutral_venue = Column(Boolean, default=False)
    match_importance = Column(String(20))
    status = Column(String(20), default="completed")
    # Tournament bracket columns — NULL for non-tournament matches
    stage = Column(String(20))              # 'group', 'r32', 'r16', 'qf', 'sf', 'final', '3rd-place'
    group_label = Column(String(2))         # 'A'–'L' for WC group stage
    bracket_position = Column(SmallInteger) # knockout slot index (1–32 for R32, etc.)
    created_at = Column(DateTime, server_default=func.now())
    # updated_at: bumped whenever score_updater (or admin revalidation) writes to
    # this row. Used to decide whether a 'completed' match is still inside the
    # 6-hour cross-source re-check window. NULL is treated as "stale" (very old).
    updated_at = Column(DateTime, server_default=func.now())

    # Composite indexes — defined here, created in Alembic migration
    __table_args__ = (
        Index("ix_matches_date_status", "match_date", "status"),
        Index("ix_matches_home_team_date", "home_team_id", "match_date"),
        Index("ix_matches_away_team_date", "away_team_id", "match_date"),
        # One physical fixture per (teams, league, date). Added in migration
        # a3b4c5d6e7f8 alongside a one-shot dedup of 26 historical duplicates.
        UniqueConstraint(
            "home_team_id", "away_team_id", "league_id", "match_date",
            name="uq_match_fixture",
        ),
    )
