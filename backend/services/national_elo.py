"""
backend/services/national_elo.py
=================================
National-team Elo rating system (pure functions, no DB I/O).

Why this exists
---------------
The current prediction router sends World Cup / international fixtures into
the EPL-trained club model, which silently produces nonsense because the
national teams aren't present in the club training data. As a stop-gap
(and as a useful feature for the eventual intl model), we maintain an Elo
table keyed by team. This module is the math kernel: probability and update
formulas only. Persistence and routing live elsewhere.

Conventions follow World Football Elo (eloratings.net) closely:
  - Logistic win-expectancy on a 400-point scale
  - Home-field advantage of 100 Elo points
  - Goal-difference modifier G on the K-factor
  - K varies with match importance (friendly < qualifier < continental < WC)

The draw model is a v1 closed-form approximation; we'll refit from data
once we have enough live matches scored against this baseline.
"""

import json
import logging
import math
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Draw probability model (v2, piecewise table)
# ---------------------------------------------------------------------------
# Loaded once at import time. Fit by `mlops/scripts/fit_draw_probability.py`
# from international matches strictly BEFORE the validation cut-off
# (2022-11-20), so the WC22 / Euro24 / Copa24 holdouts the validator uses
# remain untouched.
#
# Architecture decision (v2 retained over v3):
#   We tried a v3 direct multinomial logistic on (signed_gap, is_neutral)
#   to escape the multiplicative-fold draw-argmax ceiling. v3 was honestly
#   worse on the holdout (Brier 0.615 vs v2 0.605, log-loss 1.038 vs 1.018).
#   The v3 agent correctly identified that with feature-poor input, draw-
#   as-argmax is mathematically unreachable — in international football
#   the home class dominates the marginal at every gap. The fix needs
#   richer features (form, scoring rate, defensive strength, tournament
#   context) — that's deferred work (task #13: trained intl ML model).
#   Until then v2 is honestly our best calibrated baseline.
#
# Known limitation: predict_from_elo never picks DRAW as the argmax outcome
# given only (signed_gap, is_neutral). Per-class probabilities are
# calibrated and useful for downstream Monte Carlo sampling — sims will
# correctly produce ~28% draws by sampling from p_draw, even though no
# single match will be flagged "draw is most likely" by the picker.

_DRAW_PARAMS_PATH = Path(__file__).with_name("draw_model_params.json")


def _load_draw_params(path: Path) -> dict:
    """Load fitted piecewise draw-probability table from JSON.

    Schema produced by `mlops/scripts/fit_draw_probability.py`:
      - bin_edges: list of |elo_gap| breakpoints, last value None = open-ended
      - table: 2D array, table[bin][is_neutral] -> P(draw)
      - is_neutral index: 0 = home advantaged, 1 = neutral venue
    """
    with open(path) as f:
        data = json.load(f)
    if data.get("model") != "piecewise":
        raise RuntimeError(
            f"draw_model_params.json has unexpected model={data.get('model')!r}; "
            "expected 'piecewise'."
        )
    bin_edges = data["bin_edges"]
    table = np.asarray(data["table"], dtype=float)
    if table.shape[1] != 2:
        raise RuntimeError(
            f"draw_model_params.json table shape={table.shape}; "
            "expected (n_bins, 2) with [home_advantaged, neutral] columns."
        )
    if len(bin_edges) - 1 != table.shape[0]:
        raise RuntimeError(
            f"draw_model_params.json mismatch: {len(bin_edges) - 1} bin gaps "
            f"vs {table.shape[0]} table rows."
        )
    return {"bin_edges": bin_edges, "table": table}


try:
    _DRAW_PARAMS = _load_draw_params(_DRAW_PARAMS_PATH)
except FileNotFoundError as e:
    raise RuntimeError(
        f"Missing draw-model parameters at {_DRAW_PARAMS_PATH}; "
        "run mlops/scripts/fit_draw_probability.py to generate them."
    ) from e

_DRAW_BIN_EDGES = _DRAW_PARAMS["bin_edges"]   # list[float | None]
_DRAW_TABLE = _DRAW_PARAMS["table"]            # shape (n_bins, 2)


def _lookup_draw_prob(abs_gap: float, is_neutral: bool) -> float:
    """Look up P(draw) from the fitted piecewise table.

    abs_gap is bucketed into bins defined by `bin_edges`; the last edge
    being `None` means "anything above the previous edge falls in the
    last bin." `is_neutral` selects column 0 (home advantaged) or 1
    (neutral venue).
    """
    col = 1 if is_neutral else 0
    for i in range(len(_DRAW_BIN_EDGES) - 1):
        upper = _DRAW_BIN_EDGES[i + 1]
        if upper is None or abs_gap < upper:
            return float(_DRAW_TABLE[i, col])
    return float(_DRAW_TABLE[-1, col])

# Home-field advantage in Elo points. Applied to the home team's effective
# rating when computing win expectancy. Matches eloratings.net's HFA.
HOME_FIELD_ADVANTAGE = 100

# Default K-factor for matches we can't classify (e.g. friendlies, missing
# tournament metadata). Aligns with World Football Elo's friendly weighting.
DEFAULT_K = 30


def _expected_home(home_elo: float, away_elo: float, is_neutral: bool) -> float:
    """Logistic expected score for the home team.

    E_h = 1 / (1 + 10 ** ((R_a - R_h - HFA) / 400))

    HFA = 100 when the home team plays at home, 0 on neutral ground.
    """
    hfa = 0 if is_neutral else HOME_FIELD_ADVANTAGE
    return 1.0 / (1.0 + 10.0 ** ((away_elo - home_elo - hfa) / 400.0))


def predict_from_elo(
    home_elo: float, away_elo: float, is_neutral: bool
) -> tuple[float, float, float]:
    """Return (p_home, p_draw, p_away) probabilities that sum to 1.0.

    v2 — piecewise draw table + multiplicative split.

    Step 1: look up P(draw) from a fitted piecewise table keyed by
            (|signed_gap|, is_neutral).
    Step 2: split the remaining 1 - P(draw) between home/away by the
            standard Elo win-expectancy:
                p_home = (1 - p_draw) * E_h
                p_away = (1 - p_draw) * (1 - E_h)
    where signed_gap = home_elo - away_elo - HFA_offset (HFA_offset = 100
    if not is_neutral else 0). The HFA is folded into _expected_home as
    well, so both pieces stay consistent.

    Validated against held-out WC22 + Euro24 + Copa24 (n=147):
        accuracy 51.0%, Brier 0.605, log-loss 1.018.
    See mlops/reports/elo_validation_2026-04-24_v2.md.

    Known limitation: this function never picks DRAW as the argmax
    outcome with only (signed_gap, is_neutral) features — see module
    docstring for why and what's deferred to task #13.
    """
    hfa = 0.0 if is_neutral else float(HOME_FIELD_ADVANTAGE)
    signed_gap = (home_elo - away_elo) - hfa
    p_draw = _lookup_draw_prob(abs(signed_gap), is_neutral)
    e_h = _expected_home(home_elo, away_elo, is_neutral)
    non_draw = 1.0 - p_draw
    p_home = non_draw * e_h
    p_away = non_draw * (1.0 - e_h)

    # Defensive: probabilities should already sum to 1.0; assert the
    # invariant — silent drift here would corrupt downstream calibration.
    total = p_home + p_draw + p_away
    if not math.isfinite(total) or abs(total - 1.0) > 1e-9:
        raise RuntimeError(
            f"predict_from_elo probabilities did not sum to 1.0 "
            f"(got {total}); home={p_home}, draw={p_draw}, away={p_away}"
        )

    return p_home, p_draw, p_away


def _goal_diff_modifier(goal_diff: int) -> float:
    """World Football Elo goal-difference modifier G on the K-factor.

      |gd| == 1  → G = 1.0
      |gd| == 2  → G = 1.5
      |gd| >= 3  → G = (11 + |gd|) / 8

    Scales the rating swing for blowouts so a 5-0 counts more than a 1-0.
    """
    gd = abs(goal_diff)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11.0 + gd) / 8.0


def update_elo(
    home_elo: float,
    away_elo: float,
    home_goals: int,
    away_goals: int,
    k_constant: int,
    is_neutral: bool,
) -> tuple[float, float]:
    """Apply one match to two teams' Elo ratings, World Football Elo style.

    R_h' = R_h + K * G * (S_h - E_h)
    R_a' = R_a + K * G * (S_a - E_a)

    where:
      S_h = 1.0 (home win), 0.5 (draw), 0.0 (home loss)
      E_h = logistic expected score with HFA
      G   = goal-difference modifier (see _goal_diff_modifier)
      K   = importance constant (friendly=30, qualifier=40, continental=50, WC=60)

    Symmetric: the rating points one team gains, the other loses.
    """
    if home_goals > away_goals:
        s_h = 1.0
    elif home_goals < away_goals:
        s_h = 0.0
    else:
        s_h = 0.5

    e_h = _expected_home(home_elo, away_elo, is_neutral)
    g = _goal_diff_modifier(home_goals - away_goals)

    delta = k_constant * g * (s_h - e_h)
    return home_elo + delta, away_elo - delta


# ---------------------------------------------------------------------------
# K-factor inference
# ---------------------------------------------------------------------------

# Tournament-name fragments that classify a match by importance. We match
# against `tournament` (the parquet has both this and a pre-bucketed
# `tournament_type` column) so callers can pass either field.
_WORLD_CUP_KEYS = ("fifa world cup",)
_CONTINENTAL_KEYS = (
    "uefa euro",
    "copa américa",
    "copa america",
    "african cup of nations",
    "afc asian cup",
    "concacaf nations league",  # treated as continental, not friendly
    "uefa nations league",
    "gold cup",
    "copa libertadores",
)
_QUALIFIER_KEYS = ("qualification", "qualifier")


def infer_k(match_importance: str | None, tournament: str | None) -> int:
    """Map tournament metadata onto a K-factor.

    K values follow the standard World Football Elo brackets:
      60  — World Cup finals
      50  — major continental finals (Euros, Copa America, AFCON, Asian Cup,
            Nations Leagues)
      40  — qualifiers (any "qualification"/"qualifier" tournament)
      30  — friendlies / unknown (default)

    `match_importance` is checked first when provided (caller may have
    explicit data); otherwise we substring-match on `tournament`. Both args
    are optional — `infer_k(None, None)` yields the default 30.
    """
    # Prefer explicit importance bucket (parquet's `tournament_type`).
    if match_importance:
        m = match_importance.strip().lower()
        if m == "world_cup":
            return 60
        if m == "continental":
            return 50
        if m == "qualifier":
            return 40
        if m in {"friendly", "competitive"}:
            # `competitive` in the dataset bundles minor non-qualifier comps
            # (e.g. CECAFA Cup, Gulf Cup, Island Games). Treat as friendly
            # weight — bumping these to 40 would inflate ratings for teams
            # that mostly play regional cups.
            return 30

    if tournament:
        t = tournament.strip().lower()
        if any(k in t for k in _WORLD_CUP_KEYS) and "qualification" not in t:
            return 60
        if any(k in t for k in _QUALIFIER_KEYS):
            return 40
        if any(k in t for k in _CONTINENTAL_KEYS):
            return 50

    return DEFAULT_K


# ---------------------------------------------------------------------------
# Smoke checks for the empirical draw model.
# Run as `python -m backend.services.national_elo` from project root.
# These are sanity guards on the structural fix — not a unit-test suite.
# ---------------------------------------------------------------------------


def _smoke_check() -> None:
    """Verify the fitted multinomial behaves sensibly at known anchors."""
    # 1) Equal teams on neutral ground: should sit near the empirical
    # marginal (~0.36/0.30/0.34 H/D/A range). signed_gap=0, is_neutral=1.
    p_h, p_d, p_a = predict_from_elo(1500.0, 1500.0, is_neutral=True)
    assert abs(p_h + p_d + p_a - 1.0) < 1e-9, "probs must sum to 1"
    assert 0.30 <= p_h <= 0.45, f"equal-neutral p_home out of range: {p_h:.3f}"
    assert 0.20 <= p_d <= 0.35, f"equal-neutral p_draw out of range: {p_d:.3f}"
    assert 0.25 <= p_a <= 0.40, f"equal-neutral p_away out of range: {p_a:.3f}"
    print(f"  equal-neutral: H={p_h:.3f} D={p_d:.3f} A={p_a:.3f}")

    # 2) +400 Elo home, neutral: home strongly favoured, draw small but
    # non-zero, away tiny.
    p_h, p_d, p_a = predict_from_elo(1900.0, 1500.0, is_neutral=True)
    assert p_h > 0.65, f"+400 neutral p_home too low: {p_h:.3f}"
    assert 0.0 < p_d < 0.25, f"+400 neutral p_draw out of range: {p_d:.3f}"
    assert p_a < p_d, f"+400 neutral p_away >= p_draw: {p_a:.3f} vs {p_d:.3f}"
    print(f"  +400 neutral:  H={p_h:.3f} D={p_d:.3f} A={p_a:.3f}")

    # 3) Equal teams non-neutral: HFA active, signed_gap = -100. Home
    # should be slight favourite over away.
    p_h, p_d, p_a = predict_from_elo(1500.0, 1500.0, is_neutral=False)
    assert p_h > p_a, "home should beat away when teams equal & not neutral"
    assert 0.20 <= p_d <= 0.35, f"equal-home p_draw out of range: {p_d:.3f}"
    print(f"  equal-home:    H={p_h:.3f} D={p_d:.3f} A={p_a:.3f}")

    print("national_elo smoke checks passed.")


if __name__ == "__main__":
    _smoke_check()
