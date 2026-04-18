"""
tests/test_edge_service.py
===========================
Unit tests for backend/services/edge_service.compute_edge.

compute_edge is pure math: it converts bookmaker odds → implied probs,
removes the vig, and returns the (model - market) edge per outcome plus
a value-pick flag. These tests lock in that behavior.
"""

import pytest
from services.edge_service import (
    compute_edge,
    VALUE_PICK_EDGE_THRESHOLD,
)


def test_compute_edge_returns_none_for_invalid_odds():
    """Odds <= 1.0 or None are invalid; compute_edge must bail out with None."""
    assert compute_edge(0.5, 0.3, 0.2, None, 3.5, 4.0) is None
    assert compute_edge(0.5, 0.3, 0.2, 1.0, 3.5, 4.0) is None
    assert compute_edge(0.5, 0.3, 0.2, 2.0, 0.9, 4.0) is None


def test_compute_edge_removes_vig_so_edges_sum_to_zero():
    """
    When model probs sum to 1 and odds are normalized to 1, edges must also
    sum to ~0 (positive edge on one outcome = negative on others). This is the
    core invariant that proves the vig was removed correctly.
    """
    result = compute_edge(
        prob_home=0.50, prob_draw=0.30, prob_away=0.20,
        odds_home=2.0, odds_draw=3.5, odds_away=4.5,
    )
    assert result is not None
    total = result.edge_home + result.edge_draw + result.edge_away
    assert abs(total) < 1e-5, f"edges should sum to 0, got {total}"


def test_compute_edge_no_value_pick_when_model_matches_market():
    """Model aligned with normalized market implied probs → no value pick."""
    # Odds 2.0 / 3.0 / 6.0 → raw implied 0.5/0.333/0.167, total 1.0 → already vig-free
    result = compute_edge(0.5, 0.3333, 0.1667, 2.0, 3.0, 6.0)
    assert result is not None
    assert result.is_value_pick is False
    assert result.value_pick_direction is None


def test_compute_edge_flags_value_pick_on_correct_direction():
    """
    Model strongly disagrees with market on the home side: model says 0.70,
    market implies ~0.50. Edge ≈ +0.20 on home → flagged, direction 'H'.
    """
    result = compute_edge(
        prob_home=0.70, prob_draw=0.20, prob_away=0.10,
        odds_home=2.0, odds_draw=3.5, odds_away=4.5,
    )
    assert result is not None
    assert result.is_value_pick is True
    assert result.value_pick_direction == "H"
    assert result.edge_home > VALUE_PICK_EDGE_THRESHOLD


def test_compute_edge_threshold_is_strict_inequality():
    """
    The value-pick check is `max_edge > threshold` (strict). An edge that
    equals the threshold exactly must NOT be flagged. This guards the boundary.
    """
    # Craft probs so max_edge is clearly below the strict threshold.
    # Model differs from market by ~VALUE_PICK_EDGE_THRESHOLD - 0.01.
    # With odds 2/3/6 → market = 0.5/0.333/0.167
    delta = VALUE_PICK_EDGE_THRESHOLD - 0.01
    result = compute_edge(
        prob_home=0.5 + delta,
        prob_draw=0.3333 - delta / 2,
        prob_away=0.1667 - delta / 2,
        odds_home=2.0, odds_draw=3.0, odds_away=6.0,
    )
    assert result is not None
    assert result.max_edge <= VALUE_PICK_EDGE_THRESHOLD
    assert result.is_value_pick is False
