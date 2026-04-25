"""
backend/models/score_correction.py
====================================
SQLAlchemy ORM model for the score_corrections audit table.

Captures every time a recorded match score was changed after we first marked
it 'completed'. Two write paths populate this:

  1. scripts/revalidate_recent_scores.py — the batch cross-check job that
     compares our DB against API-Football. All corrections from a single
     invocation share a ``run_id`` so they can be grouped after-the-fact.

  2. services/score_updater.py — the 6-hour re-check window that catches
     mismatches as they arrive from the regular score updater (CSV + live API).
     These rows use a ``run_id`` of the form ``score_updater:<iso>``.

Used by:
  - GET /admin/health/scores — counts corrections in last 24 h / 7 d
  - Future Cloud Logging / alert hookups

Index strategy:
  - (match_id) — quickly pull the audit trail for a single match
  - (corrected_at desc) — health endpoint scans recent corrections
"""

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, SmallInteger, String,
)
from sqlalchemy.sql import func

from database import Base


class ScoreCorrection(Base):
    __tablename__ = "score_corrections"

    id = Column(Integer, primary_key=True)
    # NOTE: index defined explicitly in __table_args__ below — using
    # both index=True here AND Index(...) below collides on the same name
    # when SQLAlchemy auto-creates tables in tests.
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    corrected_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Pre-correction snapshot (nullable: a match might never have had a score
    # written before this row, e.g. when score_updater first marks it complete).
    before_home_goals = Column(SmallInteger)
    before_away_goals = Column(SmallInteger)
    before_result = Column(String(1))  # 'H' / 'D' / 'A'

    # Post-correction state (always known when we write this row).
    after_home_goals = Column(SmallInteger, nullable=False)
    after_away_goals = Column(SmallInteger, nullable=False)
    after_result = Column(String(1), nullable=False)

    source = Column(String(40), nullable=False)  # 'api-football', 'football-data-csv', etc.
    predictions_reevaluated = Column(SmallInteger, default=0)
    run_id = Column(String(40), nullable=False)

    __table_args__ = (
        Index("ix_score_corrections_match_id", "match_id"),
        Index("ix_score_corrections_corrected_at", corrected_at.desc()),
    )
