"""
Fit P(draw | |elo_gap|, is_neutral) empirically.

Why this exists
---------------
Validation (mlops/reports/elo_validation_2026-04-24.md) showed the v1
closed-form draw model

    p_draw = max(0.08, 0.28 - |elo_gap| / 1500)

is structurally broken: it caps p_draw at 0.28 so draw is never argmax
in a 3-way split; observed draw rate in the WC22 / Euro24 / Copa24
hold-out was 27.9 % vs 0 % predicted-as-argmax.

Approach
--------
1. Walk-forward Elo over `intl_matches.parquet` strictly BEFORE the
   validator's cut-off (2022-11-20) — same logic as `validate_elo.py`.
   This avoids leaking the WC22 / Copa24 / Euro24 holdouts into the fit.
2. For each training match, capture (|elo_gap|, is_neutral, is_draw)
   where elo_gap = home_elo - away_elo - HFA_offset (HFA=100 for non
   neutral, 0 for neutral).  We use the absolute value of the gap so
   the draw model is symmetric in home/away.
3. Inside that training set, take a temporal CV slice (last ~5 years
   of training data, 2018-01-01 .. 2022-11-19) for evaluating the
   fits. Fit two candidates on data BEFORE that slice and score on
   the slice:
       (a) Logistic regression on [|gap|, is_neutral, |gap|*is_neutral]
       (b) Piecewise lookup table: bin |gap| into fixed bins
           (0-25, 25-50, 50-100, 100-200, 200-300, 300-500, 500+)
           crossed with is_neutral. Smooth with a mild Laplace prior
           (+1 draw, +4 non-draw to each cell).
4. Pick the candidate with lower Brier score for binary draw vs not
   draw on the CV slice. Tie → prefer the table (interpretable, no
   sklearn at predict time).
5. Save selected params to backend/services/draw_model_params.json.

The fitted file is loaded by `national_elo.predict_from_elo` at
import time.

Notes
-----
- Uses the SAME walk-forward Elo update path as validate_elo.py (same
  K-factor mapping via `infer_k`, same HFA = 100, same 1500 init)
  — that's important because the params are calibrated against the
  ratings the live system actually produces.
- We keep the absolute value of the elo_gap because the draw rate
  should not depend on which team is home (only on how mismatched
  they are and whether the venue is neutral).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

PROJECT_ROOT = Path("/Users/jivanb/projects/ml-ops-project/saas")
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from services.national_elo import (  # noqa: E402
    HOME_FIELD_ADVANTAGE,
    infer_k,
    update_elo,
)

INTL_PATH = PROJECT_ROOT / "ml" / "data" / "processed" / "intl_matches.parquet"
PARAMS_PATH = PROJECT_ROOT / "backend" / "services" / "draw_model_params.json"

INITIAL_ELO = 1500.0
TRAIN_CUTOFF = pd.Timestamp("2022-11-20")  # strictly < this date
CV_SLICE_START = pd.Timestamp("2018-01-01")  # last ~5y of training data
RNG_SEED = 42

# Fixed bin edges for the piecewise table on |elo_gap| (Elo points).
# Wide low bins, geometric upward to handle the long tail of mismatches.
BIN_EDGES = [0.0, 25.0, 50.0, 100.0, 200.0, 300.0, 500.0, np.inf]
# Mild Laplace prior so tiny bins do not collapse to 0/1.
PRIOR_DRAW = 1.0
PRIOR_NONDRAW = 4.0  # -> prior mean = 0.20, weak weight (5 effective rows)


def build_dataset() -> pd.DataFrame:
    """Walk-forward Elo on matches BEFORE the validator's cut-off, collect
    (|elo_gap|, is_neutral, is_draw) for each match in a fitting frame."""
    df = pd.read_parquet(INTL_PATH)
    df = df.dropna(subset=["home_team", "away_team", "home_goals", "away_goals"])
    df = df.sort_values("match_date", kind="stable").reset_index(drop=True)

    # All matches strictly before the holdout cut-off.
    train = df[df["match_date"] < TRAIN_CUTOFF].copy()
    print(f"Training matches (< {TRAIN_CUTOFF.date()}): {len(train)}")

    elo: dict[str, float] = defaultdict(lambda: INITIAL_ELO)
    rows = []
    for r in train.itertuples(index=False):
        try:
            hg, ag = int(r.home_goals), int(r.away_goals)
        except (TypeError, ValueError):
            continue
        is_neutral = bool(r.is_neutral_venue)
        h_elo, a_elo = elo[r.home_team], elo[r.away_team]
        # Effective gap: home gets HFA bump if not neutral. Same definition
        # as inside `_expected_home`. We use the absolute value at fit time.
        hfa = 0.0 if is_neutral else float(HOME_FIELD_ADVANTAGE)
        gap = abs((h_elo + hfa) - a_elo)
        # Pre-update snapshot (the prediction-time view) and outcome.
        rows.append(
            {
                "match_date": r.match_date,
                "abs_gap": gap,
                "is_neutral": int(is_neutral),
                "is_draw": int(hg == ag),
            }
        )
        # Walk Elo forward.
        k = infer_k(r.tournament_type, r.tournament)
        new_h, new_a = update_elo(
            home_elo=h_elo,
            away_elo=a_elo,
            home_goals=hg,
            away_goals=ag,
            k_constant=k,
            is_neutral=is_neutral,
        )
        elo[r.home_team] = new_h
        elo[r.away_team] = new_a

    fit_df = pd.DataFrame(rows)
    print(
        f"Built fit frame: {len(fit_df)} rows, "
        f"draw rate = {fit_df['is_draw'].mean():.3f}"
    )
    return fit_df


# ---------------------------------------------------------------------------
# Candidate models
# ---------------------------------------------------------------------------


def fit_logistic(train: pd.DataFrame) -> LogisticRegression:
    """Logistic regression: features = [|gap|, is_neutral, |gap|*is_neutral]."""
    X = np.column_stack(
        [
            train["abs_gap"].values,
            train["is_neutral"].values,
            train["abs_gap"].values * train["is_neutral"].values,
        ]
    )
    y = train["is_draw"].values
    clf = LogisticRegression(
        class_weight="balanced",
        solver="lbfgs",
        max_iter=1000,
        random_state=RNG_SEED,
    )
    clf.fit(X, y)
    return clf


def predict_logistic(clf: LogisticRegression, abs_gap: np.ndarray, is_neutral: np.ndarray) -> np.ndarray:
    X = np.column_stack([abs_gap, is_neutral, abs_gap * is_neutral])
    return clf.predict_proba(X)[:, 1]


def fit_piecewise(train: pd.DataFrame) -> dict:
    """Bin |gap| × is_neutral, store smoothed draw rate per cell."""
    bin_idx = np.digitize(train["abs_gap"].values, BIN_EDGES, right=False) - 1
    bin_idx = np.clip(bin_idx, 0, len(BIN_EDGES) - 2)
    n_bins = len(BIN_EDGES) - 1
    table = np.zeros((n_bins, 2))
    counts = np.zeros((n_bins, 2), dtype=int)
    for b in range(n_bins):
        for n in (0, 1):
            mask = (bin_idx == b) & (train["is_neutral"].values == n)
            d = int(train.loc[mask, "is_draw"].sum())
            tot = int(mask.sum())
            # Laplace-style smoothing.
            p = (d + PRIOR_DRAW) / (tot + PRIOR_DRAW + PRIOR_NONDRAW)
            table[b, n] = p
            counts[b, n] = tot
    return {"bin_edges": BIN_EDGES, "table": table.tolist(), "counts": counts.tolist()}


def predict_piecewise(params: dict, abs_gap: np.ndarray, is_neutral: np.ndarray) -> np.ndarray:
    edges = params["bin_edges"]
    table = np.array(params["table"])
    bin_idx = np.digitize(abs_gap, edges, right=False) - 1
    bin_idx = np.clip(bin_idx, 0, len(edges) - 2)
    return table[bin_idx, is_neutral.astype(int)]


def brier_binary(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def main() -> None:
    np.random.seed(RNG_SEED)
    fit_df = build_dataset()

    # Temporal CV split inside the training data.
    cv_test = fit_df[fit_df["match_date"] >= CV_SLICE_START].copy()
    cv_train = fit_df[fit_df["match_date"] < CV_SLICE_START].copy()
    print(f"CV train: {len(cv_train)}  CV test: {len(cv_test)}")
    print(
        f"CV train draw rate: {cv_train['is_draw'].mean():.3f}  "
        f"CV test draw rate: {cv_test['is_draw'].mean():.3f}"
    )

    # ---- Fit + score logistic ----
    clf = fit_logistic(cv_train)
    p_log = predict_logistic(
        clf, cv_test["abs_gap"].values, cv_test["is_neutral"].values
    )
    brier_log = brier_binary(p_log, cv_test["is_draw"].values)
    print(f"Logistic CV Brier (binary draw): {brier_log:.5f}")
    print(
        f"  coef: {clf.coef_.ravel().tolist()} intercept: {clf.intercept_.tolist()}"
    )

    # ---- Fit + score piecewise ----
    pw = fit_piecewise(cv_train)
    p_pw = predict_piecewise(
        pw, cv_test["abs_gap"].values, cv_test["is_neutral"].values
    )
    brier_pw = brier_binary(p_pw, cv_test["is_draw"].values)
    print(f"Piecewise CV Brier (binary draw): {brier_pw:.5f}")
    print(f"  table (rows = bins {BIN_EDGES}, cols = is_neutral 0/1):")
    for i, (lo, hi) in enumerate(zip(BIN_EDGES[:-1], BIN_EDGES[1:])):
        t = pw["table"][i]
        c = pw["counts"][i]
        print(
            f"    [{lo:>5.0f}, {hi:>5.0f}): non-neutral p={t[0]:.3f} (n={c[0]:>5})  "
            f"neutral p={t[1]:.3f} (n={c[1]:>5})"
        )

    # Tie-break: prefer table (lower complexity, no sklearn at runtime).
    # Use a small epsilon: real ties don't happen with floats but ties to
    # 4 decimals favour the table.
    EPS = 1e-4
    if brier_pw <= brier_log + EPS:
        winner = "piecewise"
    else:
        winner = "logistic"
    print(f"Winner: {winner}")

    # ---- Refit winner on FULL training set, save params ----
    if winner == "piecewise":
        final = fit_piecewise(fit_df)
        out = {
            "model": "piecewise",
            "bin_edges": final["bin_edges"],
            "table": final["table"],
            "counts": final["counts"],
            "cv_brier": brier_pw,
            "cv_brier_alt": brier_log,
            "n_train": int(len(fit_df)),
            "train_cutoff": str(TRAIN_CUTOFF.date()),
            "prior_draw": PRIOR_DRAW,
            "prior_nondraw": PRIOR_NONDRAW,
        }
        # Print final table.
        print("Final piecewise table (refit on full training set):")
        for i, (lo, hi) in enumerate(zip(BIN_EDGES[:-1], BIN_EDGES[1:])):
            t = final["table"][i]
            c = final["counts"][i]
            print(
                f"    [{lo:>5.0f}, {hi:>5.0f}): non-neutral p={t[0]:.3f} (n={c[0]:>5})  "
                f"neutral p={t[1]:.3f} (n={c[1]:>5})"
            )
    else:
        final_clf = fit_logistic(fit_df)
        out = {
            "model": "logistic",
            "coef": final_clf.coef_.ravel().tolist(),
            "intercept": float(final_clf.intercept_[0]),
            "feature_order": ["abs_gap", "is_neutral", "abs_gap_x_is_neutral"],
            "cv_brier": brier_log,
            "cv_brier_alt": brier_pw,
            "n_train": int(len(fit_df)),
            "train_cutoff": str(TRAIN_CUTOFF.date()),
        }

    # Sanity: float infinities don't survive JSON. Replace with a large
    # sentinel that digitize still treats correctly when reloaded.
    if "bin_edges" in out:
        out["bin_edges"] = [
            None if (isinstance(b, float) and np.isinf(b)) else b
            for b in out["bin_edges"]
        ]

    PARAMS_PATH.write_text(json.dumps(out, indent=2))
    print(f"Wrote {PARAMS_PATH}")


if __name__ == "__main__":
    main()
