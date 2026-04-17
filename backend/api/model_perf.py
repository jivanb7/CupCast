"""
backend/api/model_perf.py
==========================
Route handlers for model performance / transparency endpoints.

Endpoints:
  GET /model/performance
    Returns: ModelPerformanceResponse with accuracy metrics, model version,
             accuracy by league, accuracy last 30 days.
    Logic: Query predictions where was_correct IS NOT NULL (i.e., match completed).
           Aggregate accuracy overall and by league.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.league import League
from models.match import Match
from models.model_registry import ModelRegistry
from models.prediction import Prediction
from schemas.prediction import ModelPerformanceResponse

from sqlalchemy import or_

router = APIRouter(prefix="/model", tags=["model"])


@router.get("/performance", response_model=ModelPerformanceResponse)
def get_model_performance(db: Session = Depends(get_db)):
    """Return model accuracy statistics for the transparency/performance page."""

    # Get production model info from model_registry
    prod_model = (
        db.query(ModelRegistry)
        .filter(
            ModelRegistry.is_production == True,
            ModelRegistry.model_name == "club_model",
        )
        .order_by(ModelRegistry.trained_at.desc())
        .first()
    )

    model_version = prod_model.model_version if prod_model else "v0.1.0-dev"
    last_trained = prod_model.trained_at.isoformat() if (prod_model and prod_model.trained_at) else None

    # Get all evaluated predictions (where was_correct is not null)
    evaluated_preds = (
        db.query(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .filter(Prediction.was_correct != None)
        .all()
    )

    total = len(evaluated_preds)
    correct = sum(1 for p, _ in evaluated_preds if p.was_correct)
    overall_accuracy = round(correct / total, 4) if total > 0 else 0.0

    # Compute F1 macro and log-loss live from production predictions
    f1_macro = 0.0
    log_loss_val = 0.0
    if total > 0:
        import math
        # Build actual vs predicted lists for F1 macro
        actuals = []
        predicteds = []
        for pred, match in evaluated_preds:
            if match.result:
                actuals.append(match.result)
                predicteds.append(pred.predicted_result)

        if actuals:
            # F1 macro: compute per-class F1 then average
            classes = ["H", "D", "A"]
            f1_scores = []
            for cls in classes:
                tp = sum(1 for a, p in zip(actuals, predicteds) if a == cls and p == cls)
                fp = sum(1 for a, p in zip(actuals, predicteds) if a != cls and p == cls)
                fn = sum(1 for a, p in zip(actuals, predicteds) if a == cls and p != cls)
                precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
                f1_scores.append(f1)
            f1_macro = round(sum(f1_scores) / len(f1_scores), 4)

            # Log-loss: -1/N * sum(log(predicted probability of actual outcome))
            eps = 1e-15
            log_loss_sum = 0.0
            for pred, match in evaluated_preds:
                if not match.result:
                    continue
                prob_map = {"H": pred.prob_home_win, "D": pred.prob_draw, "A": pred.prob_away_win}
                prob_actual = max(min(prob_map.get(match.result, 1 / 3), 1 - eps), eps)
                log_loss_sum -= math.log(prob_actual)
            log_loss_val = round(log_loss_sum / len(actuals), 4)

    # Accuracy by league
    league_stats: dict[str, dict] = {}
    league_ids = {m.league_id for _, m in evaluated_preds if m.league_id}
    leagues_by_id = (
        {l.id: l for l in db.query(League).filter(League.id.in_(league_ids)).all()}
        if league_ids else {}
    )

    for pred, match in evaluated_preds:
        if not match.league_id:
            continue
        league_obj = leagues_by_id.get(match.league_id)
        if not league_obj:
            continue
        code = league_obj.code
        if code not in league_stats:
            league_stats[code] = {"correct": 0, "total": 0}
        league_stats[code]["total"] += 1
        if pred.was_correct:
            league_stats[code]["correct"] += 1

    accuracy_by_league = {
        code: round(stats["correct"] / stats["total"], 4)
        for code, stats in league_stats.items()
        if stats["total"] > 0
    }

    # Daily accuracy breakdown (for day-by-day chart)
    daily_stats: dict[str, dict] = {}
    for pred, match in evaluated_preds:
        day = str(match.match_date)
        if day not in daily_stats:
            daily_stats[day] = {"correct": 0, "wrong": 0, "total": 0}
        daily_stats[day]["total"] += 1
        if pred.was_correct:
            daily_stats[day]["correct"] += 1
        else:
            daily_stats[day]["wrong"] += 1

    from schemas.prediction import DailyAccuracy
    accuracy_by_date = sorted([
        DailyAccuracy(
            date=day,
            correct=s["correct"],
            wrong=s["wrong"],
            total=s["total"],
            accuracy=round(s["correct"] / s["total"], 4) if s["total"] > 0 else 0.0,
        )
        for day, s in daily_stats.items()
    ], key=lambda x: x.date)

    # Accuracy last 30 days
    cutoff = date.today() - timedelta(days=30)
    recent_preds = [
        (p, m) for p, m in evaluated_preds if m.match_date >= cutoff
    ]
    if recent_preds:
        recent_correct = sum(1 for p, _ in recent_preds if p.was_correct)
        accuracy_last_30 = round(recent_correct / len(recent_preds), 4)
    else:
        accuracy_last_30 = None

    return ModelPerformanceResponse(
        overall_accuracy=overall_accuracy,
        overall_f1_macro=f1_macro,
        overall_log_loss=log_loss_val,
        accuracy_by_league=accuracy_by_league,
        accuracy_by_date=accuracy_by_date,
        accuracy_last_30_days=accuracy_last_30,
        total_predictions=total,
        correct_predictions=correct,
        model_version=model_version,
        last_trained=last_trained,
    )


@router.get("/performance/daily/{match_date}")
def get_daily_predictions(match_date: str, db: Session = Depends(get_db)):
    """Return individual match predictions for a specific date with correct/wrong status."""
    from models.team import Team

    try:
        target_date = date.fromisoformat(match_date)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    # Get all evaluated predictions for this date
    results = (
        db.query(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .filter(
            Match.match_date == target_date,
            Prediction.was_correct != None,
        )
        .all()
    )

    team_ids = set()
    league_ids = set()
    for p, m in results:
        team_ids.update([m.home_team_id, m.away_team_id])
        if m.league_id:
            league_ids.add(m.league_id)

    teams_by_id = {t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()} if team_ids else {}
    leagues_by_id = {l.id: l for l in db.query(League).filter(League.id.in_(league_ids)).all()} if league_ids else {}

    matches_out = []
    for pred, match in results:
        home = teams_by_id.get(match.home_team_id)
        away = teams_by_id.get(match.away_team_id)
        league = leagues_by_id.get(match.league_id) if match.league_id else None

        matches_out.append({
            "match_id": match.id,
            "home_team": home.canonical_name if home else "?",
            "away_team": away.canonical_name if away else "?",
            "league": league.name if league else "Unknown",
            "home_goals": match.home_goals,
            "away_goals": match.away_goals,
            "result": match.result,
            "predicted_result": pred.predicted_result,
            "was_correct": pred.was_correct,
            "confidence": pred.confidence,
            "prob_home": pred.prob_home_win,
            "prob_draw": pred.prob_draw,
            "prob_away": pred.prob_away_win,
        })

    correct = sum(1 for m in matches_out if m["was_correct"])
    total = len(matches_out)

    return {
        "date": match_date,
        "total": total,
        "correct": correct,
        "wrong": total - correct,
        "accuracy": round(correct / total, 4) if total > 0 else 0.0,
        "matches": matches_out,
    }
