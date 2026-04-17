"""
scripts/generate_predictions.py
=================================
Generate ML predictions for all scheduled matches in the database.

Uses the pre-computed feature matrix to build feature vectors quickly,
rather than rebuilding features per-match (which is slow and error-prone).

Strategy:
  For each scheduled match, look up both teams' latest feature values
  from the feature matrix. Combine home_ features from the home team's
  latest appearance and away_ features from the away team's latest
  appearance. H2H features use the pair's last meeting if available,
  otherwise default to zero.

Run:
  cd cupcast
  python scripts/generate_predictions.py

Idempotent: upserts predictions (updates if same match+model_version exists).
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

import joblib
import numpy as np
import pandas as pd

from ml.src.config import INT_TO_RESULT

from database import SessionLocal
from models.match import Match
from models.team import Team
from models.prediction import Prediction


def generate_all_predictions(model_version: str = "v1.0.0") -> int:
    """Generate predictions for all scheduled matches. Returns count generated."""

    model_path = PROJECT_ROOT / "ml" / "models" / "cupcast-club-model_best.joblib"
    features_path = PROJECT_ROOT / "ml" / "data" / "features" / "club_features.parquet"

    if not model_path.exists():
        print(f"ERROR: Model not found at {model_path}")
        print("  Run the training pipeline first: python -m ml.run_pipeline --mode train-only")
        return 0
    if not features_path.exists():
        print(f"ERROR: Features not found at {features_path}")
        print("  Run feature engineering first: python -m ml.run_pipeline --mode data-only")
        return 0

    try:
        model = joblib.load(model_path)
    except Exception as e:
        print(f"ERROR: Failed to load model from {model_path}: {e}")
        return 0

    if not hasattr(model, "feature_names_in_"):
        print("ERROR: Model does not have feature_names_in_ — was it trained with a compatible scikit-learn version?")
        return 0

    feature_names = list(model.feature_names_in_)
    features_df = pd.read_parquet(features_path)

    # Load fixtures for odds data (value pick computation)
    fixtures_path = PROJECT_ROOT / "ml" / "data" / "processed" / "fixtures.parquet"
    fixtures_df = pd.read_parquet(fixtures_path) if fixtures_path.exists() else pd.DataFrame()

    try:
        db = SessionLocal()
        scheduled = db.query(Match).filter(Match.status == "scheduled").all()
        teams_by_id = {t.id: t for t in db.query(Team).all()}
    except Exception as e:
        print(f"ERROR: Database connection failed: {e}")
        return 0

    print(f"Scheduled matches: {len(scheduled)}")
    print(f"Model features: {len(feature_names)}")

    count = 0
    skipped = 0

    for m in scheduled:
        home = teams_by_id.get(m.home_team_id)
        away = teams_by_id.get(m.away_team_id)
        if not home or not away:
            skipped += 1
            continue

        h_name = home.canonical_name
        a_name = away.canonical_name

        # Get each team's latest feature appearance
        home_mask = features_df["home_team"] == h_name
        away_mask = features_df["away_team"] == a_name

        if home_mask.sum() == 0 or away_mask.sum() == 0:
            print(f"  SKIP: {h_name} vs {a_name} — missing feature history")
            skipped += 1
            continue

        home_latest = features_df[home_mask].iloc[-1]
        away_latest = features_df[away_mask].iloc[-1]

        # Check for exact H2H pairing
        pair = features_df[
            (features_df["home_team"] == h_name) & (features_df["away_team"] == a_name)
        ]
        has_h2h = len(pair) > 0
        h2h_latest = pair.iloc[-1] if has_h2h else None

        # Look up this fixture's bookmaker odds from fixtures parquet
        fx_odds = {}
        fx_row = fixtures_df[
            (fixtures_df["home_team"] == h_name) & (fixtures_df["away_team"] == a_name)
        ]
        if len(fx_row) > 0:
            row = fx_row.iloc[0]
            for col in ["odds_home", "odds_draw", "odds_away"]:
                val = row.get(col)
                fx_odds[col] = float(val) if pd.notna(val) else 0.0
            # Compute implied probabilities
            oh, od, oa = fx_odds.get("odds_home", 0), fx_odds.get("odds_draw", 0), fx_odds.get("odds_away", 0)
            if oh > 0 and od > 0 and oa > 0:
                total = (1/oh) + (1/od) + (1/oa)
                fx_odds["implied_prob_home"] = (1/oh) / total
                fx_odds["implied_prob_draw"] = (1/od) / total
                fx_odds["implied_prob_away"] = (1/oa) / total
            else:
                fx_odds["implied_prob_home"] = 1.0/3.0
                fx_odds["implied_prob_draw"] = 1.0/3.0
                fx_odds["implied_prob_away"] = 1.0/3.0

        # Build feature vector in model's expected order
        ODDS_FEATURES = {"odds_home", "odds_draw", "odds_away",
                         "implied_prob_home", "implied_prob_draw", "implied_prob_away"}
        feat_vals = []
        for f in feature_names:
            if f in ODDS_FEATURES:
                # Use this fixture's actual odds, not historical averages
                feat_vals.append(float(fx_odds.get(f, 1.0/3.0 if "implied" in f else 0.0)))
            elif f.startswith("home_"):
                feat_vals.append(float(home_latest.get(f, 0.0)))
            elif f.startswith("away_"):
                feat_vals.append(float(away_latest.get(f, 0.0)))
            elif f.startswith("h2h_"):
                if h2h_latest is not None:
                    feat_vals.append(float(h2h_latest.get(f, 0.0)))
                else:
                    feat_vals.append(0.0)
            elif f == "days_since_last_match_home":
                feat_vals.append(float(home_latest.get(f, 30.0)))
            elif f == "days_since_last_match_away":
                feat_vals.append(float(away_latest.get(f, 30.0)))
            elif f == "is_new_team_home":
                feat_vals.append(float(home_latest.get(f, 0.0)))
            elif f == "is_new_team_away":
                feat_vals.append(float(away_latest.get(f, 0.0)))
            elif f == "rest_advantage":
                h_rest = float(home_latest.get("days_since_last_match_home", 30.0))
                a_rest = float(away_latest.get("days_since_last_match_away", 30.0))
                feat_vals.append(h_rest - a_rest)
            else:
                hv = home_latest.get(f, 0.0)
                av = away_latest.get(f, 0.0)
                hv = float(hv) if pd.notna(hv) else 0.0
                av = float(av) if pd.notna(av) else 0.0
                feat_vals.append((hv + av) / 2)

        X = np.array(feat_vals, dtype=float).reshape(1, -1)
        X = np.nan_to_num(X, nan=0.0)

        probs = model.predict_proba(X)[0]
        pred_class = int(np.argmax(probs))
        predicted_result = INT_TO_RESULT[pred_class]
        confidence = float(probs[pred_class])

        # Compute value pick from bookmaker odds
        is_value_pick = False
        value_pick_direction = None
        edge_home = edge_draw = edge_away = None
        odds_home = odds_draw = odds_away = None

        fx_row = fixtures_df[
            (fixtures_df["home_team"] == h_name) & (fixtures_df["away_team"] == a_name)
        ]
        if len(fx_row) > 0:
            row = fx_row.iloc[0]
            oh, od, oa = row.get("odds_home"), row.get("odds_draw"), row.get("odds_away")
            if pd.notna(oh) and pd.notna(od) and pd.notna(oa):
                from services.edge_service import compute_edge
                edge = compute_edge(float(probs[0]), float(probs[1]), float(probs[2]),
                                    float(oh), float(od), float(oa))
                if edge:
                    edge_home, edge_draw, edge_away = edge.edge_home, edge.edge_draw, edge.edge_away
                    is_value_pick = edge.is_value_pick
                    value_pick_direction = edge.value_pick_direction
                    odds_home, odds_draw, odds_away = float(oh), float(od), float(oa)

        # Upsert
        existing = db.query(Prediction).filter(
            Prediction.match_id == m.id,
            Prediction.model_version == model_version,
        ).first()

        pred_data = dict(
            match_id=m.id,
            model_version=model_version,
            prob_home_win=float(probs[0]),
            prob_draw=float(probs[1]),
            prob_away_win=float(probs[2]),
            predicted_result=predicted_result,
            confidence=confidence,
            is_value_pick=is_value_pick,
            value_pick_direction=value_pick_direction,
            edge_home=edge_home,
            edge_draw=edge_draw,
            edge_away=edge_away,
            odds_home=odds_home,
            odds_draw=odds_draw,
            odds_away=odds_away,
        )

        if existing:
            for k, v in pred_data.items():
                setattr(existing, k, v)
        else:
            db.add(Prediction(**pred_data))
        count += 1

    import time
    max_retries = 3
    for attempt in range(max_retries):
        try:
            db.commit()
            break
        except Exception as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                print(f"  Database locked, retrying ({attempt + 1}/{max_retries})...")
                time.sleep(1)
                continue
            print(f"ERROR: Database commit failed: {e}")
            db.rollback()
            db.close()
            return 0

    db.close()
    print(f"Generated {count} predictions, skipped {skipped}")
    return count


if __name__ == "__main__":
    generate_all_predictions()
