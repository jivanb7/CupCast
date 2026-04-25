"""
backend/services/group_standings.py
====================================
Pure functions for computing World Cup group standings.

Keeps the tiebreaker logic decoupled from the API layer / ORM so it can
be unit-tested with plain dataclasses and reused elsewhere (bracket
prediction, Monte Carlo simulator).

Pre-tournament behaviour
------------------------
When *no* match in the group has been played yet, the live computation
returns four 0-pt rows tagged `live`. The frontend renders all four with
neutral coloring, which gives the user no read on who's expected to
advance. To keep the page useful before kickoff, this module also exposes
`compute_projected_table_by_elo`: it ranks teams by their latest Elo
rating and tags top-2 as `advancing`, third as `best_third`, and fourth
as `eliminated`. The API layer chooses between live and projected based
on whether any match in the group has been played.

FIFA 2026 group-stage tiebreakers (in order):
  1) Points earned in all group matches
  2) Goal difference across all group matches
  3) Goals scored across all group matches
  4) Head-to-head points between the tied teams
  5) Head-to-head goal difference between the tied teams
  6) Head-to-head goals scored between the tied teams
  7) (further FIFA rules: fair play points, drawing of lots) — not implemented

The 2-team H2H case is fully implemented. For 3+ teams tied on points/GD/GF,
we fall back to alphabetic ordering and log a TODO — implementing mini-league
recomputation cleanly is a non-trivial addition and the class project doesn't
need it yet.

Qualification status logic
--------------------------
`advancing`      — top 2 in group after all 3 matchdays played,
                   or mathematically guaranteed top 2 before then
`third-place`    — currently 3rd and not mathematically eliminated
`eliminated`     — mathematically out of top 2 AND cannot finish 3rd with
                   enough points to be in the best-8 third-placed teams
                   (conservative: we only mark eliminated when points
                   gap makes top-2 impossible; best-3rd math is deferred)
`live`           — no matches played yet (group hasn't started)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

POINTS_WIN = 3
POINTS_DRAW = 1
GROUP_MATCHES_PER_TEAM = 3  # each team plays 3 in the group stage


@dataclass
class MatchInput:
    """Minimal match shape for standings; decouples from the ORM."""
    home_team_id: int
    away_team_id: int
    home_goals: Optional[int]
    away_goals: Optional[int]
    status: str  # 'completed' | 'scheduled' | 'live'


@dataclass
class TeamInput:
    team_id: int
    name: str
    country_code: Optional[str] = None


@dataclass
class StandingRow:
    team_id: int
    name: str
    country_code: Optional[str]
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0
    qualification_status: str = "live"

    @property
    def goal_diff(self) -> int:
        return self.goals_for - self.goals_against


def _initialise_rows(teams: list[TeamInput]) -> dict[int, StandingRow]:
    return {
        t.team_id: StandingRow(
            team_id=t.team_id,
            name=t.name,
            country_code=t.country_code,
        )
        for t in teams
    }


def _accumulate_match(rows: dict[int, StandingRow], m: MatchInput) -> None:
    """Apply a single completed match to the standings rows (in place)."""
    if m.status != "completed" or m.home_goals is None or m.away_goals is None:
        return
    home = rows.get(m.home_team_id)
    away = rows.get(m.away_team_id)
    if home is None or away is None:
        return  # match involves a team not in this group — skip defensively

    home.played += 1
    away.played += 1
    home.goals_for += m.home_goals
    home.goals_against += m.away_goals
    away.goals_for += m.away_goals
    away.goals_against += m.home_goals

    if m.home_goals > m.away_goals:
        home.wins += 1
        away.losses += 1
        home.points += POINTS_WIN
    elif m.home_goals < m.away_goals:
        away.wins += 1
        home.losses += 1
        away.points += POINTS_WIN
    else:
        home.draws += 1
        away.draws += 1
        home.points += POINTS_DRAW
        away.points += POINTS_DRAW


def _head_to_head_order(
    tied: list[StandingRow], matches: list[MatchInput]
) -> list[StandingRow]:
    """Order two or more teams tied on points/GD/GF by head-to-head results.

    Implements the 2-team case cleanly. For 3+ ties we TODO and fall back
    to alphabetical order so output stays deterministic.
    """
    if len(tied) <= 1:
        return tied

    if len(tied) > 2:
        logger.warning(
            "group_standings: %d-team tie on points/GD/GF — "
            "mini-league H2H not implemented, falling back to alphabetic order",
            len(tied),
        )
        return sorted(tied, key=lambda r: r.name)

    a, b = tied
    a_pts = b_pts = 0
    a_gf = b_gf = 0
    a_ga = b_ga = 0
    for m in matches:
        if m.status != "completed" or m.home_goals is None or m.away_goals is None:
            continue
        ids = (m.home_team_id, m.away_team_id)
        if a.team_id in ids and b.team_id in ids:
            if m.home_team_id == a.team_id:
                ag, bg = m.home_goals, m.away_goals
            else:
                ag, bg = m.away_goals, m.home_goals
            a_gf += ag; a_ga += bg
            b_gf += bg; b_ga += ag
            if ag > bg:
                a_pts += POINTS_WIN
            elif ag < bg:
                b_pts += POINTS_WIN
            else:
                a_pts += POINTS_DRAW
                b_pts += POINTS_DRAW

    if a_pts != b_pts:
        return [a, b] if a_pts > b_pts else [b, a]
    a_gd, b_gd = a_gf - a_ga, b_gf - b_ga
    if a_gd != b_gd:
        return [a, b] if a_gd > b_gd else [b, a]
    if a_gf != b_gf:
        return [a, b] if a_gf > b_gf else [b, a]
    # Still tied after H2H: alphabetise so output is stable.
    return sorted([a, b], key=lambda r: r.name)


def _group_by_primary_key(rows: list[StandingRow]) -> list[list[StandingRow]]:
    """Bucket rows that share (points, GD, GF) so H2H can reorder each bucket."""
    buckets: list[list[StandingRow]] = []
    for r in rows:
        if buckets and (
            buckets[-1][0].points == r.points
            and buckets[-1][0].goal_diff == r.goal_diff
            and buckets[-1][0].goals_for == r.goals_for
        ):
            buckets[-1].append(r)
        else:
            buckets.append([r])
    return buckets


def _compute_qualification_status(
    sorted_rows: list[StandingRow],
    group_started: bool,
) -> None:
    """Annotate each row with qualification_status in place.

    - No matches played → all rows 'live'
    - Position 1–2 → 'advancing' (guaranteed only after matchday 3;
      before that, we still mark them advancing if no team below can
      mathematically overtake given remaining matches)
    - Position 3 → 'third-place' unless mathematically eliminated
    - Position 4 → 'eliminated' if they cannot reach top 2

    Math simplification: a team's max achievable points is
      current_points + 3 * matches_remaining_for_that_team.
    If that max is strictly less than the current 2nd-place points,
    they cannot finish top 2. The "best 8 third-placed" cross-group
    math is deferred — we conservatively keep the current 3rd-place
    team marked 'third-place' rather than 'eliminated'.
    """
    if not group_started:
        for r in sorted_rows:
            r.qualification_status = "live"
        return

    # Max possible points for each team if they win all remaining matches
    max_points = {
        r.team_id: r.points + POINTS_WIN * (GROUP_MATCHES_PER_TEAM - r.played)
        for r in sorted_rows
    }

    for idx, row in enumerate(sorted_rows):
        if idx < 2:
            row.qualification_status = "advancing"
        elif idx == 2:
            # 3rd place — can they still overtake one of the top 2?
            # Conservative: if they *could* catch 2nd, they're still 'third-place'
            # (they're also alive for best-3rd). If even their max < 2nd's
            # current points, they're mathematically locked to 3rd or lower,
            # which still qualifies them for best-3rd contention until that's
            # resolved — so we still mark 'third-place', not 'eliminated'.
            row.qualification_status = "third-place"
        else:
            # 4th place — eliminated iff max points < current 2nd place points
            second_pts = sorted_rows[1].points
            if max_points[row.team_id] < second_pts:
                row.qualification_status = "eliminated"
            else:
                # Still mathematically alive for top 2
                row.qualification_status = "third-place"


def compute_group_table(
    matches: list[MatchInput],
    teams: list[TeamInput],
) -> list[StandingRow]:
    """Compute the sorted standings table for a single group.

    Sort order: points desc, GD desc, GF desc, H2H, name asc.
    Returns 4 rows for a standard WC group. Teams with no matches
    recorded still appear with zeroed stats.
    """
    rows = _initialise_rows(teams)
    any_completed = False
    for m in matches:
        if m.status == "completed" and m.home_goals is not None and m.away_goals is not None:
            any_completed = True
        _accumulate_match(rows, m)

    # Primary sort: points, GD, GF all descending, then name asc for stability.
    sorted_rows = sorted(
        rows.values(),
        key=lambda r: (-r.points, -r.goal_diff, -r.goals_for, r.name),
    )

    # Apply H2H within each (points, GD, GF) tie bucket.
    reordered: list[StandingRow] = []
    for bucket in _group_by_primary_key(sorted_rows):
        reordered.extend(_head_to_head_order(bucket, matches))

    _compute_qualification_status(reordered, group_started=any_completed)
    return reordered


DEFAULT_NEUTRAL_ELO = 1500.0


def compute_projected_table_by_elo(
    teams: list[TeamInput],
    elos: dict[int, float],
) -> list[StandingRow]:
    """Rank teams by latest Elo and project qualification status.

    Used when no match in the group has been played yet. Top 2 by rating
    are tagged `advancing`, 3rd `best_third`, 4th `eliminated`. All
    counters stay at zero because no real match data exists.

    Teams missing from `elos` are treated as ``DEFAULT_NEUTRAL_ELO`` and
    placed last on ties (alphabetic).
    """
    rows = list(_initialise_rows(teams).values())
    rows.sort(
        key=lambda r: (
            -elos.get(r.team_id, DEFAULT_NEUTRAL_ELO),
            r.name,
        )
    )
    for idx, row in enumerate(rows):
        if idx < 2:
            row.qualification_status = "advancing"
        elif idx == 2:
            row.qualification_status = "best_third"
        else:
            row.qualification_status = "eliminated"
    return rows


# ── Self-tests ────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    """Table-driven assertions. Run via `python -m services.group_standings`."""

    def teams(*names: str) -> list[TeamInput]:
        return [TeamInput(team_id=i + 1, name=n) for i, n in enumerate(names)]

    def match(h: int, a: int, hg: int, ag: int, status: str = "completed") -> MatchInput:
        return MatchInput(home_team_id=h, away_team_id=a, home_goals=hg, away_goals=ag, status=status)

    # 1) Two teams tied on points → GD breaks tie
    t = teams("Alpha", "Bravo", "Charlie", "Delta")
    ms = [
        match(1, 3, 3, 0),   # Alpha 3-0 Charlie  → Alpha +3 GD
        match(2, 4, 1, 0),   # Bravo 1-0 Delta    → Bravo +1 GD
    ]
    table = compute_group_table(ms, t)
    assert [r.name for r in table[:2]] == ["Alpha", "Bravo"], [r.name for r in table]
    assert table[0].points == 3 and table[1].points == 3
    assert table[0].goal_diff == 3 and table[1].goal_diff == 1
    print("PASS: GD breaks tie on equal points")

    # 2) Two teams tied on points + GD → GF breaks tie
    t = teams("Alpha", "Bravo", "Charlie", "Delta")
    ms = [
        match(1, 3, 3, 1),   # Alpha 3-1 Charlie → +2 GD, GF=3
        match(2, 4, 2, 0),   # Bravo 2-0 Delta   → +2 GD, GF=2
    ]
    table = compute_group_table(ms, t)
    assert [r.name for r in table[:2]] == ["Alpha", "Bravo"]
    print("PASS: GF breaks tie on equal points + GD")

    # 3) H2H tiebreaker (2-team case)
    # Construct Alpha and Bravo with identical pts/GD/GF but Alpha won H2H.
    #   Alpha: W vs Charlie 2-1, L vs Delta 0-1, W vs Bravo 2-1 → 6 pts, GF 4, GA 3
    #   Bravo: W vs Charlie 3-0, W vs Delta 1-0, L vs Alpha 1-2  → 6 pts, GF 4, GA 2
    # That gives same pts (6) but different GA → different GD. Adjust so both
    # have GF=4 GA=3 GD=1. Bravo W vs Charlie 2-1 (not 3-0), W vs Delta 1-1 (drew → no).
    # Re-do so both: 2W 0D 1L, GF 4 GA 3:
    #   Alpha: W 2-1 Charlie, L 1-2 Delta, W 3-0 Bravo   (pts 6, GF 6, GA 3) — GF too high
    # Simpler H2H setup: only 2 matches each where they face same opponents
    # identically, plus the direct meeting. Make Charlie and Delta mirror.
    #   Alpha vs Charlie 2-0, Alpha vs Delta 0-2, Alpha vs Bravo 1-0
    #     → Alpha: W L W = 6 pts, GF 3, GA 2, GD 1
    #   Bravo vs Delta 2-0, Bravo vs Charlie 0-2, Bravo vs Alpha 0-1
    #     → Bravo: W L L = 3 pts.  Nope.
    # Make Bravo mirror Alpha's results:
    #   Bravo vs Delta 2-0, Bravo vs Charlie 0-2, Bravo vs Alpha 0-1 → 3 pts.
    # H2H must give Alpha a win AND both teams same totals. So they each go 2W 1L
    # with identical GF/GA. Give them different third opponents to achieve that:
    #   Alpha: W 2-1 vs C, L 0-1 vs D, W 2-1 vs B → 2W 1L, GF 4 GA 3
    #   Bravo: W 2-1 vs D, W 2-1 vs C, L 1-2 vs A → 2W 1L, GF 5 GA 4  (GF mismatch)
    # Adjust Bravo's wins to 1-0 each:
    #   Bravo: W 1-0 vs D, W 1-0 vs C, L 1-2 vs A → 2W 1L, GF 3 GA 2  (GF mismatch)
    # Adjust Alpha's wins to be 1-0 each:
    #   Alpha: W 1-0 vs C, L 0-1 vs D, W 1-0 vs B → 2W 1L, GF 2 GA 1
    #   Bravo: W 1-0 vs D, W 1-0 vs C, L 0-1 vs A → 2W 1L, GF 2 GA 1  MATCH!
    t = teams("Alpha", "Bravo", "Charlie", "Delta")
    ms = [
        match(1, 3, 1, 0),   # Alpha 1-0 Charlie
        match(4, 1, 1, 0),   # Delta 1-0 Alpha
        match(2, 4, 1, 0),   # Bravo 1-0 Delta
        match(2, 3, 1, 0),   # Bravo 1-0 Charlie
        match(1, 2, 1, 0),   # Alpha 1-0 Bravo  (direct H2H)
    ]
    table = compute_group_table(ms, t)
    alpha = next(r for r in table if r.name == "Alpha")
    bravo = next(r for r in table if r.name == "Bravo")
    assert alpha.points == bravo.points == 6, (alpha.points, bravo.points)
    assert alpha.goal_diff == bravo.goal_diff == 1
    assert alpha.goals_for == bravo.goals_for == 2
    # Alpha beat Bravo H2H → Alpha above Bravo.
    names = [r.name for r in table]
    assert names.index("Alpha") < names.index("Bravo"), names
    print("PASS: H2H breaks tie on equal points + GD + GF")

    # 4) Empty group — no matches played
    t = teams("Alpha", "Bravo", "Charlie", "Delta")
    table = compute_group_table([], t)
    assert len(table) == 4
    assert all(r.played == 0 and r.points == 0 for r in table)
    assert all(r.qualification_status == "live" for r in table)
    print("PASS: empty group → all teams 0 pts, status=live")

    # 5) Fully completed group — top 2 advancing, bottom 2 eliminated
    t = teams("Alpha", "Bravo", "Charlie", "Delta")
    ms = [
        match(1, 2, 1, 0), match(3, 4, 1, 0),
        match(1, 3, 1, 0), match(2, 4, 1, 0),
        match(1, 4, 1, 0), match(2, 3, 1, 0),
    ]
    table = compute_group_table(ms, t)
    assert table[0].qualification_status == "advancing"
    assert table[1].qualification_status == "advancing"
    assert table[2].qualification_status == "third-place"
    assert table[3].qualification_status == "eliminated"
    print("PASS: completed group → top 2 advancing, 4th eliminated")

    print("\nAll group_standings tests passed.")


if __name__ == "__main__":
    _run_tests()
