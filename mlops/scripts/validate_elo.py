"""
Elo predictor validation — temporal hold-out.

Train: all matches BEFORE the earliest hold-out match.
Holdout 1: WC 2022 (FIFA World Cup, year=2022)
Holdout 2: Continental 2024 — UEFA Euro 2024 + Copa América 2024
           (the spec says "Euro 2024 / Copa America 2024 hold-out" — these
           are summer 2024; AFCON & Asian Cup 2024 happen in Jan/Feb 2024
           so they belong to 'training' relative to the summer hold-out.
           To keep a single, clean train cut-off, we set the cut-off at
           the earliest match across BOTH hold-outs (= WC 2022 start)
           and treat any continental match between WC22-start and the
           summer 2024 hold-out as a hold-out gap (excluded entirely from
           train AND eval). This is strictly conservative: no leakage.)

Metrics: accuracy (3-way), Brier, log loss, calibration plot.
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJECT_ROOT = Path("/Users/jivanb/projects/ml-ops-project/saas")
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from services.national_elo import predict_from_elo, update_elo, infer_k  # noqa: E402

INTL_MATCHES_PATH = PROJECT_ROOT / "ml" / "data" / "processed" / "intl_matches.parquet"
INITIAL_ELO = 1500.0
REPORT_DIR = PROJECT_ROOT / "mlops" / "reports"
REPORT_PATH = REPORT_DIR / "elo_validation_2026-04-24_v3.md"
PLOT_PATH = REPORT_DIR / "elo_calibration_2026-04-24_v3.png"


def label_holdout(row) -> str | None:
    """Return holdout bucket name or None if not held out."""
    t = row["tournament"]
    y = row["match_date"].year
    if t == "FIFA World Cup" and y == 2022:
        return "WC2022"
    if y == 2024 and t in ("UEFA Euro", "Copa América"):
        return "EuroCopa2024"
    return None


def main() -> int:
    df = pd.read_parquet(INTL_MATCHES_PATH)
    print(f"Loaded {len(df)} matches")

    df = df.dropna(subset=["home_team", "away_team", "home_goals", "away_goals"]).copy()
    df = df.sort_values("match_date", kind="stable").reset_index(drop=True)

    df["holdout"] = df.apply(label_holdout, axis=1)

    # Hold-out subsets
    hold = df[df["holdout"].notna()].copy()
    print(f"Holdout matches: {len(hold)}")
    print(hold.groupby("holdout").size())

    # Earliest hold-out match defines the train cut-off.
    cutoff = hold["match_date"].min()
    print(f"Train cut-off (strict <): {cutoff.date()}")

    train = df[df["match_date"] < cutoff].copy()
    print(f"Train matches: {len(train)}")

    # Compute Elo over training set only.
    elo: dict[str, float] = defaultdict(lambda: INITIAL_ELO)
    for row in train.itertuples(index=False):
        home, away = row.home_team, row.away_team
        try:
            hg, ag = int(row.home_goals), int(row.away_goals)
        except (TypeError, ValueError):
            continue
        is_neutral = bool(row.is_neutral_venue)
        k = infer_k(row.tournament_type, row.tournament)
        new_h, new_a = update_elo(
            home_elo=elo[home],
            away_elo=elo[away],
            home_goals=hg,
            away_goals=ag,
            k_constant=k,
            is_neutral=is_neutral,
        )
        elo[home] = new_h
        elo[away] = new_a
    print(f"Trained Elo for {len(elo)} teams")

    # Predict on holdout.
    rows = []
    for r in hold.itertuples(index=False):
        try:
            hg, ag = int(r.home_goals), int(r.away_goals)
        except (TypeError, ValueError):
            continue
        h_elo = elo.get(r.home_team, INITIAL_ELO)
        a_elo = elo.get(r.away_team, INITIAL_ELO)
        is_neutral = bool(r.is_neutral_venue)
        p_h, p_d, p_a = predict_from_elo(h_elo, a_elo, is_neutral=is_neutral)

        if hg > ag:
            actual = "H"
            y = (1, 0, 0)
        elif hg < ag:
            actual = "A"
            y = (0, 0, 1)
        else:
            actual = "D"
            y = (0, 1, 0)

        # argmax over (H, D, A)
        probs = (p_h, p_d, p_a)
        labels = ("H", "D", "A")
        pred = labels[int(np.argmax(probs))]

        # Brier = sum over classes of (p - y)^2
        brier = sum((p - yy) ** 2 for p, yy in zip(probs, y))
        # log loss with the actual class
        idx_actual = labels.index(actual)
        p_actual = max(probs[idx_actual], 1e-15)
        ll = -np.log(p_actual)

        rows.append(
            {
                "holdout": r.holdout,
                "tournament": r.tournament,
                "match_date": r.match_date,
                "home_team": r.home_team,
                "away_team": r.away_team,
                "is_neutral": is_neutral,
                "home_elo": h_elo,
                "away_elo": a_elo,
                "p_home": p_h,
                "p_draw": p_d,
                "p_away": p_a,
                "actual": actual,
                "pred": pred,
                "correct": pred == actual,
                "brier": brier,
                "log_loss": ll,
            }
        )

    res = pd.DataFrame(rows)
    print(f"Predictions: {len(res)}")

    # Headline metrics
    def metrics(d: pd.DataFrame) -> dict:
        return {
            "n": len(d),
            "accuracy": d["correct"].mean(),
            "brier": d["brier"].mean(),
            "log_loss": d["log_loss"].mean(),
        }

    overall = metrics(res)
    by_hold = {h: metrics(res[res["holdout"] == h]) for h in res["holdout"].unique()}
    print("Overall:", overall)
    for k, v in by_hold.items():
        print(k, v)

    # Always-pick-home baseline on hold-out for context
    home_baseline_acc = (res["actual"] == "H").mean()
    print(f"Always-home baseline acc on holdout: {home_baseline_acc:.3f}")

    # Per-tournament breakdown
    by_tour = res.groupby("tournament").agg(
        n=("correct", "size"),
        accuracy=("correct", "mean"),
        brier=("brier", "mean"),
        log_loss=("log_loss", "mean"),
    ).round(4)
    print(by_tour)

    # Distribution of predicted classes vs actual
    print("Pred dist:", res["pred"].value_counts(normalize=True).round(3).to_dict())
    print("Actual dist:", res["actual"].value_counts(normalize=True).round(3).to_dict())

    # ---- Calibration ----
    # For each of the three classes (H, D, A), bin predicted probability into
    # 10 equal-width deciles (0-1) and compute observed frequency that the
    # corresponding outcome occurred.
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    bins = np.linspace(0.0, 1.0, 11)
    bin_centers = (bins[:-1] + bins[1:]) / 2

    cal_summary = []
    for ax, cls, p_col in zip(axes, ["H", "D", "A"], ["p_home", "p_draw", "p_away"]):
        p = res[p_col].values
        y = (res["actual"] == cls).astype(int).values
        idx = np.digitize(p, bins, right=True) - 1
        idx = np.clip(idx, 0, 9)

        x_pred = []
        y_obs = []
        counts = []
        for b in range(10):
            mask = idx == b
            if mask.sum() == 0:
                continue
            x_pred.append(p[mask].mean())
            y_obs.append(y[mask].mean())
            counts.append(int(mask.sum()))

        ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="perfect")
        sc = ax.scatter(x_pred, y_obs, s=[max(20, c * 4) for c in counts],
                        alpha=0.7, label="observed")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xlabel(f"Predicted P({cls})")
        ax.set_title(f"Calibration — {cls}  (n bins={len(x_pred)})")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left")
        cal_summary.append((cls, list(zip(x_pred, y_obs, counts))))

    axes[0].set_ylabel("Observed frequency")
    fig.suptitle(f"Elo predictor calibration on hold-out (n={len(res)})", y=1.02)
    fig.tight_layout()
    fig.savefig(PLOT_PATH, dpi=120, bbox_inches="tight")
    print(f"Saved {PLOT_PATH}")

    # Save also a small textual calibration summary for the report.
    cal_text_lines = []
    for cls, pts in cal_summary:
        cal_text_lines.append(f"### Class {cls}")
        cal_text_lines.append("| pred prob (bin mean) | observed freq | n |")
        cal_text_lines.append("|---|---|---|")
        for xp, yo, c in pts:
            cal_text_lines.append(f"| {xp:.3f} | {yo:.3f} | {c} |")
    cal_text = "\n".join(cal_text_lines)

    # Holdout date ranges + sizes
    hold_meta = {}
    for h, g in res.groupby("holdout"):
        hold_meta[h] = (g["match_date"].min().date(), g["match_date"].max().date(), len(g))

    return {
        "overall": overall,
        "by_hold": by_hold,
        "by_tour": by_tour,
        "home_baseline_acc": home_baseline_acc,
        "cal_text": cal_text,
        "hold_meta": hold_meta,
        "cutoff": cutoff,
        "train_n": len(train),
        "pred_dist": res["pred"].value_counts(normalize=True).to_dict(),
        "actual_dist": res["actual"].value_counts(normalize=True).to_dict(),
        "res": res,
    }


if __name__ == "__main__":
    out = main()
    # Persist a small pickle for the report-writing step
    import pickle
    with open("/tmp/elo_validation_results.pkl", "wb") as f:
        pickle.dump({k: v for k, v in out.items() if k != "res"}, f)
    out["res"].to_csv("/tmp/elo_validation_predictions.csv", index=False)
    print("Done.")
