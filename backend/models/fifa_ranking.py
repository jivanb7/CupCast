"""
backend/models/fifa_ranking.py
================================
SQLAlchemy ORM model for the fifa_rankings table.

One row per (team, rank_date). The unique constraint ensures no duplicate
entries for the same team on the same date.

rank_date is the first day of the month for each FIFA ranking publication.
"""

from sqlalchemy import Column, Date, Float, ForeignKey, Integer, UniqueConstraint
from database import Base


class FifaRanking(Base):
    __tablename__ = "fifa_rankings"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    rank_date = Column(Date, nullable=False)
    fifa_rank = Column(Integer, nullable=False)
    total_points = Column(Float)

    __table_args__ = (
        UniqueConstraint("team_id", "rank_date", name="uq_fifa_ranking_team_date"),
    )
