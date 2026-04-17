"""
backend/models/player_injury.py
================================
SQLAlchemy ORM model for the player_injuries table.

Tracks active and historical injury/suspension records per player.
A player can have multiple records over time; is_active=True means currently out.

Key indexes:
  - (player_id, is_active) — fast lookup: is this player currently unavailable?

injury_type examples: "Knee", "Hamstring", "Ankle", "Suspended"
reason examples: "Muscle Injury", "Suspended", "Illness"
"""

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey,
    Index, Integer, String
)
from sqlalchemy.sql import func
from database import Base


class PlayerInjury(Base):
    __tablename__ = "player_injuries"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    injury_type = Column(String(100), nullable=True)
    reason = Column(String(200), nullable=True)
    start_date = Column(Date, nullable=True)
    expected_return = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_player_injuries_player_active", "player_id", "is_active"),
    )
