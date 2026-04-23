"""
backend/models/league.py
=========================
SQLAlchemy ORM model for the leagues table.

Schema (matches database.py schema in the spec):
  id, code (unique), name, country, season_format, is_active

Seed data (inserted by scripts/seed_database.py):
  epl     → English Premier League (split_year, active)
  championship → English Championship (split_year, active)
  laliga  → La Liga (split_year, active)
  seriea  → Serie A (split_year, active)
  bundesliga → Bundesliga (split_year, active)
  ligue1  → Ligue 1 (split_year, active)
  mls     → MLS (calendar_year, active)
  worldcup → FIFA World Cup (N/A, active)
"""

from sqlalchemy import Boolean, Column, Integer, String
from database import Base


class League(Base):
    __tablename__ = "leagues"

    # TODO (database-engineer): implement all columns per schema spec
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    country = Column(String(50))
    season_format = Column(String(20))  # 'split_year' or 'calendar_year'
    is_active = Column(Boolean, default=True)
