"""
backend/database.py
====================
SQLAlchemy engine and session factory setup.

Provides:
  - engine: SQLAlchemy Engine (connected to PostgreSQL or SQLite)
  - SessionLocal: session factory
  - Base: declarative base for ORM models
  - get_db(): FastAPI dependency for database sessions

Connection pool is sized conservatively for Supabase free tier
(50 connection limit — 5 pool_size + 10 max_overflow per service instance
leaves buffer for multiple Cloud Run instances).

For SQLite (local dev), pool args are skipped — SQLite uses StaticPool
and requires check_same_thread=False for FastAPI's threaded request handling.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

_url = settings.database_url

if _url.startswith("sqlite"):
    engine = create_engine(
        _url,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        _url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=settings.db_pool_pre_ping,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    FastAPI dependency: yield a database session, close on exit.

    Usage in route handler:
        @router.get("/foo")
        def get_foo(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
