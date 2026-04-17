"""
backend/models/team.py
=======================
SQLAlchemy ORM models for teams and team name aliases.

Teams table stores both club teams and national teams.
  team_type: 'club' | 'national'
  confederation: only set for national teams (UEFA, CONMEBOL, CONCACAF, CAF, AFC, OFC)

TeamNameAlias stores source-specific name variants so data ingestion can
resolve any raw name to a canonical team_id. This table is populated by
scripts/seed_database.py and grown over time as new variants are discovered.
"""

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Team(Base):
    __tablename__ = "teams"

    # TODO (database-engineer): implement all columns per schema spec
    id = Column(Integer, primary_key=True)
    canonical_name = Column(String(100), unique=True, nullable=False)
    short_name = Column(String(50))
    team_type = Column(String(20), nullable=False)  # 'club' or 'national'
    league_id = Column(Integer, ForeignKey("leagues.id"))
    country = Column(String(50))
    confederation = Column(String(10))
    logo_url = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())

    aliases = relationship("TeamNameAlias", back_populates="team")


class TeamNameAlias(Base):
    __tablename__ = "team_name_aliases"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    alias = Column(String(100), nullable=False)
    source = Column(String(50), nullable=False)  # 'football_data_uk', 'kaggle_intl', etc.

    team = relationship("Team", back_populates="aliases")
