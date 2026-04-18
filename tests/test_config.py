"""
tests/test_config.py
=====================
Unit test for backend/config.py. The Settings singleton is small but load-bearing:
every service reads from it. We lock in the two behaviors the rest of the app
actually depends on — a usable default DB URL and the is_production flag.

Note: config.py auto-loads a .env file from the current working directory at
import time. We chdir into a fresh tmp directory before importing so the test
is hermetic regardless of what lives in the repo's .env.
"""

import sys


def test_settings_defaults_and_is_production_flag(monkeypatch, tmp_path):
    # Hermetic: run inside a tmp dir with no .env, drop any cached module, then import.
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("config", None)
    from config import Settings

    s = Settings(_env_file=None)  # explicit: ignore any local .env
    assert s.environment == "dev"
    assert s.database_url  # non-empty default (SQLite fallback)
    assert s.is_production is False

    prod = Settings(_env_file=None, environment="prod")
    assert prod.is_production is True
