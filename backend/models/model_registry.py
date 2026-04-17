"""
backend/models/model_registry.py
==================================
SQLAlchemy ORM model for the model_registry table.

Synced with MLFlow but provides the backend a fast local lookup for:
  - Which model version is currently in production
  - What its accuracy metrics were
  - When it was trained

Only one row per model_name should have is_production=True.
This is enforced by the ML pipeline when promoting a new model.
"""

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String
from sqlalchemy.sql import func
from database import Base


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id = Column(Integer, primary_key=True)
    model_name = Column(String(50), nullable=False)   # 'club_model' or 'intl_model'
    model_version = Column(String(50), nullable=False)
    mlflow_run_id = Column(String(50))
    accuracy = Column(Float)
    f1_macro = Column(Float)
    log_loss = Column(Float)
    is_production = Column(Boolean, default=False)
    trained_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
