"""
backend/api/world_cup.py
=========================
Route handlers for the FIFA World Cup 2026 frontend hub.

Mounted under /api/v1 by main.py, so the full paths are:
  GET /api/v1/world-cup/overview    — hero stats for the page
  GET /api/v1/world-cup/groups      — all 12 group standings + next fixtures
  GET /api/v1/world-cup/fixtures    — upcoming/recent WC matches with stage filter
  GET /api/v1/world-cup/title-odds  — Monte Carlo tournament winner odds (stub)

Separate from api/worldcup.py (which powers an older `/worldcup/*` hub with
a different shape). The two coexist intentionally; the new hub page targets
this router exclusively.

All endpoints are read-only and computed from existing tables:
  - leagues.code = 'worldcup'  (identifies WC matches)
  - matches.stage, matches.group_label, matches.status   (already populated)
  - predictions.was_correct                              (for model accuracy)
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from api.matches import (
    _build_league_map,
    _build_prediction_map,
    _build_team_map,
    _match_to_summary,
)
from database import get_db
from models.league import League
from models.match import Match
from models.prediction import Prediction
from models.team import Team
from schemas.world_cup import (
    FinalsPair,
    GroupFixture,
    GroupFixtureTeam,
    GroupTable,
    HostCountry,
    KeyRisk as KeyRiskSchema,
    MostLikelyChampion,
    OpeningMatchResponse,
    ProjectedPathStep,
    RationaleFact as RationaleFactSchema,
    StandingRow as StandingRowSchema,
    TitleContender,
    TitleOddsResponse,
    WinnerRationale as WinnerRationaleSchema,
    WorldCupFixturesResponse,
    WorldCupGroupsResponse,
    WorldCupOverview,
)
from models.team_elo import TeamElo
from services.group_standings import (
    MatchInput,
    TeamInput,
    compute_group_table,
    compute_projected_table_by_elo,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/world-cup", tags=["world-cup"])

WC_LEAGUE_CODE = "worldcup"
WC_MODEL_VERSION = "wc-elo-v1"
WC_TOURNAMENT_NAME = "FIFA World Cup 2026"
WC_HOSTS: list[HostCountry] = [
    HostCountry(name="United States", country_code="us"),
    HostCountry(name="Canada", country_code="ca"),
    HostCountry(name="Mexico", country_code="mx"),
]

# Official 2026 tournament window. Exposed here (not hard-derived from fixtures)
# because the earliest knockout dates aren't in the DB yet.
WC_START_DATE = date(2026, 6, 11)
WC_END_DATE = date(2026, 7, 19)
WC_MATCHES_TOTAL = 104  # 48 teams, new format (12 groups of 4 + R32 knockouts)

# Group-stage matchday windows for the 2026 WC. Values are inclusive ranges on
# match_date. A matchday here means "nth round of group games" — useful for
# rendering "Matchday 2 of 3" copy on the overview hero.
GROUP_MATCHDAY_WINDOWS: list[tuple[int, date, date]] = [
    (1, date(2026, 6, 11), date(2026, 6, 17)),
    (2, date(2026, 6, 18), date(2026, 6, 23)),
    (3, date(2026, 6, 24), date(2026, 6, 27)),
]

# Ordering of stages for "most-advanced scheduled/live stage" detection.
STAGE_ORDER = ["group", "r32", "r16", "qf", "sf", "3rd-place", "final"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_wc_league_id(db: Session) -> Optional[int]:
    league = db.query(League).filter(League.code == WC_LEAGUE_CODE).first()
    return league.id if league else None


def _latest_elo_by_team(db: Session, team_ids: list[int]) -> dict[int, float]:
    """Return latest (highest as_of_date) Elo rating per team_id.

    Uses `ix_team_elo_team_date`. Teams with no row are simply omitted —
    callers should fall back to a neutral default.
    """
    if not team_ids:
        return {}
    # Single grouped query — pull max(as_of_date) per team, then join back
    # to fetch the rating on that date. Simpler: load all rows for the
    # given teams (small set: ≤48 WC teams) and reduce in Python.
    rows = (
        db.query(TeamElo.team_id, TeamElo.as_of_date, TeamElo.rating)
        .filter(TeamElo.team_id.in_(team_ids))
        .all()
    )
    latest: dict[int, tuple[date, float]] = {}
    for team_id, as_of_date, rating in rows:
        cur = latest.get(team_id)
        if cur is None or as_of_date > cur[0]:
            latest[team_id] = (as_of_date, float(rating))
    return {tid: r for tid, (_, r) in latest.items()}


def _kickoff_datetime(m: Match) -> Optional[datetime]:
    """Combine match_date + kickoff_time ('HH:MM') into a naive datetime.

    Returns the date at midnight if kickoff_time is missing/malformed.
    Kept naive (no tz) to match how the rest of the API returns times.
    """
    if not m.match_date:
        return None
    if m.kickoff_time:
        try:
            hh, mm = m.kickoff_time.split(":")
            return datetime.combine(m.match_date, time(int(hh), int(mm)))
        except (ValueError, AttributeError):
            pass
    return datetime.combine(m.match_date, time.min)


def _current_matchday(played_dates: list[date]) -> Optional[int]:
    """Return the current group-stage matchday based on today's date.

    If the tournament hasn't started, return None.
    If we're between two matchdays, return the upcoming one.
    If we're past matchday 3, return None (group stage over).
    """
    today = date.today()
    for md, start, end in GROUP_MATCHDAY_WINDOWS:
        if today <= end:
            return md
    return None


def _derive_current_stage(wc_matches: list[Match]) -> str:
    """Most-advanced stage with at least one scheduled-or-live match.

    If all matches are completed → 'completed'.
    If there are no matches at all → 'pre-tournament'.
    """
    if not wc_matches:
        return "pre-tournament"

    all_completed = all(m.status == "completed" for m in wc_matches)
    if all_completed:
        return "completed"

    # Find highest-index stage among scheduled/live matches
    active_stages = {
        m.stage for m in wc_matches
        if m.status in ("scheduled", "live") and m.stage
    }
    if not active_stages:
        return "pre-tournament"

    for stage in reversed(STAGE_ORDER):
        if stage in active_stages:
            return stage
    return "group"


# ── 1. Overview ───────────────────────────────────────────────────────────────

@router.get("/overview", response_model=WorldCupOverview)
def get_overview(db: Session = Depends(get_db)) -> WorldCupOverview:
    """Return hero-stat summary for the WC page."""
    league_id = _get_wc_league_id(db)
    wc_matches: list[Match] = []
    if league_id is not None:
        wc_matches = db.query(Match).filter(Match.league_id == league_id).all()

    matches_played = sum(1 for m in wc_matches if m.status == "completed")
    matches_remaining = sum(1 for m in wc_matches if m.status in ("scheduled", "live"))

    # Compute model accuracy from evaluated WC predictions
    accuracy: Optional[float] = None
    if wc_matches:
        wc_match_ids = [m.id for m in wc_matches]
        evaluated = (
            db.query(Prediction.was_correct)
            .filter(
                Prediction.match_id.in_(wc_match_ids),
                Prediction.was_correct.isnot(None),
            )
            .all()
        )
        if evaluated:
            correct = sum(1 for row in evaluated if row[0])
            accuracy = round(correct / len(evaluated), 4)

    # Next scheduled kickoff
    next_kickoff: Optional[datetime] = None
    upcoming = [m for m in wc_matches if m.status in ("scheduled", "live")]
    if upcoming:
        upcoming.sort(key=lambda m: (m.match_date, m.kickoff_time or "99:99"))
        next_kickoff = _kickoff_datetime(upcoming[0])

    return WorldCupOverview(
        tournament_name=WC_TOURNAMENT_NAME,
        start_date=WC_START_DATE,
        end_date=WC_END_DATE,
        host_countries=WC_HOSTS,
        current_stage=_derive_current_stage(wc_matches),
        current_matchday=_current_matchday([m.match_date for m in wc_matches if m.status == "completed"]),
        matches_total=WC_MATCHES_TOTAL,
        matches_played=matches_played,
        matches_remaining=matches_remaining,
        model_accuracy_wc=accuracy,
        model_version=WC_MODEL_VERSION,
        next_match_kickoff=next_kickoff,
    )


# ── 2. Groups ─────────────────────────────────────────────────────────────────

def _load_wc_groups_config() -> dict[str, list[str]]:
    """Import WORLD_CUP_2026_GROUPS from ml/src/config (walks up the tree)."""
    ml_dir = next(
        (p / "ml" for p in Path(__file__).resolve().parents
         if (p / "ml" / "src" / "config.py").is_file()),
        None,
    )
    if ml_dir is not None and str(ml_dir) not in sys.path:
        sys.path.insert(0, str(ml_dir))
    try:
        from src.config import WORLD_CUP_2026_GROUPS  # type: ignore
        return dict(WORLD_CUP_2026_GROUPS)
    except ImportError:
        logger.warning("ml/src/config.py not importable — group labels will come from DB only")
        return {}


@router.get("/groups", response_model=WorldCupGroupsResponse)
def get_groups(db: Session = Depends(get_db)) -> WorldCupGroupsResponse:
    """Return all 12 group tables with standings + next 2 fixtures per group."""
    league_id = _get_wc_league_id(db)
    if league_id is None:
        return WorldCupGroupsResponse(groups=[])

    group_matches = (
        db.query(Match)
        .filter(
            Match.league_id == league_id,
            Match.stage == "group",
            Match.group_label.isnot(None),
        )
        .all()
    )

    # Collect team ids present in group matches
    team_ids = set()
    for m in group_matches:
        team_ids.add(m.home_team_id)
        team_ids.add(m.away_team_id)
    teams_by_id = _build_team_map(db, list(team_ids))

    # Also load teams via the ml config so groups render fully even before
    # matches exist for them (edge case).
    groups_config = _load_wc_groups_config()
    if groups_config:
        config_team_names = {n for names in groups_config.values() for n in names}
        extra_teams = (
            db.query(Team)
            .filter(Team.canonical_name.in_(config_team_names))
            .all()
        )
        for t in extra_teams:
            teams_by_id[t.id] = t

    # Bucket matches by group_label
    matches_by_group: dict[str, list[Match]] = defaultdict(list)
    for m in group_matches:
        matches_by_group[m.group_label].append(m)

    # Derive the team roster per group. Prefer ml config (authoritative ordering),
    # fall back to whichever teams appear in that group's matches.
    name_to_team = {t.canonical_name: t for t in teams_by_id.values()}

    def roster_for(label: str) -> list[TeamInput]:
        if label in groups_config:
            out: list[TeamInput] = []
            for name in groups_config[label]:
                t = name_to_team.get(name)
                if t is None:
                    continue
                out.append(TeamInput(team_id=t.id, name=t.canonical_name, country_code=t.country_code))
            return out
        # Fallback: unique teams seen in this group's matches
        seen_ids: list[int] = []
        for m in matches_by_group[label]:
            for tid in (m.home_team_id, m.away_team_id):
                if tid not in seen_ids:
                    seen_ids.append(tid)
        out = []
        for tid in seen_ids:
            t = teams_by_id.get(tid)
            if t is None:
                continue
            out.append(TeamInput(team_id=t.id, name=t.canonical_name, country_code=t.country_code))
        return out

    # Build groups in alphabetic label order (A–L), using config keys if present.
    labels = sorted(groups_config.keys()) if groups_config else sorted(matches_by_group.keys())

    # Pre-load latest Elo for every team that might appear, so per-group
    # projection is one dict lookup rather than N queries.
    all_roster_team_ids = list({
        ti.team_id for label in labels for ti in roster_for(label)
    })
    elo_by_team = _latest_elo_by_team(db, all_roster_team_ids)

    group_tables: list[GroupTable] = []
    for label in labels:
        roster = roster_for(label)
        match_inputs = [
            MatchInput(
                home_team_id=m.home_team_id,
                away_team_id=m.away_team_id,
                home_goals=m.home_goals,
                away_goals=m.away_goals,
                status=m.status,
            )
            for m in matches_by_group[label]
        ]
        any_completed = any(
            mi.status == "completed"
            and mi.home_goals is not None
            and mi.away_goals is not None
            for mi in match_inputs
        )
        if any_completed or not roster:
            standings = compute_group_table(match_inputs, roster)
            is_projected = False
        else:
            standings = compute_projected_table_by_elo(roster, elo_by_team)
            is_projected = True

        standings_out = [
            StandingRowSchema(
                team_id=r.team_id,
                name=r.name,
                country_code=r.country_code,
                played=r.played,
                wins=r.wins,
                draws=r.draws,
                losses=r.losses,
                goals_for=r.goals_for,
                goals_against=r.goals_against,
                goal_diff=r.goal_diff,
                points=r.points,
                qualification_status=r.qualification_status,  # type: ignore[arg-type]
            )
            for r in standings
        ]

        # Next 2 fixtures in this group, ordered by kickoff
        today = date.today()
        upcoming_matches = sorted(
            (m for m in matches_by_group[label]
             if m.status in ("scheduled", "live") and m.match_date >= today),
            key=lambda m: (m.match_date, m.kickoff_time or "99:99"),
        )[:2]

        next_fixtures = []
        for fm in upcoming_matches:
            home = teams_by_id.get(fm.home_team_id)
            away = teams_by_id.get(fm.away_team_id)
            next_fixtures.append(GroupFixture(
                match_id=fm.id,
                home=GroupFixtureTeam(
                    name=home.canonical_name if home else f"Team {fm.home_team_id}",
                    country_code=home.country_code if home else None,
                ),
                away=GroupFixtureTeam(
                    name=away.canonical_name if away else f"Team {fm.away_team_id}",
                    country_code=away.country_code if away else None,
                ),
                kickoff=_kickoff_datetime(fm),
                match_date=fm.match_date,
            ))

        group_tables.append(GroupTable(
            label=label,
            venue=None,  # `matches` has no location column; frontend can show fallback
            teams=standings_out,
            next_fixtures=next_fixtures,
            is_projected=is_projected,
        ))

    return WorldCupGroupsResponse(groups=group_tables)


# ── 3. Fixtures ───────────────────────────────────────────────────────────────

@router.get("/fixtures", response_model=WorldCupFixturesResponse)
def get_fixtures(
    stage: Optional[str] = Query(None, description="Filter by stage (group, r32, r16, qf, sf, final, 3rd-place)"),
    days: Optional[int] = Query(None, ge=1, le=60, description="Window of ±days around today"),
    include_completed: bool = Query(False, description="If true, include completed matches"),
    db: Session = Depends(get_db),
) -> WorldCupFixturesResponse:
    """Return WC matches, filtered by stage and a time window around today."""
    league_id = _get_wc_league_id(db)
    if league_id is None:
        return WorldCupFixturesResponse(
            matches=[], total=0, stage_filter=stage, days=days, include_completed=include_completed,
        )

    query = db.query(Match).filter(Match.league_id == league_id)

    if stage:
        query = query.filter(Match.stage == stage)

    if not include_completed:
        query = query.filter(Match.status.in_(["scheduled", "live"]))

    if days is not None:
        today = date.today()
        window_start = today - timedelta(days=days)
        window_end = today + timedelta(days=days)
        query = query.filter(
            and_(Match.match_date >= window_start, Match.match_date <= window_end)
        )

    matches = query.order_by(Match.match_date, Match.kickoff_time).all()

    team_ids = list({m.home_team_id for m in matches} | {m.away_team_id for m in matches})
    league_ids = list({m.league_id for m in matches if m.league_id})
    match_ids = [m.id for m in matches]

    teams_map = _build_team_map(db, team_ids)
    leagues_map = _build_league_map(db, league_ids)
    predictions = _build_prediction_map(db, match_ids)

    summaries = [_match_to_summary(m, teams_map, leagues_map, predictions) for m in matches]

    return WorldCupFixturesResponse(
        matches=summaries,
        total=len(summaries),
        stage_filter=stage,
        days=days,
        include_completed=include_completed,
    )


# ── 3b. Opening match ─────────────────────────────────────────────────────────


def _build_opening_rationale(
    home_name: str,
    away_name: str,
    home_elo: Optional[float],
    away_elo: Optional[float],
    pred_home_pct: Optional[int],
) -> str:
    """One-sentence rationale for the opening match, factual and rating-grounded.

    Phrased in user-facing terms — no "Elo" jargon. Falls back to a neutral
    sentence when ratings or prediction are unavailable.
    """
    if home_elo is None or away_elo is None or pred_home_pct is None:
        return f"{home_name} opens the tournament against {away_name}."

    if home_elo > away_elo:
        return (
            f"{home_name} hosts {away_name} — the model gives the hosts the edge at "
            f"{pred_home_pct}% on home advantage."
        )
    if home_elo < away_elo:
        return (
            f"{home_name} hosts the higher-rated {away_name}; the model still gives "
            f"the hosts {pred_home_pct}% on home advantage."
        )
    return (
        f"{home_name} hosts {away_name} in an evenly-matched opener; the model gives "
        f"the hosts {pred_home_pct}% on home advantage."
    )


@router.get("/opening-match", response_model=OpeningMatchResponse)
def get_opening_match(db: Session = Depends(get_db)) -> OpeningMatchResponse:
    """Return the first WC fixture (by date, then kickoff) plus a one-line rationale."""
    league_id = _get_wc_league_id(db)
    if league_id is None:
        return OpeningMatchResponse(available=False, reason="World Cup league not configured")

    first = (
        db.query(Match)
        .filter(Match.league_id == league_id, Match.match_date.isnot(None))
        .order_by(Match.match_date.asc(), func.coalesce(Match.kickoff_time, "99:99").asc())
        .first()
    )
    if first is None:
        return OpeningMatchResponse(available=False, reason="No World Cup fixtures available")

    teams_map = _build_team_map(db, [first.home_team_id, first.away_team_id])
    leagues_map = _build_league_map(db, [first.league_id] if first.league_id else [])
    predictions = _build_prediction_map(db, [first.id])
    summary = _match_to_summary(first, teams_map, leagues_map, predictions)

    elos = _latest_elo_by_team(db, [first.home_team_id, first.away_team_id])
    home_elo = elos.get(first.home_team_id)
    away_elo = elos.get(first.away_team_id)

    pred_home_pct: Optional[int] = None
    if summary.prediction and summary.prediction.prob_home_win is not None:
        pred_home_pct = round(summary.prediction.prob_home_win * 100)

    rationale = _build_opening_rationale(
        home_name=summary.home_team_name,
        away_name=summary.away_team_name,
        home_elo=home_elo,
        away_elo=away_elo,
        pred_home_pct=pred_home_pct,
    )

    return OpeningMatchResponse(
        available=True,
        match=summary,
        home_elo=home_elo,
        away_elo=away_elo,
        rationale=rationale,
    )


# ── 4. Title odds ─────────────────────────────────────────────────────────────

# Cap for the contenders list returned to the frontend. The full sim covers
# 48 teams; the WC page only renders the leaderboard, and downstream clients
# can re-query if they need the full distribution.
_TITLE_CONTENDERS_LIMIT = 24


@router.get("/title-odds", response_model=TitleOddsResponse)
def get_title_odds(db: Session = Depends(get_db)) -> TitleOddsResponse:
    """Return the latest tournament Monte Carlo result.

    Reads `tournament_simulations` for the most recent row (ordered by run_at
    desc). If no simulation has been run yet, returns `available=False` with
    a hint pointing at the admin trigger endpoint.
    """
    import json

    from models.tournament_simulation import TournamentSimulation
    from services.tournament_simulator import result_from_json

    row = (
        db.query(TournamentSimulation)
        .order_by(TournamentSimulation.run_at.desc())
        .first()
    )
    if row is None:
        return TitleOddsResponse(
            available=False,
            reason=(
                "No simulation run yet — schedule via "
                "POST /api/v1/admin/world-cup/run-simulation"
            ),
        )

    try:
        result = result_from_json(json.loads(row.result_json))
    except (ValueError, KeyError) as e:
        logger.exception("Failed to parse stored simulation row id=%s", row.id)
        return TitleOddsResponse(
            available=False,
            reason=f"Stored simulation could not be deserialised: {e}",
        )

    contenders = [
        TitleContender(
            team_id=p.team_id,
            name=p.name,
            country_code=p.country_code,
            win_tournament_pct=round(p.win_tournament_pct, 2),
            reach_final_pct=round(p.reach_final_pct, 2),
            reach_semis_pct=round(p.reach_semis_pct, 2),
            reach_qf_pct=round(p.reach_qf_pct, 2),
            reach_r16_pct=round(p.reach_r16_pct, 2),
            reach_r32_pct=round(p.reach_r32_pct, 2),
        )
        for p in result.per_team[:_TITLE_CONTENDERS_LIMIT]
    ]

    most_likely_champion: Optional[MostLikelyChampion] = None
    if result.most_likely_champion_id is not None and result.per_team:
        top = result.per_team[0]

        rationale_schema: Optional[WinnerRationaleSchema] = None
        try:
            from services.wc_rationale import generate_winner_rationale
            rationale = generate_winner_rationale(db, result)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to generate winner rationale; serving without it")
            rationale = None
        if rationale is not None:
            rationale_schema = WinnerRationaleSchema(
                facts=[
                    RationaleFactSchema(
                        label=f.label, value=f.value, rank=f.rank, icon=f.icon,
                    )
                    for f in rationale.rationale_facts
                ],
                key_risk=(
                    KeyRiskSchema(
                        stage=rationale.key_risk.stage,
                        opponent=GroupFixtureTeam(
                            name=rationale.key_risk.opponent.name,
                            country_code=rationale.key_risk.opponent.country_code,
                        ),
                        win_prob=round(rationale.key_risk.win_prob, 4),
                        explanation=rationale.key_risk.explanation,
                    )
                    if rationale.key_risk is not None
                    else None
                ),
            )

        most_likely_champion = MostLikelyChampion(
            team_id=top.team_id,
            team=GroupFixtureTeam(name=top.name, country_code=top.country_code),
            win_tournament_pct=round(top.win_tournament_pct, 2),
            projected_path=[
                ProjectedPathStep(
                    stage=s.stage,
                    opponent=(
                        GroupFixtureTeam(
                            name=s.opponent_name,
                            country_code=s.opponent_country_code,
                        )
                        if s.opponent_name is not None
                        else None
                    ),
                    win_prob=round(s.win_prob, 4),
                    frequency=round(s.frequency, 4),
                )
                for s in result.most_likely_champion_path
            ],
            rationale=rationale_schema,
        )

    finals_pairs = [
        FinalsPair(
            champion=GroupFixtureTeam(
                name=f.champion_name, country_code=f.champion_country_code
            ),
            runner_up=GroupFixtureTeam(
                name=f.runner_up_name, country_code=f.runner_up_country_code
            ),
            frequency=round(f.frequency, 4),
        )
        for f in result.most_likely_finals
    ]

    return TitleOddsResponse(
        available=True,
        run_at=result.run_at,
        n_sims=result.n_sims,
        seed=result.seed,
        model_version=result.model_version,
        elo_model_version=result.elo_model_version,
        title_contenders=contenders,
        most_likely_champion=most_likely_champion,
        most_likely_finals=finals_pairs,
    )
