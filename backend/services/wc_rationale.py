"""
backend/services/wc_rationale.py
=================================
Templated, feature-driven "Why this team will win" rationale generator
for the World Cup 2026 hub's Predicted Winner block.

Inputs come entirely from a `TournamentSimResult` (the Monte Carlo output)
plus a small DB lookup for current Elo rank. No LLM, no randomness — same
sim result + same DB state always yields the same rationale facts.

Frontend renders the structured `WinnerRationale` into the locked mockup's
gold-tinted Predicted Winner card. The backend deliberately does not
assemble a prose paragraph; the frontend stitches one from `rationale_facts`
and `key_risk` so styling/copy stays in the UI layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from models.team import Team
from models.team_elo import TeamElo
from services.tournament_simulator import (
    PathStep,
    TournamentSimResult,
)

# ── Constants ─────────────────────────────────────────────────────────────────

# Hosts of the 2026 tournament (US/Canada/Mexico). Country codes match
# how teams are stored in `teams.country_code`.
HOST_COUNTRY_CODES: frozenset[str] = frozenset({"us", "ca", "mx"})

# Hardcoded prior World Cup champion. Argentina won WC 2022. We compare by
# canonical name to avoid coupling to a numeric team_id.
PRIOR_WC_CHAMPION_NAME = "Argentina"
PRIOR_WC_YEAR = 2022

# Win-prob thresholds used by fact generators.
STRONG_KO_THRESHOLD = 0.55       # all of R32+R16+QF >= this → "Strong knockout draw"
SOFT_DRAW_THRESHOLD = 0.65       # both R32+R16 >= this → "Soft draw"
KEY_RISK_LOW = 0.55              # below → "lowest projected win-prob"
KEY_RISK_MID = 0.65              # 0.55-0.65 → "competitive matchup"

# Cap on number of facts returned (frontend renders 3-5 chips).
MIN_FACTS = 3
MAX_FACTS = 5


# ── Result dataclasses ────────────────────────────────────────────────────────


@dataclass
class TeamRef:
    name: str
    country_code: Optional[str]


@dataclass
class RationaleFact:
    label: str
    value: str
    rank: Optional[int] = None
    icon: Optional[str] = None  # 'trending-up' | 'shield' | 'route' | None


@dataclass
class KeyRisk:
    stage: str
    opponent: TeamRef
    win_prob: float
    explanation: str


@dataclass
class WinnerRationale:
    team: TeamRef
    win_tournament_pct: float
    reach_final_pct: float
    reach_semis_pct: float
    reach_qf_pct: float
    rationale_facts: list[RationaleFact] = field(default_factory=list)
    projected_path: list[PathStep] = field(default_factory=list)
    key_risk: Optional[KeyRisk] = None


# ── DB helpers ────────────────────────────────────────────────────────────────


def _load_national_team_elo_rank(db: Session) -> dict[int, tuple[int, float]]:
    """Return {team_id: (rank_1_indexed, latest_rating)} for national teams.

    Ranks are dense by descending latest rating. Only national teams are
    considered — the elo table also stores club ratings, but champion
    rationale should rank against the WC field's peers.
    """
    national_team_ids = {
        tid for (tid,) in db.query(Team.id).filter(Team.team_type == "national").all()
    }
    if not national_team_ids:
        return {}

    rows = (
        db.query(TeamElo.team_id, TeamElo.rating, TeamElo.as_of_date)
        .filter(TeamElo.team_id.in_(national_team_ids))
        .order_by(TeamElo.team_id, desc(TeamElo.as_of_date))
        .all()
    )

    latest: dict[int, float] = {}
    for team_id, rating, _as_of in rows:
        if team_id not in latest:
            latest[team_id] = float(rating)

    # Sort by rating desc; ties broken by team_id asc for determinism.
    ordered = sorted(latest.items(), key=lambda kv: (-kv[1], kv[0]))
    return {tid: (i + 1, rating) for i, (tid, rating) in enumerate(ordered)}


def _team_ref_for_id(db: Session, team_id: int) -> Optional[TeamRef]:
    t = db.query(Team).filter(Team.id == team_id).first()
    if t is None:
        return None
    return TeamRef(name=t.canonical_name, country_code=t.country_code)


# ── Fact generation ───────────────────────────────────────────────────────────


def _format_elo(rating: float) -> str:
    """Format an Elo rating with thousands-separator and no decimals."""
    return f"{rating:,.0f}"


def _path_by_stage(path: list[PathStep]) -> dict[str, PathStep]:
    return {step.stage: step for step in path}


def _fact_elo(
    rank: Optional[int], rating: Optional[float]
) -> Optional[RationaleFact]:
    """`Highest team rating` (rank 1) or `Top-3 team rating` (rank 2-3)."""
    if rank is None or rating is None:
        return None
    if rank == 1:
        return RationaleFact(
            label="Highest team rating",
            value=_format_elo(rating),
            rank=1,
            icon="trending-up",
        )
    if rank <= 3:
        return RationaleFact(
            label="Top-3 team rating",
            value=f"rank #{rank} · {_format_elo(rating)}",
            rank=rank,
            icon="trending-up",
        )
    return None


def _fact_underdog(
    rank: Optional[int], rating: Optional[float]
) -> Optional[RationaleFact]:
    if rank is None or rank <= 5:
        return None
    value = f"rank #{rank} · upset profile"
    if rating is not None:
        value = f"rank #{rank} · {_format_elo(rating)} · upset profile"
    return RationaleFact(label="Underdog", value=value, rank=rank, icon=None)


def _fact_knockout_draw(path: list[PathStep]) -> Optional[RationaleFact]:
    """`Strong knockout draw` if R32, R16, QF win-probs all >= 0.55."""
    by_stage = _path_by_stage(path)
    needed = ("r32", "r16", "qf")
    if not all(s in by_stage for s in needed):
        return None
    probs = [by_stage[s].win_prob for s in needed]
    if min(probs) < STRONG_KO_THRESHOLD:
        return None

    # Choose value based on which truth is stronger. We don't know
    # opponent rank here, so the "no projected sub-50% before SF" framing
    # is the safe one to assert from path data alone.
    return RationaleFact(
        label="Tough run, but favored",
        value="no projected sub-55% matchup before semis",
        rank=None,
        icon="route",
    )


def _fact_soft_draw(path: list[PathStep]) -> Optional[RationaleFact]:
    """`Soft draw` if R32 and R16 win-probs both >= 0.65."""
    by_stage = _path_by_stage(path)
    if "r32" not in by_stage or "r16" not in by_stage:
        return None
    p_r32 = by_stage["r32"].win_prob
    p_r16 = by_stage["r16"].win_prob
    if p_r32 < SOFT_DRAW_THRESHOLD or p_r16 < SOFT_DRAW_THRESHOLD:
        return None
    return RationaleFact(
        label="Soft path through knockouts",
        value=f"{int(round(p_r32 * 100))}% / {int(round(p_r16 * 100))}% R32 + R16",
        rank=None,
        icon="route",
    )


def _fact_defending_champion(team: TeamRef) -> Optional[RationaleFact]:
    if team.name != PRIOR_WC_CHAMPION_NAME:
        return None
    return RationaleFact(
        label="Defending champion",
        value=f"won WC {PRIOR_WC_YEAR}",
        rank=None,
        icon="shield",
    )


def _fact_host(team: TeamRef) -> Optional[RationaleFact]:
    if team.country_code is None:
        return None
    if team.country_code.lower() not in HOST_COUNTRY_CODES:
        return None
    return RationaleFact(
        label="Home advantage",
        value="host nation, possible HFA boost",
        rank=None,
        icon="shield",
    )


def _fact_reach_final(reach_final_pct: float) -> RationaleFact:
    return RationaleFact(
        label="Reaches final",
        value=f"{reach_final_pct:.1f}%",
        rank=None,
        icon=None,
    )


def _build_facts(
    team: TeamRef,
    reach_final_pct: float,
    path: list[PathStep],
    elo_rank: Optional[int],
    elo_rating: Optional[float],
) -> list[RationaleFact]:
    """Run generators in priority order; keep first MIN..MAX that apply.

    Order matters because we cap at MAX_FACTS and want the most
    informative ones first.
    """
    candidates: list[Optional[RationaleFact]] = [
        _fact_elo(elo_rank, elo_rating),
        _fact_defending_champion(team),
        _fact_host(team),
        _fact_strong_or_soft_draw(path),  # combined to avoid double-counting
        _fact_underdog(elo_rank, elo_rating),
        _fact_reach_final(reach_final_pct),  # always last, always present
    ]
    facts = [f for f in candidates if f is not None]
    # Reach-final is always last but is required — guarantee it's in.
    if not any(f.label == "Reaches final" for f in facts):
        facts.append(_fact_reach_final(reach_final_pct))

    # Cap at MAX_FACTS; pad order is already priority-correct.
    return facts[:MAX_FACTS]


def _fact_strong_or_soft_draw(path: list[PathStep]) -> Optional[RationaleFact]:
    """Prefer `Soft draw` over `Strong knockout draw` when both apply.

    Soft draw is the more specific claim (two early rounds, both >= 65%);
    strong-knockout-draw is a weaker version (three rounds, all >= 55%).
    Returning whichever has the stronger numeric story keeps the chip
    list informative without redundancy.
    """
    soft = _fact_soft_draw(path)
    if soft is not None:
        return soft
    return _fact_knockout_draw(path)


# ── Key risk ──────────────────────────────────────────────────────────────────


def _build_key_risk(
    db: Session, path: list[PathStep]
) -> Optional[KeyRisk]:
    if not path:
        return None
    # Lowest win-prob along the projected path.
    worst = min(path, key=lambda s: s.win_prob)
    if worst.opponent_team_id is None:
        return None

    pct = int(round(worst.win_prob * 100))
    opponent_ref = TeamRef(
        name=worst.opponent_name or f"Team {worst.opponent_team_id}",
        country_code=worst.opponent_country_code,
    )
    opp_name = opponent_ref.name
    # Phrase the explanation so the percentage clearly belongs to OUR side
    # (the modal champion), not the opponent — readers were parsing
    # "Argentina (54%)" as Argentina's win prob rather than ours.
    if worst.win_prob >= 0.55:
        explanation = f"we're {pct}% favored — our closest matchup of the run"
    elif worst.win_prob >= 0.45:
        explanation = f"toss-up — we're {pct}% favored against {opp_name}"
    else:
        explanation = f"upset risk — only {pct}% favored against {opp_name}"
    return KeyRisk(
        stage=worst.stage,
        opponent=opponent_ref,
        win_prob=worst.win_prob,
        explanation=explanation,
    )


# ── Public entrypoint ─────────────────────────────────────────────────────────


def generate_winner_rationale(
    db: Session,
    sim_result: TournamentSimResult,
) -> Optional[WinnerRationale]:
    """Build the structured rationale for the modal champion.

    Returns None if the sim has no champion (e.g. all sims were skipped).
    """
    if sim_result.most_likely_champion_id is None or not sim_result.per_team:
        return None

    champion_id = sim_result.most_likely_champion_id
    top = sim_result.per_team[0]
    if top.team_id != champion_id:
        # Defensive — per_team is sorted by win_pct desc and the sim
        # uses the top entry as `most_likely_champion_id`, but be
        # explicit so a future change doesn't silently mis-attribute.
        top = next(
            (p for p in sim_result.per_team if p.team_id == champion_id),
            top,
        )

    team = TeamRef(name=top.name, country_code=top.country_code)

    # Elo rank lookup (national teams only).
    rank_by_team = _load_national_team_elo_rank(db)
    rank_rating = rank_by_team.get(champion_id)
    elo_rank = rank_rating[0] if rank_rating else None
    elo_rating = rank_rating[1] if rank_rating else None

    facts = _build_facts(
        team=team,
        reach_final_pct=top.reach_final_pct,
        path=sim_result.most_likely_champion_path,
        elo_rank=elo_rank,
        elo_rating=elo_rating,
    )

    key_risk = _build_key_risk(db, sim_result.most_likely_champion_path)

    return WinnerRationale(
        team=team,
        win_tournament_pct=top.win_tournament_pct,
        reach_final_pct=top.reach_final_pct,
        reach_semis_pct=top.reach_semis_pct,
        reach_qf_pct=top.reach_qf_pct,
        rationale_facts=facts,
        projected_path=list(sim_result.most_likely_champion_path),
        key_risk=key_risk,
    )
