"""
backend/api/predictions.py
===========================
Route handlers for prediction-specific endpoints.

Endpoints:
  GET /predictions/value-picks
    Query params: league (str, optional), min_edge (float, default=0.08)
    Returns: list[ValuePickResponse]
    Logic: Query predictions where is_value_pick=True AND match status='scheduled'
           AND match_date >= today. Join with matches and filter by league if provided.
           Sort by max(abs(edge)) descending. Apply min_edge filter.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models.league import League
from models.match import Match
from models.prediction import Prediction
from models.team import Team
from schemas.prediction import ValuePickResponse

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("/value-picks", response_model=list[ValuePickResponse])
def get_value_picks(
    league: Optional[str] = Query(None),
    min_edge: float = Query(0.08, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    """Return upcoming matches where the model disagrees with bookmakers."""
    today = date.today()

    # Load match+prediction tuples, then batch-load teams and leagues
    query = (
        db.query(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .filter(
            Prediction.is_value_pick == True,
            Match.status == "scheduled",
            Match.match_date >= today,
            Prediction.edge_home != None,
        )
    )

    if league:
        league_obj = db.query(League).filter(League.code == league).first()
        if not league_obj:
            raise HTTPException(status_code=404, detail=f"League '{league}' not found")
        query = query.filter(Match.league_id == league_obj.id)

    pred_match_pairs: list[tuple[Prediction, Match]] = query.all()

    # Apply min_edge filter
    filtered = []
    for pred, match in pred_match_pairs:
        max_edge = max(
            abs(pred.edge_home or 0),
            abs(pred.edge_draw or 0),
            abs(pred.edge_away or 0),
        )
        if max_edge >= min_edge:
            filtered.append((pred, match, max_edge))

    # Sort by max_edge descending
    filtered.sort(key=lambda x: x[2], reverse=True)

    # Batch load teams and leagues
    team_ids = list({m.home_team_id for _, m, _ in filtered} | {m.away_team_id for _, m, _ in filtered})
    league_ids = list({m.league_id for _, m, _ in filtered if m.league_id})

    teams_by_id = {t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()} if team_ids else {}
    leagues_by_id = {l.id: l for l in db.query(League).filter(League.id.in_(league_ids)).all()} if league_ids else {}

    results = []
    for pred, match, max_edge in filtered:
        home = teams_by_id.get(match.home_team_id)
        away = teams_by_id.get(match.away_team_id)
        league_obj = leagues_by_id.get(match.league_id) if match.league_id else None

        if not home or not away:
            continue

        # Compute bookmaker implied probabilities (de-vigged)
        bm_home, bm_draw, bm_away = 0.0, 0.0, 0.0
        if pred.odds_home and pred.odds_draw and pred.odds_away:
            raw_home = 1.0 / pred.odds_home
            raw_draw = 1.0 / pred.odds_draw
            raw_away = 1.0 / pred.odds_away
            total = raw_home + raw_draw + raw_away
            if total > 0:
                bm_home = round(raw_home / total, 6)
                bm_draw = round(raw_draw / total, 6)
                bm_away = round(raw_away / total, 6)

        results.append(ValuePickResponse(
            match_id=match.id,
            home_team_name=home.canonical_name,
            away_team_name=away.canonical_name,
            match_date=str(match.match_date),
            league_name=league_obj.name if league_obj else "Unknown",
            model_prob_home=round(pred.prob_home_win, 6),
            model_prob_draw=round(pred.prob_draw, 6),
            model_prob_away=round(pred.prob_away_win, 6),
            bookmaker_prob_home=bm_home,
            bookmaker_prob_draw=bm_draw,
            bookmaker_prob_away=bm_away,
            edge_home=round(pred.edge_home or 0.0, 6),
            edge_draw=round(pred.edge_draw or 0.0, 6),
            edge_away=round(pred.edge_away or 0.0, 6),
            max_edge=round(max_edge, 6),
            value_pick_direction=pred.value_pick_direction or "H",
            odds_home=pred.odds_home or 0.0,
            odds_draw=pred.odds_draw or 0.0,
            odds_away=pred.odds_away or 0.0,
        ))

    return results
