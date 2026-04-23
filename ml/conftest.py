"""
ml/conftest.py
===============
Ensures the cupcast/ directory is on sys.path so that `from ml.src.xxx import ...`
works correctly when pytest is invoked from the project root.
"""

import sys
from pathlib import Path

# Add cupcast/ to path so `from ml.src.xxx import ...` resolves correctly
# when running `pytest cupcast/` from the project root.
CUPCAST_DIR = Path(__file__).resolve().parent.parent
if str(CUPCAST_DIR) not in sys.path:
    sys.path.insert(0, str(CUPCAST_DIR))
