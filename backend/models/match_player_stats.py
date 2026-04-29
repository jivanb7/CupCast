"""
backend/models/match_player_stats.py
=====================================
Per-match per-player statistics — populated from API-Football's
``/fixtures/players?fixture={id}`` endpoint by
services.match_player_stats_service.

One row per (match, player). Refreshed on the same 5-min cron tick that
pulls team-level stats (services.match_stats_service); the upsert is keyed
on ``UNIQUE (match_id, player_api_football_id)`` so re-running mid-game
just overwrites the running totals.

Why a separate table (vs JSON on matches):
  - Lets the frontend / future ML pipeline query "show me every Bukayo
    Saka match" without scanning a JSON column.
  - Cheap to index, cheap to filter.
  - Schema evolution is a single migration vs a JSON-shape contract.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.orm import relationship

from database import Base


class MatchPlayerStats(Base):
    __tablename__ = "match_player_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)

    match_id = Column(
        Integer,
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)

    # API-Football's stable player ID. We store names denormalised on this
    # row so we don't have to maintain a separate players dimension yet —
    # the player name + photo URL lives on the row for direct read.
    player_api_football_id = Column(Integer, nullable=False)
    player_name = Column(String(255), nullable=False)
    player_photo_url = Column(String(512))

    position = Column(String(8))             # e.g. "F", "M", "D", "G"
    jersey_number = Column(Integer)
    minutes_played = Column(Integer)         # null = unused sub
    rating = Column(Numeric(3, 1))           # API-Football's "7.8" → 7.8

    goals = Column(Integer, default=0, nullable=False)
    assists = Column(Integer, default=0, nullable=False)
    shots_total = Column(Integer, default=0, nullable=False)
    shots_on = Column(Integer, default=0, nullable=False)
    yellow_cards = Column(Integer, default=0, nullable=False)
    red_cards = Column(Integer, default=0, nullable=False)
    is_starter = Column(Boolean, default=False, nullable=False)

    fetched_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "player_api_football_id",
            name="uq_match_player_stats_match_player",
        ),
        Index(
            "ix_match_player_stats_match_id",
            "match_id",
        ),
    )

    match = relationship("Match", backref="player_stats")
    team = relationship("Team")
