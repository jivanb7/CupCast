"""
tests/conftest.py
==================
Shared pytest setup.

1. Adds the backend/ directory to sys.path so tests can import backend modules
   the same way main.py does (e.g. `from config import ...`).
2. Moves CWD out of saas/ before any test imports. config.py auto-loads a
   .env via Pydantic Settings (relative to CWD) at module-load time, and the
   repo's .env currently carries a stale key that would break import. Tests
   should be hermetic, so we side-step it.
"""

import os
import sys
import tempfile
from pathlib import Path

_SAAS_DIR = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _SAAS_DIR / "backend"

for p in (str(_BACKEND_DIR), str(_SAAS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Pin CWD to a tmp dir so no stray .env is auto-loaded by pydantic-settings.
_TMP_CWD = tempfile.mkdtemp(prefix="cupcast-tests-")
os.chdir(_TMP_CWD)
