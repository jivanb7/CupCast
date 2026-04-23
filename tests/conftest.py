"""
tests/conftest.py
==================
Shared pytest setup for saas tests.

- Puts backend/ on sys.path so tests can import backend modules (`from config import ...`).
- Moves CWD to a tmp dir so pydantic-settings does not auto-load a stale repo .env.
- Provides `db` (fresh in-memory SQLite per test) and `client` (TestClient with
  DB dependency overridden) fixtures for integration-style API tests.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

_SAAS_DIR = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _SAAS_DIR / "backend"

for p in (str(_BACKEND_DIR), str(_SAAS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

_TMP_CWD = tempfile.mkdtemp(prefix="cupcast-tests-")
os.chdir(_TMP_CWD)

# Imports below must come AFTER sys.path/CWD setup.
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402

TEST_DATABASE_URL = "sqlite://"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db():
    """Fresh in-memory DB per test."""
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db):
    """TestClient with get_db dependency overridden to use the test session."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
