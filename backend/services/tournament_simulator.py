"""
backend/services/tournament_simulator.py
=========================================
Monte Carlo simulator for the FIFA World Cup 2026.

Powers the WC page's Title Contenders, Predicted Winner, and Bracket Teaser
sections. Pure compute on top of the validated `national_elo` model and the
`group_standings` tiebreaker logic — both reused as-is to guarantee the
simulator's per-match probabilities are identical to what the rest of the
pipeline produces.

What it does
------------
For each Monte Carlo run:
  1. Group stage — sample H/D/A outcomes from stored predictions when present,
     otherwise from `predict_from_elo`. For sampled draws/wins we fabricate
     plausible scorelines (1-1 / 1-0 / 2-1) because `compute_group_table`
     needs goals to break ties; the goal-pattern is held fixed so the GD/GF
     tiebreakers remain meaningful.
  2. Group standings — top 2 of each group advance; best 8 third-placed teams
     across all groups round out the R32 field.
  3. Knockouts — walk R32 → R16 → QF → SF → Final via the official 2026
     bracket schema (see _R32_SLOTS below). Each tie sampled from a 2-class
     {home, away} renormalisation of `predict_from_elo` (knockouts are
     decided on the day; we drop p_draw and rescale). All knockouts at
     neutral venues. Elos update in-sim with K=60 — see "Choices" below.

Aggregated over N sims:
  - Per-team probability of reaching each round (R32 / R16 / QF / SF / Final
    / champion).
  - The most-likely champion's modal opponent at each stage with that
    matchup's win probability under current Elos.
  - Top-5 most-frequent (champion, runner-up) finals pairings.

Choices and their justifications
--------------------------------
* In-sim Elo updates after every knockout match (K=60). This means a team
  that "wins" R32 in a given sim plays its R16 opponent at a slightly
  inflated rating — realistic, because real tournaments produce hot teams
  and the Elo formula already encodes win-streak credit. Without this,
  later-round matchups would use rating snapshots that ignore the path
  taken; with it, sims model momentum directionally. Goal-difference
  modifier defaults to G=1 (single-goal margin) in knockouts since we
  don't simulate scorelines beyond H/A.
* Knockouts use a 2-class draw-stripped distribution. Per the project's
  convention (FIFA knockouts are settled by ET/penalties), we collapse
  p_draw onto the favourite and underdog by simply renormalising over
  {home, away}. This is equivalent to the Bradley-Terry win-expectancy
  E_h = 1 / (1 + 10 ** ((R_a - R_h) / 400)) at neutral venues — which is
  exactly what predict_from_elo's _expected_home returns. We use that
  directly to skip the unused p_draw computation in the hot loop.
* Best-8 third-placed selection follows FIFA's announced order
  (points → GD → GF → goals scored → fair-play → drawing of lots).
  We implement the first four; the final two are deterministic
  alphabetic-by-group fallbacks for stability.
* Bracket-slot assignment for the 8 third-placed teams is the only place
  the actual FIFA scenario table (495 cases) is approximated. We assign
  each qualifying third-placed team to the lowest-numbered R32 slot whose
  group-source set contains that team's group, in match order
  (74, 77, 79, 80, 81, 82, 85, 87). This is deterministic, never violates
  the "must be from one of these groups" constraint, and is good enough
  for the aggregate rate output we're producing — exact slot mapping only
  matters for individual-bracket reasoning, not Monte Carlo aggregates.

Reproducibility
---------------
A single numpy.random.Generator seeded with `seed` drives the entire run.
Same seed → byte-identical TournamentSimResult.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
from sqlalchemy import desc
from sqlalchemy.orm import Session

from models.league import League
from models.match import Match
from models.prediction import Prediction
from models.team import Team
from models.team_elo import TeamElo
from services.group_standings import (
    MatchInput,
    TeamInput,
    compute_group_table,
)
from services.national_elo import (
    HOME_FIELD_ADVANTAGE,
    _expected_home,
    predict_from_elo,
    update_elo,
)

logger = logging.getLogger(__name__)

WC_LEAGUE_CODE = "worldcup"
SIM_MODEL_VERSION = "wc-mc-v1"
ELO_MODEL_VERSION = "wc-elo-v1"
WC_K_KNOCKOUT = 60  # World-Cup K-factor (matches infer_k('world_cup'))

# Stage codes
STAGE_R32 = "r32"
STAGE_R16 = "r16"
STAGE_QF = "qf"
STAGE_SF = "sf"
STAGE_FINAL = "final"
KNOCKOUT_STAGES = [STAGE_R32, STAGE_R16, STAGE_QF, STAGE_SF, STAGE_FINAL]


# ── Result dataclasses ────────────────────────────────────────────────────────


@dataclass
class TeamProjection:
    team_id: int
    name: str
    country_code: Optional[str]
    win_tournament_pct: float
    reach_final_pct: float
    reach_semis_pct: float
    reach_qf_pct: float
    reach_r16_pct: float
    reach_r32_pct: float


@dataclass
class PathStep:
    stage: str
    opponent_team_id: Optional[int]
    opponent_name: Optional[str]
    opponent_country_code: Optional[str]
    win_prob: float
    frequency: float  # fraction of sims (in which our champion reached this stage) where this opponent appeared


@dataclass
class FinalsProjection:
    champion_team_id: int
    champion_name: str
    champion_country_code: Optional[str]
    runner_up_team_id: int
    runner_up_name: str
    runner_up_country_code: Optional[str]
    frequency: float  # share of all sims producing this exact (champion, runner-up) pair


@dataclass
class TournamentSimResult:
    run_at: datetime
    n_sims: int
    seed: int
    model_version: str
    elo_model_version: str
    per_team: list[TeamProjection]
    most_likely_finals: list[FinalsProjection]
    most_likely_champion_id: Optional[int]
    most_likely_champion_path: list[PathStep]


# ── R32 bracket schema (official FIFA 2026 mapping) ───────────────────────────
#
# Each slot is one R32 match. Encoded as (match_id, side_a, side_b) where each
# side is one of:
#   ("W", "<group_label>")          → winner of group
#   ("R", "<group_label>")          → runner-up of group
#   ("3", frozenset(group_labels))  → best-3rd from one of these groups
#
# Sourced from Wikipedia/FIFA's 2026 knockout bracket (matches 73-88).
# Cross-referenced with goalcup2026.com and ESPN.
#
_R32_SLOTS: list[tuple[int, tuple, tuple]] = [
    (73, ("R", "A"), ("R", "B")),
    (74, ("W", "E"), ("3", frozenset({"A", "B", "C", "D", "F"}))),
    (75, ("W", "F"), ("R", "C")),
    (76, ("W", "C"), ("R", "F")),
    (77, ("W", "I"), ("3", frozenset({"C", "D", "F", "G", "H"}))),
    (78, ("R", "E"), ("R", "I")),
    (79, ("W", "A"), ("3", frozenset({"C", "E", "F", "H", "I"}))),
    (80, ("W", "L"), ("3", frozenset({"E", "H", "I", "J", "K"}))),
    (81, ("W", "D"), ("3", frozenset({"B", "E", "F", "I", "J"}))),
    (82, ("W", "G"), ("3", frozenset({"A", "E", "H", "I", "J"}))),
    (83, ("R", "K"), ("R", "L")),
    (84, ("W", "H"), ("R", "J")),
    (85, ("W", "B"), ("3", frozenset({"E", "F", "G", "I", "J"}))),
    (86, ("W", "J"), ("R", "H")),
    (87, ("W", "K"), ("3", frozenset({"D", "E", "I", "J", "L"}))),
    (88, ("R", "D"), ("R", "G")),
]

# R16 bracket: each R16 match is (match_id, src_match_a, src_match_b).
_R16_PAIRS: list[tuple[int, int, int]] = [
    (89, 74, 77),
    (90, 73, 75),
    (91, 76, 78),
    (92, 79, 80),
    (93, 83, 84),
    (94, 81, 82),
    (95, 86, 88),
    (96, 85, 87),
]

_QF_PAIRS: list[tuple[int, int, int]] = [
    (97, 89, 90),
    (98, 93, 94),
    (99, 91, 92),
    (100, 95, 96),
]

_SF_PAIRS: list[tuple[int, int, int]] = [
    (101, 97, 98),
    (102, 99, 100),
]

_FINAL_PAIR: tuple[int, int, int] = (104, 101, 102)


# ── Data loading helpers ──────────────────────────────────────────────────────


def _load_latest_elo(db: Session) -> dict[int, float]:
    """Return {team_id: latest_rating}.

    Uses (team_id, max(as_of_date)) — the ix_team_elo_team_date index
    makes this cheap. We load all rows and reduce in Python because there
    are only ~50 national teams in the table; a window-function query
    is overkill at this size.
    """
    rows = db.query(TeamElo).order_by(TeamElo.team_id, desc(TeamElo.as_of_date)).all()
    out: dict[int, float] = {}
    for r in rows:
        if r.team_id not in out:  # first row per team is latest by sort order
            out[r.team_id] = float(r.rating)
    return out


def _load_wc_data(db: Session) -> tuple[
    int,
    list[Match],
    dict[int, Team],
    dict[int, tuple[float, float, float]],
    dict[int, float],
]:
    """Load all WC inputs in one place.

    Returns:
      league_id, matches, teams_by_id, predictions_by_match_id, elo_by_team_id
    where `predictions_by_match_id` maps to (p_h, p_d, p_a) for matches that
    have a stored wc-elo-v1 prediction.
    """
    league = db.query(League).filter(League.code == WC_LEAGUE_CODE).first()
    if league is None:
        raise RuntimeError("World Cup league row not found (leagues.code='worldcup')")

    matches = db.query(Match).filter(Match.league_id == league.id).all()
    if not matches:
        raise RuntimeError("No World Cup matches in DB — cannot simulate")

    team_ids = {m.home_team_id for m in matches} | {m.away_team_id for m in matches}
    teams = db.query(Team).filter(Team.id.in_(team_ids)).all()
    teams_by_id = {t.id: t for t in teams}

    preds = (
        db.query(Prediction)
        .filter(
            Prediction.match_id.in_([m.id for m in matches]),
            Prediction.model_version == ELO_MODEL_VERSION,
        )
        .all()
    )
    preds_by_match: dict[int, tuple[float, float, float]] = {
        p.match_id: (float(p.prob_home_win), float(p.prob_draw), float(p.prob_away_win))
        for p in preds
    }

    elo = _load_latest_elo(db)

    # Defensive: every WC team must have an Elo rating, otherwise sim is unsound.
    missing = [tid for tid in team_ids if tid not in elo]
    if missing:
        names = [teams_by_id[t].canonical_name for t in missing if t in teams_by_id]
        raise RuntimeError(f"Missing Elo for WC teams: {names!r}")

    return league.id, matches, teams_by_id, preds_by_match, elo


# ── Group stage simulation ────────────────────────────────────────────────────


# Fixed scoreline templates by sampled outcome. Held constant so GD/GF
# tiebreakers stay informative without us having to model scorelines.
#   H → 1-0, D → 1-1, A → 0-1
_SCORELINE = {"H": (1, 0), "D": (1, 1), "A": (0, 1)}


def _probs_for_match(
    m: Match,
    preds_by_match: dict[int, tuple[float, float, float]],
    elo: dict[int, float],
) -> tuple[float, float, float]:
    """(p_home, p_draw, p_away) from stored prediction or live Elo lookup."""
    cached = preds_by_match.get(m.id)
    if cached is not None:
        return cached
    return predict_from_elo(
        elo[m.home_team_id],
        elo[m.away_team_id],
        is_neutral=bool(m.is_neutral_venue),
    )


def _simulate_group_stage(
    matches: list[Match],
    preds_by_match: dict[int, tuple[float, float, float]],
    elo: dict[int, float],
    rng: np.random.Generator,
) -> dict[str, list[MatchInput]]:
    """Sample outcomes for every group-stage match.

    Returns a dict {group_label: [MatchInput, ...]} ready to be fed into
    compute_group_table. Completed matches preserve their actual scoreline.
    """
    by_group: dict[str, list[MatchInput]] = defaultdict(list)

    for m in matches:
        if m.stage != "group":
            continue
        if m.status == "completed" and m.home_goals is not None and m.away_goals is not None:
            by_group[m.group_label].append(MatchInput(
                home_team_id=m.home_team_id,
                away_team_id=m.away_team_id,
                home_goals=m.home_goals,
                away_goals=m.away_goals,
                status="completed",
            ))
            continue

        p_h, p_d, p_a = _probs_for_match(m, preds_by_match, elo)
        # Sample one of {0,1,2} → H/D/A
        idx = rng.choice(3, p=[p_h, p_d, p_a])
        outcome = ("H", "D", "A")[idx]
        hg, ag = _SCORELINE[outcome]
        by_group[m.group_label].append(MatchInput(
            home_team_id=m.home_team_id,
            away_team_id=m.away_team_id,
            home_goals=hg,
            away_goals=ag,
            status="completed",
        ))

    return by_group


def _build_group_rosters(
    matches: list[Match],
    teams_by_id: dict[int, Team],
) -> dict[str, list[TeamInput]]:
    """Derive {group_label: [TeamInput, ...]} from the group-stage matches.

    Order within a group follows first-seen-team-id; this only affects
    name-based tiebreaker stability in compute_group_table (which sorts
    by name internally), so the exact order here doesn't matter.
    """
    by_group: dict[str, list[TeamInput]] = defaultdict(list)
    seen: dict[str, set[int]] = defaultdict(set)
    for m in matches:
        if m.stage != "group" or m.group_label is None:
            continue
        for tid in (m.home_team_id, m.away_team_id):
            if tid in seen[m.group_label]:
                continue
            seen[m.group_label].add(tid)
            t = teams_by_id.get(tid)
            if t is None:
                continue
            by_group[m.group_label].append(TeamInput(
                team_id=t.id,
                name=t.canonical_name,
                country_code=t.country_code,
            ))
    return by_group


def _select_best_third_placed(
    third_placed: list[tuple[str, "_StandingRowLike"]],
) -> list[tuple[str, "_StandingRowLike"]]:
    """Pick the 8 best third-placed teams by FIFA tiebreakers.

    Sort key: points desc, GD desc, GF desc, goals_for (already counted),
    then group label asc as deterministic fallback (substitutes for the
    fair-play/lottery tiebreakers FIFA uses, which we don't model).
    """
    return sorted(
        third_placed,
        key=lambda gr: (-gr[1].points, -gr[1].goal_diff, -gr[1].goals_for, gr[0]),
    )[:8]


# Type alias kept loose to avoid a forward-import dance with group_standings.
_StandingRowLike = "object"


def _assign_third_placed_to_slots(
    qualifiers: list[tuple[str, _StandingRowLike]],
) -> dict[int, _StandingRowLike]:
    """Assign 8 third-placed teams to R32 slots 74/77/79/80/81/82/85/87.

    Greedy in match-id order: for each slot whose `("3", group_set)`
    constraint must be satisfied, pick the highest-ranked remaining
    third-placed team from an eligible group. This deterministic rule
    is one of 495 valid FIFA scenarios; the choice doesn't affect
    aggregate champion/finals percentages materially because the
    R32-side opponents the third-placed teams face vary little in
    Elo across eligible group sets.
    """
    third_slots = [(mid, side_b[1]) for (mid, _, side_b) in _R32_SLOTS if side_b[0] == "3"]
    # qualifiers is already sorted (best to worst); iterate in slot order.
    available = list(qualifiers)
    out: dict[int, _StandingRowLike] = {}
    for mid, group_set in third_slots:
        for idx, (group_label, row) in enumerate(available):
            if group_label in group_set:
                out[mid] = row
                available.pop(idx)
                break
        else:
            # Shouldn't happen with a real WC bracket, but if it does
            # (e.g. weird input data), fall back to picking the next
            # available qualifier regardless of group constraint.
            if available:
                out[mid] = available.pop(0)[1]
    return out


# ── Knockout simulation ───────────────────────────────────────────────────────


def _sample_knockout_winner(
    home_id: int,
    away_id: int,
    elo: dict[int, float],
    rng: np.random.Generator,
) -> tuple[int, int]:
    """Return (winner_id, loser_id) for a single neutral-venue KO match.

    Uses the Bradley-Terry / Elo win-expectancy directly, skipping the
    draw model since knockouts are decided on the day. Updates `elo`
    in place using update_elo with K=60 (assumed 1-goal margin since
    we don't simulate scorelines past the H/A flag).
    """
    e_h = _expected_home(elo[home_id], elo[away_id], is_neutral=True)
    if rng.random() < e_h:
        winner, loser = home_id, away_id
        hg, ag = 1, 0
    else:
        winner, loser = away_id, home_id
        hg, ag = 0, 1

    new_h, new_a = update_elo(
        elo[home_id], elo[away_id], hg, ag,
        k_constant=WC_K_KNOCKOUT, is_neutral=True,
    )
    elo[home_id] = new_h
    elo[away_id] = new_a
    return winner, loser


def _resolve_r32_pairs(
    standings: dict[str, list],  # group_label -> sorted [StandingRow]
    third_assigned: dict[int, _StandingRowLike],
) -> list[tuple[int, int, int]]:
    """Build the 16 R32 matchups as (match_id, home_team_id, away_team_id)."""
    out = []
    for mid, side_a, side_b in _R32_SLOTS:
        team_a = _resolve_side(side_a, standings, third_assigned, mid)
        team_b = _resolve_side(side_b, standings, third_assigned, mid)
        out.append((mid, team_a, team_b))
    return out


def _resolve_side(side, standings, third_assigned, match_id) -> int:
    kind = side[0]
    if kind == "W":
        return standings[side[1]][0].team_id
    if kind == "R":
        return standings[side[1]][1].team_id
    if kind == "3":
        row = third_assigned[match_id]
        return row.team_id
    raise RuntimeError(f"Unknown side spec: {side!r}")


def _simulate_knockouts(
    r32_pairs: list[tuple[int, int, int]],
    elo_in: dict[int, float],
    rng: np.random.Generator,
) -> dict[str, set[int]]:
    """Run R32 → Final on a fresh copy of `elo_in`. Return reach-stage sets.

    Output keys: 'r32', 'r16', 'qf', 'sf', 'final', 'champion'.
    Each value is a set of team_ids that reached that round (champion is
    a 1-element set).
    """
    elo = dict(elo_in)  # in-sim copy

    reached = {
        STAGE_R32: set(),
        STAGE_R16: set(),
        STAGE_QF: set(),
        STAGE_SF: set(),
        STAGE_FINAL: set(),
        "champion": set(),
    }

    # R32: every team in the 16 pairs reaches R32.
    winners_by_match: dict[int, int] = {}
    losers_by_match: dict[int, int] = {}
    for mid, h, a in r32_pairs:
        reached[STAGE_R32].add(h)
        reached[STAGE_R32].add(a)
        w, l = _sample_knockout_winner(h, a, elo, rng)
        winners_by_match[mid] = w
        losers_by_match[mid] = l

    # R16
    for mid, src_a, src_b in _R16_PAIRS:
        h, a = winners_by_match[src_a], winners_by_match[src_b]
        reached[STAGE_R16].add(h)
        reached[STAGE_R16].add(a)
        w, l = _sample_knockout_winner(h, a, elo, rng)
        winners_by_match[mid] = w
        losers_by_match[mid] = l

    # QF
    for mid, src_a, src_b in _QF_PAIRS:
        h, a = winners_by_match[src_a], winners_by_match[src_b]
        reached[STAGE_QF].add(h)
        reached[STAGE_QF].add(a)
        w, l = _sample_knockout_winner(h, a, elo, rng)
        winners_by_match[mid] = w
        losers_by_match[mid] = l

    # SF
    for mid, src_a, src_b in _SF_PAIRS:
        h, a = winners_by_match[src_a], winners_by_match[src_b]
        reached[STAGE_SF].add(h)
        reached[STAGE_SF].add(a)
        w, l = _sample_knockout_winner(h, a, elo, rng)
        winners_by_match[mid] = w
        losers_by_match[mid] = l

    # Final
    fmid, src_a, src_b = _FINAL_PAIR
    h, a = winners_by_match[src_a], winners_by_match[src_b]
    reached[STAGE_FINAL].add(h)
    reached[STAGE_FINAL].add(a)
    w, l = _sample_knockout_winner(h, a, elo, rng)
    reached["champion"].add(w)

    return reached, winners_by_match, losers_by_match


# ── Top-level entrypoint ──────────────────────────────────────────────────────


def simulate_world_cup(
    db: Session,
    n_sims: int = 10_000,
    seed: int = 42,
) -> TournamentSimResult:
    """Run `n_sims` Monte Carlo runs and return aggregated projections.

    Args:
      db: open SQLAlchemy session.
      n_sims: number of independent simulations. 10k is plenty for stable
              top-N percentages on 48 teams; 1k is fine for smoke checks.
      seed: master seed for the numpy Generator. Same seed → same result.
    """
    if n_sims <= 0:
        raise ValueError(f"n_sims must be positive, got {n_sims}")

    started = time.perf_counter()
    rng = np.random.default_rng(seed)

    league_id, matches, teams_by_id, preds_by_match, elo_initial = _load_wc_data(db)
    rosters = _build_group_rosters(matches, teams_by_id)

    if len(rosters) != 12:
        logger.warning(
            "Expected 12 WC groups but found %d (%s). "
            "Sim will run but may not reflect a complete tournament.",
            len(rosters), sorted(rosters.keys()),
        )

    # Per-team reach counters
    n_teams = len(teams_by_id)
    team_id_list = sorted(teams_by_id.keys())
    team_idx = {tid: i for i, tid in enumerate(team_id_list)}
    counts = {
        STAGE_R32: np.zeros(n_teams, dtype=np.int64),
        STAGE_R16: np.zeros(n_teams, dtype=np.int64),
        STAGE_QF: np.zeros(n_teams, dtype=np.int64),
        STAGE_SF: np.zeros(n_teams, dtype=np.int64),
        STAGE_FINAL: np.zeros(n_teams, dtype=np.int64),
        "champion": np.zeros(n_teams, dtype=np.int64),
    }

    # For most-likely-finals pair tally
    finals_pairs: Counter[tuple[int, int]] = Counter()

    # For champion-path reconstruction: for the modal champion, record per-stage
    # (opponent_id) when they reached that stage. We only do this for the most
    # frequent champion; we collect everything keyed by champion_id and then
    # filter at the end. To keep memory bounded, we accumulate per-(champion,
    # stage) opponent counters.
    path_opponents: dict[int, dict[str, Counter[int]]] = defaultdict(
        lambda: {s: Counter() for s in KNOCKOUT_STAGES}
    )

    for sim in range(n_sims):
        # 1) Group stage
        sim_matches_by_group = _simulate_group_stage(matches, preds_by_match, elo_initial, rng)

        standings = {}
        third_placed: list[tuple[str, _StandingRowLike]] = []
        for label, mlist in sim_matches_by_group.items():
            roster = rosters.get(label, [])
            table = compute_group_table(mlist, roster)
            standings[label] = table
            if len(table) >= 3:
                third_placed.append((label, table[2]))

        # 2) Best 8 third-placed
        qualifiers = _select_best_third_placed(third_placed)

        # 3) Bracket assignment for third-placed slots
        third_assigned = _assign_third_placed_to_slots(qualifiers)

        # 4) Build R32 pairs
        try:
            r32_pairs = _resolve_r32_pairs(standings, third_assigned)
        except (KeyError, IndexError) as e:
            # Group missing teams — log once, skip this sim. In a healthy
            # WC dataset this should never trigger.
            if sim == 0:
                logger.warning("Sim %d: bracket resolution failed (%s). Skipping.", sim, e)
            continue

        # 5) Knockouts — sample winners round by round
        reached, winners_by_match, _ = _simulate_knockouts(r32_pairs, elo_initial, rng)

        # 6) Tally
        for stage, ids in reached.items():
            for tid in ids:
                counts[stage][team_idx[tid]] += 1

        # Finals pair (champion, runner-up)
        fmid, src_a, src_b = _FINAL_PAIR
        finalists = sorted(reached[STAGE_FINAL])
        # Recover champion + runner-up explicitly
        champion_id = next(iter(reached["champion"]))
        runner_up_id = next(t for t in reached[STAGE_FINAL] if t != champion_id)
        finals_pairs[(champion_id, runner_up_id)] += 1

        # Per-champion path opponent counters
        # Reconstruct by walking the bracket forward and recording who the
        # champion played at each stage.
        path = _walk_path_for_team(champion_id, r32_pairs, winners_by_match)
        for stage, opp_id in path.items():
            if opp_id is not None:
                path_opponents[champion_id][stage][opp_id] += 1

    elapsed = time.perf_counter() - started
    logger.info("simulate_world_cup: %d sims in %.2fs (%.1f sims/s)",
                n_sims, elapsed, n_sims / elapsed if elapsed > 0 else 0)

    # ── Build per-team projections ────────────────────────────────────────────
    per_team: list[TeamProjection] = []
    for tid in team_id_list:
        i = team_idx[tid]
        t = teams_by_id[tid]
        per_team.append(TeamProjection(
            team_id=tid,
            name=t.canonical_name,
            country_code=t.country_code,
            win_tournament_pct=100.0 * counts["champion"][i] / n_sims,
            reach_final_pct=100.0 * counts[STAGE_FINAL][i] / n_sims,
            reach_semis_pct=100.0 * counts[STAGE_SF][i] / n_sims,
            reach_qf_pct=100.0 * counts[STAGE_QF][i] / n_sims,
            reach_r16_pct=100.0 * counts[STAGE_R16][i] / n_sims,
            reach_r32_pct=100.0 * counts[STAGE_R32][i] / n_sims,
        ))

    per_team.sort(key=lambda p: -p.win_tournament_pct)

    # ── Most-likely finals pairs ──────────────────────────────────────────────
    most_likely_finals: list[FinalsProjection] = []
    for (champ_id, ru_id), freq in finals_pairs.most_common(5):
        ct = teams_by_id[champ_id]
        rt = teams_by_id[ru_id]
        most_likely_finals.append(FinalsProjection(
            champion_team_id=champ_id,
            champion_name=ct.canonical_name,
            champion_country_code=ct.country_code,
            runner_up_team_id=ru_id,
            runner_up_name=rt.canonical_name,
            runner_up_country_code=rt.country_code,
            frequency=freq / n_sims,
        ))

    # ── Modal-champion path ───────────────────────────────────────────────────
    most_likely_champion_id = per_team[0].team_id if per_team else None
    most_likely_champion_path: list[PathStep] = []
    if most_likely_champion_id is not None and most_likely_champion_id in path_opponents:
        opps = path_opponents[most_likely_champion_id]
        n_champion_sims = counts["champion"][team_idx[most_likely_champion_id]]
        for stage in KNOCKOUT_STAGES:
            counter = opps[stage]
            if not counter:
                continue
            opp_id, opp_freq = counter.most_common(1)[0]
            opp_team = teams_by_id.get(opp_id)
            # Win prob under current Elo (initial — no in-sim updates) at neutral.
            e_h = _expected_home(
                elo_initial[most_likely_champion_id],
                elo_initial[opp_id],
                is_neutral=True,
            )
            most_likely_champion_path.append(PathStep(
                stage=stage,
                opponent_team_id=opp_id,
                opponent_name=opp_team.canonical_name if opp_team else None,
                opponent_country_code=opp_team.country_code if opp_team else None,
                win_prob=float(e_h),
                frequency=opp_freq / n_champion_sims if n_champion_sims else 0.0,
            ))

    return TournamentSimResult(
        run_at=datetime.utcnow(),
        n_sims=n_sims,
        seed=seed,
        model_version=SIM_MODEL_VERSION,
        elo_model_version=ELO_MODEL_VERSION,
        per_team=per_team,
        most_likely_finals=most_likely_finals,
        most_likely_champion_id=most_likely_champion_id,
        most_likely_champion_path=most_likely_champion_path,
    )


def _walk_path_for_team(
    team_id: int,
    r32_pairs: list[tuple[int, int, int]],
    winners_by_match: dict[int, int],
) -> dict[str, Optional[int]]:
    """Find the champion's opponent at each stage of one sim.

    Returns {stage: opponent_team_id} for stages the team participated in.
    Stages not reached map to None.
    """
    out = {s: None for s in KNOCKOUT_STAGES}

    # R32: find the slot containing team_id
    r32_match = None
    for mid, h, a in r32_pairs:
        if team_id == h:
            out[STAGE_R32] = a
            r32_match = mid
            break
        if team_id == a:
            out[STAGE_R32] = h
            r32_match = mid
            break

    if r32_match is None or winners_by_match.get(r32_match) != team_id:
        return out

    # Walk forward through the bracket pairs
    def find_next(prev_match_id: int, pairs: list[tuple[int, int, int]]) -> Optional[tuple[int, int]]:
        """Return (next_match_id, opponent_match_id) where prev_match_id feeds in."""
        for mid, src_a, src_b in pairs:
            if src_a == prev_match_id:
                return (mid, src_b)
            if src_b == prev_match_id:
                return (mid, src_a)
        return None

    stage_pairs = [
        (STAGE_R16, _R16_PAIRS),
        (STAGE_QF, _QF_PAIRS),
        (STAGE_SF, _SF_PAIRS),
        (STAGE_FINAL, [_FINAL_PAIR]),
    ]
    cur_match = r32_match
    for stage, pairs in stage_pairs:
        nxt = find_next(cur_match, pairs)
        if nxt is None:
            break
        next_mid, opp_src = nxt
        opp_id = winners_by_match.get(opp_src)
        out[stage] = opp_id
        if winners_by_match.get(next_mid) != team_id:
            break
        cur_match = next_mid

    return out


# ── JSON (de)serialisation ────────────────────────────────────────────────────


def result_to_json(result: TournamentSimResult) -> dict:
    """Convert a TournamentSimResult into a JSON-serialisable dict."""
    return {
        "run_at": result.run_at.isoformat(),
        "n_sims": result.n_sims,
        "seed": result.seed,
        "model_version": result.model_version,
        "elo_model_version": result.elo_model_version,
        "per_team": [asdict(p) for p in result.per_team],
        "most_likely_finals": [asdict(f) for f in result.most_likely_finals],
        "most_likely_champion_id": result.most_likely_champion_id,
        "most_likely_champion_path": [asdict(s) for s in result.most_likely_champion_path],
    }


def result_from_json(data: dict) -> TournamentSimResult:
    """Round-trip the dict produced by `result_to_json`."""
    return TournamentSimResult(
        run_at=datetime.fromisoformat(data["run_at"]),
        n_sims=int(data["n_sims"]),
        seed=int(data["seed"]),
        model_version=data["model_version"],
        elo_model_version=data["elo_model_version"],
        per_team=[TeamProjection(**p) for p in data["per_team"]],
        most_likely_finals=[FinalsProjection(**f) for f in data["most_likely_finals"]],
        most_likely_champion_id=data.get("most_likely_champion_id"),
        most_likely_champion_path=[PathStep(**s) for s in data["most_likely_champion_path"]],
    )
