"""
backend/schemas/world_cup.py
=============================
Pydantic response schemas for the FIFA World Cup 2026 hub endpoints
(see backend/api/world_cup.py).

Kept separate from schemas/match.py because the WC hub has its own
compact shapes (hero overview, group standing rows, grouped fixtures)
that don't belong in the general match schema.
"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel

from schemas.match import MatchSummary


# ── Overview ──────────────────────────────────────────────────────────────────

class HostCountry(BaseModel):
    name: str
    country_code: str


class WorldCupOverview(BaseModel):
    tournament_name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    host_countries: list[HostCountry]
    current_stage: str  # 'pre-tournament' | 'group' | 'r32' | ... | 'completed'
    current_matchday: Optional[int] = None
    matches_total: int
    matches_played: int
    matches_remaining: int
    model_accuracy_wc: Optional[float] = None
    model_version: str
    next_match_kickoff: Optional[datetime] = None


# ── Groups ────────────────────────────────────────────────────────────────────

QualificationStatus = Literal[
    "advancing", "third-place", "best_third", "eliminated", "live"
]


class StandingRow(BaseModel):
    team_id: int
    name: str
    country_code: Optional[str] = None
    played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    goal_diff: int
    points: int
    qualification_status: QualificationStatus


class GroupFixtureTeam(BaseModel):
    name: str
    country_code: Optional[str] = None


class GroupFixture(BaseModel):
    match_id: int
    home: GroupFixtureTeam
    away: GroupFixtureTeam
    kickoff: Optional[datetime] = None
    match_date: date


class GroupTable(BaseModel):
    label: str
    venue: Optional[str] = None
    teams: list[StandingRow]
    next_fixtures: list[GroupFixture]
    # True when team statuses are projected from latest Elo (pre-tournament,
    # no match in this group played yet). False once at least one group match
    # has been recorded and statuses are computed from real results.
    is_projected: bool = False


class WorldCupGroupsResponse(BaseModel):
    groups: list[GroupTable]


# ── Fixtures ──────────────────────────────────────────────────────────────────

class WorldCupFixturesResponse(BaseModel):
    matches: list[MatchSummary]
    total: int
    stage_filter: Optional[str] = None
    days: Optional[int] = None
    include_completed: bool


# ── Opening match ─────────────────────────────────────────────────────────────


class OpeningMatchResponse(BaseModel):
    """Response for /world-cup/opening-match.

    Returns a single MatchSummary (the very first WC fixture by date+kickoff)
    plus a one-sentence Elo-based rationale string. `available=False` when no
    WC fixtures exist yet.
    """
    available: bool
    match: Optional[MatchSummary] = None
    home_elo: Optional[float] = None
    away_elo: Optional[float] = None
    rationale: Optional[str] = None
    reason: Optional[str] = None


# ── Title odds ────────────────────────────────────────────────────────────────


class TitleContender(BaseModel):
    team_id: int
    name: str
    country_code: Optional[str] = None
    win_tournament_pct: float
    reach_final_pct: float
    reach_semis_pct: float
    reach_qf_pct: float
    reach_r16_pct: float
    reach_r32_pct: float


class FinalsPair(BaseModel):
    champion: GroupFixtureTeam
    runner_up: GroupFixtureTeam
    frequency: float  # fraction of sims producing this exact pair


class ProjectedPathStep(BaseModel):
    stage: str  # 'r32' | 'r16' | 'qf' | 'sf' | 'final'
    opponent: Optional[GroupFixtureTeam] = None
    win_prob: float
    frequency: float  # fraction of sims (where champion reached this stage) facing this opponent


class RationaleFact(BaseModel):
    label: str
    value: str
    rank: Optional[int] = None
    icon: Optional[str] = None  # 'trending-up' | 'shield' | 'route' | None


class KeyRisk(BaseModel):
    stage: str  # 'r32' | 'r16' | 'qf' | 'sf' | 'final'
    opponent: GroupFixtureTeam
    win_prob: float
    explanation: str


class WinnerRationale(BaseModel):
    facts: list[RationaleFact]
    key_risk: Optional[KeyRisk] = None


class MostLikelyChampion(BaseModel):
    team: GroupFixtureTeam
    team_id: int
    win_tournament_pct: float
    projected_path: list[ProjectedPathStep]
    rationale: Optional[WinnerRationale] = None


class TitleOddsResponse(BaseModel):
    available: bool
    reason: Optional[str] = None
    run_at: Optional[datetime] = None
    n_sims: Optional[int] = None
    seed: Optional[int] = None
    model_version: Optional[str] = None
    elo_model_version: Optional[str] = None
    title_contenders: Optional[list[TitleContender]] = None
    most_likely_champion: Optional[MostLikelyChampion] = None
    most_likely_finals: Optional[list[FinalsPair]] = None
