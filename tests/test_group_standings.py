"""
tests/test_group_standings.py
==============================
Table-driven tests for services/group_standings.compute_group_table.

Focuses on tiebreaker ordering because that's where the subtle logic lives.
Run with: `cd saas && conda run -n ml pytest tests/test_group_standings.py -v`
"""

from services.group_standings import (
    MatchInput,
    TeamInput,
    compute_group_table,
    compute_projected_table_by_elo,
)


def _teams(*names: str) -> list[TeamInput]:
    return [TeamInput(team_id=i + 1, name=n) for i, n in enumerate(names)]


def _match(h: int, a: int, hg: int, ag: int, status: str = "completed") -> MatchInput:
    return MatchInput(
        home_team_id=h, away_team_id=a,
        home_goals=hg, away_goals=ag, status=status,
    )


def test_equal_points_goal_difference_breaks_tie():
    teams = _teams("Alpha", "Bravo", "Charlie", "Delta")
    matches = [
        _match(1, 3, 3, 0),  # Alpha 3-0 Charlie → +3 GD
        _match(2, 4, 1, 0),  # Bravo 1-0 Delta   → +1 GD
    ]
    table = compute_group_table(matches, teams)
    assert [r.name for r in table[:2]] == ["Alpha", "Bravo"]
    assert table[0].points == 3 and table[1].points == 3
    assert table[0].goal_diff > table[1].goal_diff


def test_equal_points_and_gd_goals_for_breaks_tie():
    teams = _teams("Alpha", "Bravo", "Charlie", "Delta")
    matches = [
        _match(1, 3, 3, 1),  # Alpha +2 GD, GF 3
        _match(2, 4, 2, 0),  # Bravo +2 GD, GF 2
    ]
    table = compute_group_table(matches, teams)
    assert [r.name for r in table[:2]] == ["Alpha", "Bravo"]
    assert table[0].goal_diff == table[1].goal_diff
    assert table[0].goals_for > table[1].goals_for


def test_equal_points_gd_gf_head_to_head_breaks_tie():
    # Alpha and Bravo each go 2W 1L with GF=2, GA=1, GD=1. Alpha beat Bravo H2H.
    teams = _teams("Alpha", "Bravo", "Charlie", "Delta")
    matches = [
        _match(1, 3, 1, 0),  # Alpha 1-0 Charlie
        _match(4, 1, 1, 0),  # Delta 1-0 Alpha
        _match(2, 4, 1, 0),  # Bravo 1-0 Delta
        _match(2, 3, 1, 0),  # Bravo 1-0 Charlie
        _match(1, 2, 1, 0),  # Alpha 1-0 Bravo  — head-to-head
    ]
    table = compute_group_table(matches, teams)
    alpha = next(r for r in table if r.name == "Alpha")
    bravo = next(r for r in table if r.name == "Bravo")
    assert alpha.points == bravo.points == 6
    assert alpha.goal_diff == bravo.goal_diff
    assert alpha.goals_for == bravo.goals_for
    names = [r.name for r in table]
    assert names.index("Alpha") < names.index("Bravo")


def test_empty_group_all_zero_points_status_live():
    teams = _teams("Alpha", "Bravo", "Charlie", "Delta")
    table = compute_group_table([], teams)
    assert len(table) == 4
    assert all(r.played == 0 for r in table)
    assert all(r.points == 0 for r in table)
    assert all(r.qualification_status == "live" for r in table)


def test_completed_group_top_two_advancing_fourth_eliminated():
    teams = _teams("Alpha", "Bravo", "Charlie", "Delta")
    matches = [
        _match(1, 2, 1, 0), _match(3, 4, 1, 0),
        _match(1, 3, 1, 0), _match(2, 4, 1, 0),
        _match(1, 4, 1, 0), _match(2, 3, 1, 0),
    ]
    table = compute_group_table(matches, teams)
    # All 4 teams end on different outcomes in this symmetric setup.
    assert table[0].qualification_status == "advancing"
    assert table[1].qualification_status == "advancing"
    assert table[2].qualification_status == "third-place"
    assert table[3].qualification_status == "eliminated"


def test_projected_table_top_two_by_elo_advancing():
    teams = _teams("Alpha", "Bravo", "Charlie", "Delta")
    elos = {1: 1700.0, 2: 1900.0, 3: 1500.0, 4: 1600.0}
    table = compute_projected_table_by_elo(teams, elos)
    assert [r.name for r in table] == ["Bravo", "Alpha", "Delta", "Charlie"]
    assert table[0].qualification_status == "advancing"
    assert table[1].qualification_status == "advancing"
    assert table[2].qualification_status == "best_third"
    assert table[3].qualification_status == "eliminated"
    # No matches played → counters stay zero.
    assert all(r.played == 0 and r.points == 0 for r in table)


def test_projected_table_missing_elo_uses_neutral_default_and_alphabetic_tiebreak():
    teams = _teams("Alpha", "Bravo", "Charlie", "Delta")
    # No Elos at all → all teams equal (1500), alphabetic order wins.
    table = compute_projected_table_by_elo(teams, {})
    assert [r.name for r in table] == ["Alpha", "Bravo", "Charlie", "Delta"]
    assert table[0].qualification_status == "advancing"
    assert table[3].qualification_status == "eliminated"


def test_scheduled_matches_do_not_affect_standings():
    teams = _teams("Alpha", "Bravo", "Charlie", "Delta")
    matches = [
        _match(1, 2, 3, 0),                                # completed, counts
        _match(3, 4, 5, 0, status="scheduled"),            # ignored
        MatchInput(1, 3, None, None, "scheduled"),         # ignored (no score)
    ]
    table = compute_group_table(matches, teams)
    alpha = next(r for r in table if r.name == "Alpha")
    charlie = next(r for r in table if r.name == "Charlie")
    assert alpha.played == 1 and alpha.points == 3
    assert charlie.played == 0 and charlie.points == 0
