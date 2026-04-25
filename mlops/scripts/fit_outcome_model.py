"""
Fit a direct 3-way multinomial logistic for (home_win, draw, away_win)
from elo features.

Why this exists
---------------
v2's piecewise draw model fixed *binary* draw calibration but the v2
report (`mlops/reports/elo_validation_2026-04-24_v2.md`) showed the
multiplicative split

    (p_h, p_d, p_a) = ( (1 - p_d) * E_h, p_d, (1 - p_d) * (1 - E_h) )

is structurally incapable of producing draw-as-argmax in a 3-way split
because draw is argmax iff p_d > 1/3 and the empirical zero-gap draw
rate is ~0.293 < 1/3. The fix is to drop the multiplicative fold and
fit (p_h, p_d, p_a) jointly.

Approach
--------
1. Walk-forward Elo over `intl_matches.parquet` strictly BEFORE the
   validator's cut-off (2022-11-20). Same path used by
   `fit_draw_probability.py` so ratings are identical.
2. For each historical match, capture
       signed_gap = home_elo - away_elo - HFA_offset   (HFA = 100 if not
                                                        neutral else 0)
       is_neutral ∈ {0,1}
       outcome    ∈ {0=home_win, 1=draw, 2=away_win}
3. Fit `LogisticRegression(multi_class='multinomial', solver='lbfgs')`
   on features `[signed_gap, is_neutral, signed_gap * is_neutral]`.
4. Compare against the v2 piecewise table on a temporal CV slice
   (2018-01-01 -> 2022-11-19) using both 3-way Brier and 3-way
   log loss. The piecewise baseline uses the v2 multiplicative split
   to produce 3-way probabilities, exactly as it would in production.
5. Save coefficients to `backend/services/outcome_model_params.json`.

Notes
-----
- We keep the SIGNED gap here (not the absolute value used in v2). The
  multinomial model can learn the home/away asymmetry directly via the
  per-class coefficient on `signed_gap`. Symmetry is a free implicit
  consequence of how H and A classes share the same feature.
- HFA-offset subtraction is the natural way to fold the home advantage
  into a single "team-quality differential" feature so `signed_gap=0`
  means "would be a 50/50 if home were neutral". This matches what
  `_expected_home` already conditions on.
- We do NOT use class_weight='balanced'. Calibrated probabilities are
  the goal here, not minority-class accuracy.
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
PARAMS_PATH = PROJECT_ROOT / "backend" / "services" / "outcome_model_params.json"
PIECEWISE_PARAMS_PATH = PROJECT_ROOT / "backend" / "services" / "draw_model_params.json"

INITIAL_ELO = 1500.0
TRAIN_CUTOFF = pd.Timestamp("2022-11-20")  # strictly < this date
CV_SLICE_START = pd.Timestamp("2018-01-01")  # last ~5y of training data
RNG_SEED = 42


def build_dataset() -> pd.DataFrame:
    """Walk-forward Elo on matches BEFORE the validator's cut-off; collect
    (signed_gap, is_neutral, outcome) for each training match."""
    df = pd.read_parquet(INTL_PATH)
    df = df.dropna(subset=["home_team", "away_team", "home_goals", "away_goals"])
    df = df.sort_values("match_date", kind="stable").reset_index(drop=True)

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
        hfa = 0.0 if is_neutral else float(HOME_FIELD_ADVANTAGE)
        # signed_gap: positive when the (HFA-adjusted) home team is stronger.
        signed_gap = (h_elo - a_elo) - hfa
        if hg > ag:
            outcome = 0
        elif hg == ag:
            outcome = 1
        else:
            outcome = 2
        rows.append(
            {
                "match_date": r.match_date,
                "signed_gap": signed_gap,
                "is_neutral": int(is_neutral),
                "outcome": outcome,
            }
        )
        # Walk Elo forward (uses the SAME `update_elo` the live system uses
        # so ratings here match what production would compute on the same
        # data).
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
    counts = fit_df["outcome"].value_counts(normalize=True).round(3).to_dict()
    print(
        f"Built fit frame: {len(fit_df)} rows, outcome dist (0=H,1=D,2=A): {counts}"
    )
    return fit_df


# ---------------------------------------------------------------------------
# Feature builder + scoring
# ---------------------------------------------------------------------------


def make_X(df: pd.DataFrame) -> np.ndarray:
    g = df["signed_gap"].values.astype(float)
    n = df["is_neutral"].values.astype(float)
    return np.column_stack([g, n, g * n])


def fit_multinomial(train: pd.DataFrame) -> LogisticRegression:
    X = make_X(train)
    y = train["outcome"].values
    clf = LogisticRegression(
        multi_class="multinomial",
        solver="lbfgs",
        max_iter=1000,
        C=1.0,
        random_state=RNG_SEED,
    )
    clf.fit(X, y)
    return clf


def predict_multinomial(clf: LogisticRegression, df: pd.DataFrame) -> np.ndarray:
    """Return a (n, 3) matrix of (p_home, p_draw, p_away) probabilities,
    columns ordered to match clf.classes_ which we expect = [0,1,2]."""
    X = make_X(df)
    proba = clf.predict_proba(X)
    # Reorder to (H,D,A) just in case.
    order = [list(clf.classes_).index(c) for c in (0, 1, 2)]
    return proba[:, order]


# ---------------------------------------------------------------------------
# Piecewise baseline (v2): produces 3-way probs via the multiplicative split.
# We score it here purely so we can quote the head-to-head comparison in the
# v3 report — the production code stops loading this once the multinomial
# is in place.
# ---------------------------------------------------------------------------


def load_piecewise() -> dict:
    with open(PIECEWISE_PARAMS_PATH) as f:
        data = json.load(f)
    edges = [np.inf if e is None else float(e) for e in data["bin_edges"]]
    return {"edges": edges, "table": np.array(data["table"])}


def predict_piecewise_3way(pw: dict, df: pd.DataFrame) -> np.ndarray:
    """Reproduce v2's 3-way prediction: piecewise p_draw + multiplicative split.

    p_draw  = table[bin(|gap_eff|)][is_neutral]
    E_h     = 1 / (1 + 10 ** ((-signed_gap) / 400))
              (signed_gap already has HFA folded in: signed_gap = h-a-hfa,
               so equal-quality non-neutral game has signed_gap = -100 and
               E_h ~ 0.36 — same shape as production.)
    p_h     = (1 - p_draw) * E_h
    p_a     = (1 - p_draw) * (1 - E_h)

    We need |gap_eff|, which equals |signed_gap + hfa| (because the table
    was fit on `abs(home_elo + hfa - away_elo)` while signed_gap subtracts
    hfa). Equivalently abs_gap_eff = abs((h-a-hfa) + hfa) = abs(h-a).
    Hmm — wait, the v2 fit used abs((h+hfa)-a) where the ratings are pre-
    update. So abs_gap_eff = abs(signed_gap + 2*hfa)? No: signed_gap as
    defined here is (h-a)-hfa, while abs_gap_eff used for the table is
    abs((h+hfa)-a) = abs((h-a)+hfa) = abs(signed_gap + 2*hfa). For the
    neutral case hfa=0 so abs_gap_eff = abs(signed_gap). For non-neutral
    case abs_gap_eff = abs(signed_gap + 200). That's an ugly off-by-one
    that exists in v2 too — but here we just want a faithful reproduction
    of v2's behavior so we mirror it exactly.

    Simpler and exactly faithful to v2: compute h_elo - a_elo from
    signed_gap + hfa, then abs_gap_eff = abs((h-a) + hfa_apply) where
    hfa_apply = 0 if neutral else 100. That's `abs(signed_gap + 2*hfa)`
    for non-neutral. We just write it literally below.
    """
    edges = pw["edges"]
    table = pw["table"]
    g = df["signed_gap"].values.astype(float)
    n = df["is_neutral"].values.astype(int)
    # Recover h_elo - a_elo.
    h_minus_a = g + np.where(n == 1, 0.0, 100.0)
    abs_gap_eff = np.abs(h_minus_a + np.where(n == 1, 0.0, 100.0))
    # E_h uses the same effective gap inside the logistic.
    e_h = 1.0 / (1.0 + 10.0 ** ((-h_minus_a - np.where(n == 1, 0.0, 100.0)) / 400.0))
    # ^ this is logistic over `(h_elo - a_elo) + hfa` — same as production.

    # Bin lookup
    bin_idx = np.digitize(abs_gap_eff, edges, right=False) - 1
    bin_idx = np.clip(bin_idx, 0, len(edges) - 2)
    p_d = table[bin_idx, n]
    p_h = (1.0 - p_d) * e_h
    p_a = (1.0 - p_d) * (1.0 - e_h)
    return np.column_stack([p_h, p_d, p_a])


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def brier_3way(probs: np.ndarray, y: np.ndarray) -> float:
    """3-way Brier = mean over rows of sum_k (p_k - 1{y==k})^2."""
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y)), y] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def logloss_3way(probs: np.ndarray, y: np.ndarray) -> float:
    p = probs[np.arange(len(y)), y]
    p = np.clip(p, 1e-15, 1.0)
    return float(-np.mean(np.log(p)))


def main() -> None:
    np.random.seed(RNG_SEED)
    fit_df = build_dataset()

    cv_test = fit_df[fit_df["match_date"] >= CV_SLICE_START].copy()
    cv_train = fit_df[fit_df["match_date"] < CV_SLICE_START].copy()
    print(f"CV train: {len(cv_train)}  CV test: {len(cv_test)}")
    y_cv = cv_test["outcome"].values

    # ---- Multinomial ----
    clf = fit_multinomial(cv_train)
    probs_mn = predict_multinomial(clf, cv_test)
    brier_mn = brier_3way(probs_mn, y_cv)
    ll_mn = logloss_3way(probs_mn, y_cv)
    print(f"Multinomial CV Brier (3-way): {brier_mn:.5f}")
    print(f"Multinomial CV log loss: {ll_mn:.5f}")
    print(f"  classes_={clf.classes_.tolist()}")
    print(f"  coef_=\n{clf.coef_}")
    print(f"  intercept_={clf.intercept_}")

    # ---- Piecewise (v2) baseline ----
    pw = load_piecewise()
    probs_pw = predict_piecewise_3way(pw, cv_test)
    brier_pw = brier_3way(probs_pw, y_cv)
    ll_pw = logloss_3way(probs_pw, y_cv)
    print(f"Piecewise v2 CV Brier (3-way): {brier_pw:.5f}")
    print(f"Piecewise v2 CV log loss: {ll_pw:.5f}")

    # ---- Refit multinomial on full training set ----
    final_clf = fit_multinomial(fit_df)
    print("Final multinomial (refit on full training set):")
    print(f"  classes_={final_clf.classes_.tolist()}")
    print(f"  coef_=\n{final_clf.coef_}")
    print(f"  intercept_={final_clf.intercept_}")

    # ---- Save params ----
    # Save with class order [0,1,2] explicitly so the loader knows what each
    # row of coef_ refers to. sklearn already sorts classes_ ascending but
    # we don't want to depend on that.
    order = [list(final_clf.classes_).index(c) for c in (0, 1, 2)]
    coef_ordered = final_clf.coef_[order].tolist()
    intercept_ordered = final_clf.intercept_[order].tolist()
    out = {
        "coef_": coef_ordered,
        "intercept_": intercept_ordered,
        "classes_": [0, 1, 2],
        "feature_names": ["signed_gap", "is_neutral", "signed_gap_x_is_neutral"],
        "fitted_on_n_matches": int(len(fit_df)),
        "training_cutoff_date": str(TRAIN_CUTOFF.date()),
        "cv_brier_multinomial": brier_mn,
        "cv_logloss_multinomial": ll_mn,
        "cv_brier_piecewise_v2": brier_pw,
        "cv_logloss_piecewise_v2": ll_pw,
    }
    PARAMS_PATH.write_text(json.dumps(out, indent=2))
    print(f"Wrote {PARAMS_PATH}")


if __name__ == "__main__":
    main()
