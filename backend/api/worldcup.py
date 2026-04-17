"""
backend/api/worldcup.py
========================
Route handlers for World Cup 2026 hub endpoints.

Endpoints:
  GET /worldcup/groups
    Returns: all 12 group tables with teams, current standings (points/GD/GF/GA),
             and prediction for each remaining group stage match.

  GET /worldcup/bracket
    Returns: knockout stage bracket. Before tournament starts, shows predicted
             bracket based on group stage predictions. During tournament, shows
             actual results for completed rounds + predictions for remaining.

  GET /worldcup/winner-odds
    Returns: list of all 48 teams sorted by predicted probability of winning
             the tournament (computed from FIFA ranking points).
"""

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.fifa_ranking import FifaRanking
from models.match import Match
from models.team import Team

# Import WC group assignments from ml config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "ml"))
try:
    from src.config import WORLD_CUP_2026_GROUPS
except ImportError:
    WORLD_CUP_2026_GROUPS = {}

router = APIRouter(prefix="/worldcup", tags=["worldcup"])

# Confederation for each WC team (for display)
CONFEDERATION_MAP = {
    "Mexico": "CONCACAF", "South Africa": "CAF", "South Korea": "AFC",
    "Czech Republic": "UEFA", "Canada": "CONCACAF",
    "Bosnia and Herzegovina": "UEFA", "Qatar": "AFC", "Switzerland": "UEFA",
    "Brazil": "CONMEBOL", "Morocco": "CAF", "Haiti": "CONCACAF",
    "Scotland": "UEFA", "United States": "CONCACAF", "Paraguay": "CONMEBOL",
    "Australia": "AFC", "Turkey": "UEFA", "Germany": "UEFA",
    "Curaçao": "CONCACAF", "Côte d'Ivoire": "CAF", "Ecuador": "CONMEBOL",
    "Netherlands": "UEFA", "Japan": "AFC", "Sweden": "UEFA", "Tunisia": "CAF",
    "Belgium": "UEFA", "Egypt": "CAF", "Iran": "AFC", "New Zealand": "OFC",
    "Spain": "UEFA", "Cape Verde Islands": "CAF", "Saudi Arabia": "AFC",
    "Uruguay": "CONMEBOL", "France": "UEFA", "Senegal": "CAF", "Iraq": "AFC",
    "Norway": "UEFA", "Argentina": "CONMEBOL", "Algeria": "CAF",
    "Austria": "UEFA", "Jordan": "AFC", "Portugal": "UEFA",
    "Democratic Republic of Congo": "CAF", "Uzbekistan": "AFC",
    "Colombia": "CONMEBOL", "England": "UEFA", "Croatia": "UEFA",
    "Ghana": "CAF", "Panama": "CONCACAF",
}


@router.get("/groups")
def get_groups(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return all 12 group tables with predictions for remaining matches."""
    if not WORLD_CUP_2026_GROUPS:
        return {"error": "World Cup group data not available", "groups": {}}

    # Build team name → id map for national teams
    national_teams = db.query(Team).filter(Team.team_type == "national").all()
    team_by_name = {t.canonical_name: t for t in national_teams}

    groups_data: dict[str, Any] = {}

    for group_letter, team_names in WORLD_CUP_2026_GROUPS.items():
        # Get team IDs for this group
        group_teams = [team_by_name.get(name) for name in team_names]
        group_team_ids = [t.id for t in group_teams if t]

        # Get completed matches within this group
        # (matches where both teams are in the group and tournament='FIFA World Cup')
        completed_matches = (
            db.query(Match)
            .filter(
                Match.status == "completed",
                Match.home_team_id.in_(group_team_ids),
                Match.away_team_id.in_(group_team_ids),
                Match.tournament == "FIFA World Cup",
            )
            .all()
        ) if group_team_ids else []

        # Compute standings
        standings = {name: {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Pts": 0}
                     for name in team_names}

        team_id_to_name = {t.id: n for n, t in team_by_name.items() if t and n in team_names}

        for m in completed_matches:
            if m.home_goals is None or m.away_goals is None:
                continue
            home_name = team_id_to_name.get(m.home_team_id)
            away_name = team_id_to_name.get(m.away_team_id)
            if not home_name or not away_name:
                continue

            standings[home_name]["P"] += 1
            standings[away_name]["P"] += 1
            standings[home_name]["GF"] += m.home_goals
            standings[home_name]["GA"] += m.away_goals
            standings[away_name]["GF"] += m.away_goals
            standings[away_name]["GA"] += m.home_goals

            if m.result == "H":
                standings[home_name]["W"] += 1
                standings[away_name]["L"] += 1
                standings[home_name]["Pts"] += 3
            elif m.result == "D":
                standings[home_name]["D"] += 1
                standings[away_name]["D"] += 1
                standings[home_name]["Pts"] += 1
                standings[away_name]["Pts"] += 1
            elif m.result == "A":
                standings[away_name]["W"] += 1
                standings[home_name]["L"] += 1
                standings[away_name]["Pts"] += 3

        # Sort by points, then GD, then GF
        sorted_standings = sorted(
            [
                {
                    "team": name,
                    "confederation": CONFEDERATION_MAP.get(name, ""),
                    "played": s["P"],
                    "won": s["W"],
                    "drawn": s["D"],
                    "lost": s["L"],
                    "goals_for": s["GF"],
                    "goals_against": s["GA"],
                    "goal_difference": s["GF"] - s["GA"],
                    "points": s["Pts"],
                }
                for name, s in standings.items()
            ],
            key=lambda x: (x["points"], x["goal_difference"], x["goals_for"]),
            reverse=True,
        )

        groups_data[group_letter] = {
            "group": group_letter,
            "teams": team_names,
            "standings": sorted_standings,
            "matches_played": len(completed_matches),
        }

    return {"groups": groups_data, "total_groups": len(groups_data)}


@router.get("/bracket")
def get_bracket(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return knockout stage bracket with predictions.

    MVP: Static predicted bracket based on top-ranked teams advancing from groups.
    This becomes dynamic once the tournament starts and group results come in.
    """
    if not WORLD_CUP_2026_GROUPS:
        return {"error": "World Cup group data not available"}

    # Build team name → id map for national teams
    national_teams = db.query(Team).filter(Team.team_type == "national").all()
    team_by_name = {t.canonical_name: t for t in national_teams}

    # Get most recent FIFA ranking for each team (proxy for strength)
    team_ids = [t.id for t in national_teams if t.id]
    latest_rankings: dict[int, int] = {}

    if team_ids:
        all_rankings = (
            db.query(FifaRanking)
            .filter(FifaRanking.team_id.in_(team_ids))
            .order_by(FifaRanking.rank_date.desc())
            .all()
        )
        latest_by_team: dict[int, FifaRanking] = {}
        for r in all_rankings:
            if r.team_id not in latest_by_team:
                latest_by_team[r.team_id] = r
        latest_rankings = {team_id: r.fifa_rank for team_id, r in latest_by_team.items()}

    # Predict group winners and runners-up based on FIFA ranking (lower rank = better)
    bracket: dict[str, Any] = {"round_of_32": [], "note": "Static prediction based on FIFA rankings"}

    for group_letter, team_names in WORLD_CUP_2026_GROUPS.items():
        ranked = sorted(
            team_names,
            key=lambda name: latest_rankings.get(
                team_by_name[name].id if name in team_by_name and team_by_name[name] else 999,
                999
            ),
        )
        winner = ranked[0] if ranked else team_names[0]
        runner_up = ranked[1] if len(ranked) > 1 else team_names[1] if len(team_names) > 1 else ""

        bracket["round_of_32"].append({
            "group": group_letter,
            "predicted_winner": winner,
            "predicted_runner_up": runner_up,
        })

    return bracket


@router.get("/winner-odds")
def get_winner_odds(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return predicted tournament winner probabilities for all 48 teams.

    Uses FIFA ranking total_points as a proxy for team strength.
    Normalizes to sum to 1.0 across all teams.
    """
    national_teams = db.query(Team).filter(Team.team_type == "national").all()
    if not national_teams:
        return {"teams": [], "note": "No national team data available"}

    # Get most recent FIFA ranking for each team — single batch query
    wo_team_ids = [t.id for t in national_teams if t.id]
    wo_latest_by_team: dict[int, FifaRanking] = {}
    if wo_team_ids:
        wo_all_rankings = (
            db.query(FifaRanking)
            .filter(FifaRanking.team_id.in_(wo_team_ids))
            .order_by(FifaRanking.rank_date.desc())
            .all()
        )
        for r in wo_all_rankings:
            if r.team_id not in wo_latest_by_team:
                wo_latest_by_team[r.team_id] = r

    team_strengths: list[dict] = []
    for team in national_teams:
        ranking = wo_latest_by_team.get(team.id)
        if ranking:
            team_strengths.append({
                "team_name": team.canonical_name,
                "fifa_rank": ranking.fifa_rank,
                "total_points": ranking.total_points or 0.0,
            })
        else:
            team_strengths.append({
                "team_name": team.canonical_name,
                "fifa_rank": 999,
                "total_points": 0.0,
            })

    # Normalize total_points to win probabilities
    # Use rank-based inverse scoring as fallback: strength = 1 / rank
    total_pts_sum = sum(t["total_points"] for t in team_strengths)

    if total_pts_sum > 0:
        for t in team_strengths:
            t["raw_strength"] = t["total_points"]
    else:
        for t in team_strengths:
            t["raw_strength"] = 1.0 / max(t["fifa_rank"], 1)

    total_strength = sum(t["raw_strength"] for t in team_strengths)

    for t in team_strengths:
        t["win_probability"] = round(t["raw_strength"] / total_strength, 6) if total_strength > 0 else 0.0

    team_strengths.sort(key=lambda x: x["win_probability"], reverse=True)

    return {
        "teams": [
            {
                "team_name": t["team_name"],
                "win_probability": t["win_probability"],
                "fifa_rank": t["fifa_rank"],
                "total_points": t["total_points"],
            }
            for t in team_strengths
        ],
        "note": "Win probability derived from FIFA ranking points. Model predictions will replace this when available.",
    }
