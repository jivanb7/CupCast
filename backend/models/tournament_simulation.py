"""
backend/models/tournament_simulation.py
========================================
SQLAlchemy ORM model for the tournament_simulations table.

Stores the JSON-serialised output of one Monte Carlo run of the World Cup
tournament simulator (services/tournament_simulator.py). One row per run;
the `/api/v1/world-cup/title-odds` endpoint reads the most recent row.

We persist the JSON blob rather than normalising into per-team rows because:
  - A run is a single atomic snapshot — partial reads make no sense.
  - The result shape evolves as the simulator gains features (path detail,
    upset rates, etc.); JSON keeps the schema flexible for the class project.
  - There are at most a few dozen runs total over the tournament window.
"""

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from database import Base


class TournamentSimulation(Base):
    __tablename__ = "tournament_simulations"

    id = Column(Integer, primary_key=True)
    run_at = Column(DateTime, nullable=False)
    n_sims = Column(Integer, nullable=False)
    result_json = Column(Text, nullable=False)
    model_version = Column(String(30), nullable=False)
    elo_model_version = Column(String(30), nullable=False)
    seed = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_tournament_simulations_run_at", "run_at"),
    )
