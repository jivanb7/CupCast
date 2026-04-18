"""
tests/test_schemas.py
======================
Unit test for backend/schemas/prediction.ValuePickResponse.

Pydantic schemas are the contract between the backend and the frontend. A
missing or mistyped field here breaks every client. This test verifies a
valid payload round-trips and an invalid payload fails loudly.
"""

import pytest
from pydantic import ValidationError

from schemas.prediction import ValuePickResponse


def _valid_payload():
    return {
        "match_id": 42,
        "home_team_name": "Arsenal",
        "away_team_name": "Chelsea",
        "match_date": "2026-04-20",
        "league_name": "Premier League",
        "model_prob_home": 0.55,
        "model_prob_draw": 0.25,
        "model_prob_away": 0.20,
        "bookmaker_prob_home": 0.50,
        "bookmaker_prob_draw": 0.28,
        "bookmaker_prob_away": 0.22,
        "edge_home": 0.05,
        "edge_draw": -0.03,
        "edge_away": -0.02,
        "max_edge": 0.05,
        "value_pick_direction": "H",
        "odds_home": 2.0,
        "odds_draw": 3.5,
        "odds_away": 4.5,
    }


def test_value_pick_response_roundtrips_valid_payload_and_rejects_bad_one():
    # Valid payload → model validates and preserves values
    vp = ValuePickResponse(**_valid_payload())
    assert vp.match_id == 42
    assert vp.value_pick_direction == "H"
    assert vp.max_edge == pytest.approx(0.05)

    # Drop a required field → pydantic raises ValidationError
    bad = _valid_payload()
    del bad["match_id"]
    with pytest.raises(ValidationError):
        ValuePickResponse(**bad)
