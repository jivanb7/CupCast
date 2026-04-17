"""
backend/services/edge_service.py
==================================
Business logic for comparing model predictions to bookmaker odds.

The "edge" concept:
  Bookmakers include a margin (vig/juice) in their odds, so the implied
  probabilities sum to > 100%. We normalize them to sum to exactly 1.0
  before comparing to our model's probabilities.

  edge = model_prob - normalized_implied_prob

  A positive edge means our model thinks the outcome is MORE likely than
  the market does. A large positive edge (> threshold) = "value pick."

Functions:
  compute_edge(prob_home, prob_draw, prob_away, odds_home, odds_draw, odds_away) → EdgeResult
  flag_value_picks(predictions_df, threshold) → predictions_df with is_value_pick column

Used by:
  - ml/src/predict.py (during batch inference)
  - backend/api/predictions.py (GET /predictions/value-picks)
"""

from dataclasses import dataclass
from typing import Optional

# Threshold above which a model-vs-market disagreement is flagged as a value pick.
# Matches ml/src/config.py VALUE_PICK_EDGE_THRESHOLD — kept as a local constant
# to avoid a fragile cross-module import across the backend/ml boundary.
VALUE_PICK_EDGE_THRESHOLD = 0.08


@dataclass
class EdgeResult:
    edge_home: float
    edge_draw: float
    edge_away: float
    max_edge: float
    is_value_pick: bool
    value_pick_direction: Optional[str]  # 'H', 'D', 'A', or None


def compute_edge(
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    odds_home: Optional[float],
    odds_draw: Optional[float],
    odds_away: Optional[float],
    threshold: float = VALUE_PICK_EDGE_THRESHOLD,
) -> Optional[EdgeResult]:
    """
    Compute the edge between model probabilities and bookmaker odds.

    Returns None if any odds are missing or invalid (<= 1.0).

    Steps:
      1. raw_implied = [1/odds_home, 1/odds_draw, 1/odds_away]
      2. total_implied = sum(raw_implied)  (will be > 1.0 due to vig)
      3. normalized = [x / total_implied for x in raw_implied]
      4. edge = model_prob - normalized for each outcome
      5. max_edge = max(abs(edge_home), abs(edge_draw), abs(edge_away))
      6. is_value_pick = max_edge > threshold
      7. value_pick_direction = argmax(edge) if is_value_pick else None
    """
    # Validate all odds are present and meaningful (> 1.0)
    if any(o is None or o <= 1.0 for o in (odds_home, odds_draw, odds_away)):
        return None

    # Step 1: raw implied probabilities
    raw_home = 1.0 / odds_home
    raw_draw = 1.0 / odds_draw
    raw_away = 1.0 / odds_away

    # Step 2: total implied (overround / vig)
    total = raw_home + raw_draw + raw_away

    # Step 3: normalize to remove vig
    norm_home = raw_home / total
    norm_draw = raw_draw / total
    norm_away = raw_away / total

    # Step 4: edge = model probability minus market implied probability
    edge_home = prob_home - norm_home
    edge_draw = prob_draw - norm_draw
    edge_away = prob_away - norm_away

    # Step 5: max absolute edge
    max_edge = max(abs(edge_home), abs(edge_draw), abs(edge_away))

    # Step 6: value pick flag
    is_value_pick = max_edge > threshold

    # Step 7: direction of the largest edge
    if is_value_pick:
        edges = {"H": edge_home, "D": edge_draw, "A": edge_away}
        value_pick_direction = max(edges, key=lambda k: edges[k])
    else:
        value_pick_direction = None

    return EdgeResult(
        edge_home=round(edge_home, 6),
        edge_draw=round(edge_draw, 6),
        edge_away=round(edge_away, 6),
        max_edge=round(max_edge, 6),
        is_value_pick=is_value_pick,
        value_pick_direction=value_pick_direction,
    )
