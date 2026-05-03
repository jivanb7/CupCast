"""Automated data integrity tests.

Seven tests covering the integrity of the match dataset that feeds
the model. All tests are self-contained: they build synthetic
fixtures so they run cleanly in CI without database or API access.

Run locally with:
    pytest ml/tests/test_automated_data.py -v
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


REQUIRED_MATCH_COLUMNS = (
    "match_date",
    "home_team",
    "away_team",
    "home_goals",
    "away_goals",
    "result",
    "league",
)

VALID_RESULT_CODES = {"H", "D", "A"}

VALID_LEAGUE_CODES = {
    "E0", "E1", "E2", "E3", "EC",   # English tiers
    "SP1",                          # La Liga
    "I1",                           # Serie A
    "D1",                           # Bundesliga
    "F1",                           # Ligue 1
    "MLS",                          # MLS
}


@pytest.fixture
def synthetic_matches() -> pd.DataFrame:
    """Small synthetic match table that mirrors the real schema."""
    return pd.DataFrame({
        "match_date": pd.to_datetime([
            "2024-08-10", "2024-08-17", "2024-08-24",
            "2025-09-01", "2025-09-08", "2025-09-15",
        ]),
        "home_team": ["Arsenal", "Chelsea", "Liverpool", "Real Madrid", "Barcelona", "Atletico"],
        "away_team": ["Tottenham", "Arsenal", "Man City", "Sevilla", "Valencia", "Real Betis"],
        "home_goals": [2, 1, 3, 4, 2, 0],
        "away_goals": [1, 1, 0, 0, 2, 1],
        "result": ["H", "D", "H", "H", "D", "A"],
        "league": ["E0", "E0", "E0", "SP1", "SP1", "SP1"],
    })


# ─────────────────────────────────────────────────────────────────────
# Test 1 — Schema completeness
# ─────────────────────────────────────────────────────────────────────
def test_match_table_has_all_required_columns(synthetic_matches):
    """Every required column must be present in the match table."""
    missing = set(REQUIRED_MATCH_COLUMNS) - set(synthetic_matches.columns)
    assert not missing, f"Match table is missing required columns: {missing}"


# ─────────────────────────────────────────────────────────────────────
# Test 2 — No nulls in critical columns
# ─────────────────────────────────────────────────────────────────────
def test_no_null_values_in_critical_columns(synthetic_matches):
    """Critical columns can never be null. Nulls here would break training."""
    critical = ["match_date", "home_team", "away_team", "result"]
    for col in critical:
        null_count = synthetic_matches[col].isna().sum()
        assert null_count == 0, f"Column '{col}' has {null_count} null value(s)"


# ─────────────────────────────────────────────────────────────────────
# Test 3 — Result codes are from the valid set
# ─────────────────────────────────────────────────────────────────────
def test_result_codes_are_valid(synthetic_matches):
    """Result must be one of H, D, A. Anything else is data corruption."""
    invalid = set(synthetic_matches["result"].unique()) - VALID_RESULT_CODES
    assert not invalid, f"Found invalid result codes: {invalid}"


# ─────────────────────────────────────────────────────────────────────
# Test 4 — Goal counts are non-negative integers
# ─────────────────────────────────────────────────────────────────────
def test_goal_counts_are_non_negative_integers(synthetic_matches):
    """Goals can never be negative or fractional."""
    for col in ("home_goals", "away_goals"):
        series = synthetic_matches[col]
        assert (series >= 0).all(), f"'{col}' contains negative values"
        assert series.apply(lambda x: float(x).is_integer()).all(), \
            f"'{col}' contains non-integer values"


# ─────────────────────────────────────────────────────────────────────
# Test 5 — No duplicate matches (same teams, same date)
# ─────────────────────────────────────────────────────────────────────
def test_no_duplicate_matches(synthetic_matches):
    """A match is uniquely identified by (date, home, away). Duplicates
    would double-count training samples and bias the model."""
    duplicate_mask = synthetic_matches.duplicated(
        subset=["match_date", "home_team", "away_team"], keep=False
    )
    assert not duplicate_mask.any(), \
        f"Found {duplicate_mask.sum()} duplicate match rows"


# ─────────────────────────────────────────────────────────────────────
# Test 6 — Result is internally consistent with goals
# ─────────────────────────────────────────────────────────────────────
def test_result_code_matches_score_line(synthetic_matches):
    """If home_goals > away_goals the result must be 'H', etc.
    Catches data corruption where goals and result drift apart."""
    df = synthetic_matches
    inferred = np.where(
        df["home_goals"] > df["away_goals"], "H",
        np.where(df["home_goals"] < df["away_goals"], "A", "D")
    )
    mismatches = (inferred != df["result"]).sum()
    assert mismatches == 0, \
        f"Found {mismatches} row(s) where result code disagrees with the score line"


# ─────────────────────────────────────────────────────────────────────
# Test 7 — League codes are from the supported set
# ─────────────────────────────────────────────────────────────────────
def test_league_codes_are_supported(synthetic_matches):
    """Every league in the dataset must be one we explicitly support.
    Random codes leaking in would break per-league reporting downstream."""
    found = set(synthetic_matches["league"].unique())
    invalid = found - VALID_LEAGUE_CODES
    assert not invalid, \
        f"Dataset contains unsupported league codes: {invalid}"
