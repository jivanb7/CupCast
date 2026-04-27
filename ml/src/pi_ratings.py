"""
ml/src/pi_ratings.py
====================
Constantinou & Fenton pi-rating system.

Each team carries TWO ratings: a home-context skill (`pi_h`) and an
away-context skill (`pi_a`). After every played match between home team H
(playing at home) and away team A (playing away) with score gh-ga:

    expected_goal_diff = pi_h[H] - pi_a[A]
    actual_goal_diff   = gh - ga
    epsilon            = actual - expected
    delta              = sign(epsilon) * log1p(|epsilon|)   # diminishing returns

    # primary update — the rating that was directly tested
    pi_h[H] += LAMBDA * delta
    pi_a[A] -= LAMBDA * delta

    # cross-update — opposite-context rating moves at fraction GAMMA
    pi_a[H] += GAMMA * LAMBDA * delta
    pi_h[A] -= GAMMA * LAMBDA * delta

Hyperparameters (Constantinou's tuned values for football):
    LAMBDA = 0.054
    GAMMA  = 0.30

The features attached to each match are computed BEFORE the match's result
is observed — so there is no leakage. Updates from the match are applied
AFTER the snapshot is taken.

For upcoming dummy rows (`is_upcoming=True`), the snapshot is still taken
(so prediction service gets ratings) but no update is applied (no real result).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

LAMBDA = 0.054
GAMMA = 0.30


def _diminish(epsilon: float) -> float:
    """Diminishing returns on the prediction error to dampen blowouts.

    A 5-0 thrashing should not move ratings 5x as much as a 1-0 win, because
    score margins are noisy in football. log1p preserves sign and converts
    the linear error to ~log scale.
    """
    if epsilon == 0:
        return 0.0
    sign = 1.0 if epsilon > 0 else -1.0
    return sign * np.log1p(abs(epsilon))


def attach_pi_ratings(matches_df: pd.DataFrame) -> pd.DataFrame:
    """
    Walk ``matches_df`` chronologically and attach pi-rating snapshots
    BEFORE each match.

    Returns a frame with columns:
        match_idx
        home_pi_h     # home team's home-context skill BEFORE match
        home_pi_a     # home team's away-context skill BEFORE match
        away_pi_h     # away team's home-context skill BEFORE match
        away_pi_a     # away team's away-context skill BEFORE match
        pi_rating_diff_direct      # home_pi_h - away_pi_a (the matchup pair)
        pi_rating_diff_overall     # mean(home pair) - mean(away pair)

    Input requirements:
      - ``match_idx`` column (caller usually assigns ``np.arange(len(df))``).
      - ``match_date`` for chronological order.
      - ``home_team`` / ``away_team`` strings.
      - ``home_goals`` / ``away_goals`` numeric (NaN OK; row is then skipped
        for updates but still gets a snapshot).
      - Optional ``is_upcoming`` boolean — True rows skipped for updates.
    """
    if "match_idx" not in matches_df.columns:
        raise ValueError("attach_pi_ratings requires a match_idx column on input")

    df = matches_df.copy()
    df = df.sort_values(["match_date", "match_idx"]).reset_index(drop=True)

    n = len(df)
    out_home_h = np.zeros(n)
    out_home_a = np.zeros(n)
    out_away_h = np.zeros(n)
    out_away_a = np.zeros(n)

    ratings: Dict[str, Tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))

    home_team = df["home_team"].values
    away_team = df["away_team"].values
    home_goals = df["home_goals"].values if "home_goals" in df.columns else np.full(n, np.nan)
    away_goals = df["away_goals"].values if "away_goals" in df.columns else np.full(n, np.nan)

    if "is_upcoming" in df.columns:
        is_upcoming = df["is_upcoming"].fillna(False).astype(bool).values
    else:
        is_upcoming = np.zeros(n, dtype=bool)

    for i in range(n):
        h, a = home_team[i], away_team[i]

        h_pi_h, h_pi_a = ratings[h]
        a_pi_h, a_pi_a = ratings[a]

        # Snapshot BEFORE the match — these are the predict-time ratings.
        out_home_h[i] = h_pi_h
        out_home_a[i] = h_pi_a
        out_away_h[i] = a_pi_h
        out_away_a[i] = a_pi_a

        # Skip update for upcoming rows or missing scores.
        if is_upcoming[i]:
            continue
        gh = home_goals[i]
        ga = away_goals[i]
        if pd.isna(gh) or pd.isna(ga):
            continue

        expected_diff = h_pi_h - a_pi_a
        actual_diff = float(gh) - float(ga)
        delta = _diminish(actual_diff - expected_diff)

        primary = LAMBDA * delta
        cross = GAMMA * primary

        # Home team — home rating directly tested, away rating cross-updated
        ratings[h] = (h_pi_h + primary, h_pi_a + cross)
        # Away team — away rating directly tested, home rating cross-updated
        ratings[a] = (a_pi_h - cross, a_pi_a - primary)

    out = pd.DataFrame({
        "match_idx": df["match_idx"].values,
        "home_pi_h": out_home_h,
        "home_pi_a": out_home_a,
        "away_pi_h": out_away_h,
        "away_pi_a": out_away_a,
    })
    out["pi_rating_diff_direct"] = out["home_pi_h"] - out["away_pi_a"]
    out["pi_rating_diff_overall"] = (
        (out["home_pi_h"] + out["home_pi_a"]) / 2.0
        - (out["away_pi_h"] + out["away_pi_a"]) / 2.0
    )

    logger.info(
        "Pi-ratings: computed for %d matches (LAMBDA=%.3f, GAMMA=%.2f)",
        n, LAMBDA, GAMMA,
    )
    return out


# Public column list — kept here so config.py doesn't have to know the
# internal naming scheme.
PI_RATING_FEATURES = [
    "home_pi_h",
    "home_pi_a",
    "away_pi_h",
    "away_pi_a",
    "pi_rating_diff_direct",
    "pi_rating_diff_overall",
]
