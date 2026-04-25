"""
tests/test_wc_rationale.py
==========================
Table-driven coverage for services.wc_rationale.generate_winner_rationale.

We construct synthetic `TournamentSimResult`s and minimal Team/TeamElo rows
in the in-memory test DB, then assert that the right facts and key_risk
get produced. The simulator itself is not exercised here — we trust its
shape and only test the templated rationale logic.

Run: `cd saas && conda run -n ml pytest tests/test_wc_rationale.py -v`
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from models.team import Team
from models.team_elo import TeamElo
from services.tournament_simulator import (
    PathStep,
    TeamProjection,
    TournamentSimResult,
)
from services.wc_rationale import (
    HOST_COUNTRY_CODES,
    PRIOR_WC_CHAMPION_NAME,
    generate_winner_rationale,
)


# ── Fixtures helpers ──────────────────────────────────────────────────────────


def _make_team(
    db,
    team_id: int,
    name: str,
    country_code: Optional[str],
    rating: Optional[float],
) -> Team:
    t = Team(
        id=team_id,
        canonical_name=name,
        team_type="national",
        country_code=country_code,
    )
    db.add(t)
    if rating is not None:
        db.add(TeamElo(
            team_id=team_id,
            rating=rating,
            as_of_date=date(2026, 4, 1),
            source="historical_backfill",
        ))
    db.commit()
    return t


def _make_path(
    win_probs: list[float],
    opponent_ids: list[int],
    opponent_names: list[str],
    opponent_codes: Optional[list[Optional[str]]] = None,
) -> list[PathStep]:
    """Build a 5-stage path matching r32 → final."""
    stages = ["r32", "r16", "qf", "sf", "final"]
    if opponent_codes is None:
        opponent_codes = [None] * len(stages)
    return [
        PathStep(
            stage=stages[i],
            opponent_team_id=opponent_ids[i],
            opponent_name=opponent_names[i],
            opponent_country_code=opponent_codes[i],
            win_prob=win_probs[i],
            frequency=1.0,
        )
        for i in range(len(stages))
    ]


def _make_result(
    champion_id: int,
    champion_name: str,
    champion_code: Optional[str],
    win_pct: float,
    reach_final_pct: float,
    reach_semis_pct: float,
    reach_qf_pct: float,
    path: list[PathStep],
) -> TournamentSimResult:
    return TournamentSimResult(
        run_at=datetime(2026, 4, 24, 12, 0, 0),
        n_sims=1000,
        seed=42,
        model_version="wc-mc-v1",
        elo_model_version="wc-elo-v1",
        per_team=[TeamProjection(
            team_id=champion_id,
            name=champion_name,
            country_code=champion_code,
            win_tournament_pct=win_pct,
            reach_final_pct=reach_final_pct,
            reach_semis_pct=reach_semis_pct,
            reach_qf_pct=reach_qf_pct,
            reach_r16_pct=95.0,
            reach_r32_pct=100.0,
        )],
        most_likely_finals=[],
        most_likely_champion_id=champion_id,
        most_likely_champion_path=path,
    )


def _seed_field(db, champion_rating: float, champion_id: int = 100) -> None:
    """Seed a small national-team field so champion ranks 1 by elo."""
    # Other teams are intentionally below the champion for default tests.
    others = [
        (1, "Brazil", "br", 2050.0),
        (2, "France", "fr", 2030.0),
        (3, "England", "gb-eng", 2010.0),
        (4, "Germany", "de", 1990.0),
        (5, "Portugal", "pt", 1970.0),
        (6, "Belgium", "be", 1950.0),
    ]
    for tid, name, cc, r in others:
        if tid == champion_id:
            continue
        _make_team(db, tid, name, cc, r)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_champion_is_top_elo_emits_highest_elo_fact(db):
    """Champion ranked #1 by elo → 'Highest elo' fact present with rank 1."""
    _seed_field(db, champion_rating=2200.0)
    _make_team(db, 100, "Spain", "es", 2200.0)

    path = _make_path(
        win_probs=[0.80, 0.70, 0.60, 0.55, 0.50],
        opponent_ids=[1, 2, 3, 4, 5],
        opponent_names=["Brazil", "France", "England", "Germany", "Portugal"],
    )
    result = _make_result(
        champion_id=100, champion_name="Spain", champion_code="es",
        win_pct=21.87, reach_final_pct=42.1, reach_semis_pct=66.8, reach_qf_pct=91.4,
        path=path,
    )

    r = generate_winner_rationale(db, result)
    assert r is not None
    labels = [f.label for f in r.rationale_facts]
    assert "Highest team rating" in labels
    elo_fact = next(f for f in r.rationale_facts if f.label == "Highest team rating")
    assert elo_fact.rank == 1
    assert elo_fact.value == "2,200"


def test_champion_rank_4_emits_top_elo_only_when_top_3(db):
    """Champion ranked outside top-3 → no 'Top elo' fact, gets 'Underdog'."""
    # Field of 5 others all rated higher than champion.
    others = [
        (1, "Brazil", "br", 2200.0),
        (2, "France", "fr", 2150.0),
        (3, "England", "gb-eng", 2100.0),
        (4, "Germany", "de", 2050.0),
        (5, "Portugal", "pt", 2000.0),
    ]
    for tid, name, cc, r in others:
        _make_team(db, tid, name, cc, r)
    _make_team(db, 100, "Croatia", "hr", 1900.0)  # rank 6

    path = _make_path(
        win_probs=[0.55, 0.52, 0.51, 0.50, 0.50],
        opponent_ids=[1, 2, 3, 4, 5],
        opponent_names=["Brazil", "France", "England", "Germany", "Portugal"],
    )
    result = _make_result(
        champion_id=100, champion_name="Croatia", champion_code="hr",
        win_pct=8.5, reach_final_pct=22.0, reach_semis_pct=40.0, reach_qf_pct=60.0,
        path=path,
    )

    r = generate_winner_rationale(db, result)
    assert r is not None
    labels = [f.label for f in r.rationale_facts]
    assert "Highest team rating" not in labels
    assert "Top-3 team rating" not in labels
    assert "Underdog" in labels
    underdog = next(f for f in r.rationale_facts if f.label == "Underdog")
    assert underdog.rank == 6


def test_champion_rank_3_emits_top_elo_fact(db):
    """Champion at rank 3 → 'Top elo' fact with rank 3."""
    others = [
        (1, "Brazil", "br", 2200.0),
        (2, "France", "fr", 2150.0),
        (4, "Germany", "de", 2050.0),
        (5, "Portugal", "pt", 2000.0),
    ]
    for tid, name, cc, r in others:
        _make_team(db, tid, name, cc, r)
    _make_team(db, 100, "England", "gb-eng", 2100.0)  # rank 3

    path = _make_path(
        win_probs=[0.70, 0.62, 0.55, 0.50, 0.48],
        opponent_ids=[1, 2, 4, 5, 5],
        opponent_names=["Brazil", "France", "Germany", "Portugal", "Portugal"],
    )
    result = _make_result(
        champion_id=100, champion_name="England", champion_code="gb-eng",
        win_pct=14.0, reach_final_pct=30.0, reach_semis_pct=50.0, reach_qf_pct=70.0,
        path=path,
    )

    r = generate_winner_rationale(db, result)
    assert r is not None
    labels = [f.label for f in r.rationale_facts]
    assert "Top-3 team rating" in labels
    top_elo = next(f for f in r.rationale_facts if f.label == "Top-3 team rating")
    assert top_elo.rank == 3
    assert "rank #3" in top_elo.value


def test_strong_knockout_draw_emits_when_all_path_probs_above_threshold(db):
    """All R32+R16+QF win-probs >= 0.55 → 'Strong knockout draw' fact present.

    Soft draw (R32+R16 >= 0.65) is preferred over Strong-KO when both apply,
    so we set R32 just under 0.65 to isolate the strong-KO branch.
    """
    _seed_field(db, champion_rating=2200.0)
    _make_team(db, 100, "Spain", "es", 2200.0)

    path = _make_path(
        win_probs=[0.60, 0.58, 0.56, 0.50, 0.45],   # Soft draw not triggered
        opponent_ids=[1, 2, 3, 4, 5],
        opponent_names=["Brazil", "France", "England", "Germany", "Portugal"],
    )
    result = _make_result(
        champion_id=100, champion_name="Spain", champion_code="es",
        win_pct=21.87, reach_final_pct=42.1, reach_semis_pct=66.8, reach_qf_pct=91.4,
        path=path,
    )

    r = generate_winner_rationale(db, result)
    assert r is not None
    labels = [f.label for f in r.rationale_facts]
    assert "Tough run, but favored" in labels


def test_defending_champion_argentina_present(db):
    """If champion is Argentina → 'Defending champion' fact (WC 2022)."""
    _seed_field(db, champion_rating=2100.0)
    _make_team(db, 100, PRIOR_WC_CHAMPION_NAME, "ar", 2100.0)

    path = _make_path(
        win_probs=[0.75, 0.65, 0.55, 0.50, 0.48],
        opponent_ids=[1, 2, 3, 4, 5],
        opponent_names=["Brazil", "France", "England", "Germany", "Portugal"],
    )
    result = _make_result(
        champion_id=100, champion_name=PRIOR_WC_CHAMPION_NAME, champion_code="ar",
        win_pct=19.25, reach_final_pct=40.0, reach_semis_pct=60.0, reach_qf_pct=80.0,
        path=path,
    )

    r = generate_winner_rationale(db, result)
    assert r is not None
    labels = [f.label for f in r.rationale_facts]
    assert "Defending champion" in labels
    fact = next(f for f in r.rationale_facts if f.label == "Defending champion")
    assert "2022" in fact.value


def test_host_nation_usa_present(db):
    """USA as champion → 'Hosts' fact present."""
    _seed_field(db, champion_rating=1850.0)
    _make_team(db, 100, "United States", "us", 1850.0)

    path = _make_path(
        win_probs=[0.55, 0.52, 0.50, 0.45, 0.45],
        opponent_ids=[1, 2, 3, 4, 5],
        opponent_names=["Brazil", "France", "England", "Germany", "Portugal"],
    )
    result = _make_result(
        champion_id=100, champion_name="United States", champion_code="us",
        win_pct=6.5, reach_final_pct=18.0, reach_semis_pct=32.0, reach_qf_pct=55.0,
        path=path,
    )

    r = generate_winner_rationale(db, result)
    assert r is not None
    assert "us" in HOST_COUNTRY_CODES
    labels = [f.label for f in r.rationale_facts]
    assert "Home advantage" in labels


def test_key_risk_uses_lowest_path_winprob_and_explanation(db):
    """key_risk picks lowest-prob step; explanation tier matches threshold."""
    _seed_field(db, champion_rating=2200.0)
    _make_team(db, 100, "Spain", "es", 2200.0)

    # QF is the bottleneck at 0.51 → "lowest projected win-prob (51%)".
    path = _make_path(
        win_probs=[0.78, 0.65, 0.51, 0.60, 0.58],
        opponent_ids=[1, 2, 3, 4, 5],
        opponent_names=["Brazil", "France", "England", "Germany", "Portugal"],
    )
    result = _make_result(
        champion_id=100, champion_name="Spain", champion_code="es",
        win_pct=21.87, reach_final_pct=42.1, reach_semis_pct=66.8, reach_qf_pct=91.4,
        path=path,
    )

    r = generate_winner_rationale(db, result)
    assert r is not None
    assert r.key_risk is not None
    assert r.key_risk.stage == "qf"
    assert r.key_risk.opponent.name == "England"
    assert r.key_risk.win_prob == 0.51
    assert r.key_risk.explanation == "toss-up — we're 51% favored against England"


def test_reach_final_fact_always_present(db):
    """Reach-final is always included, even when no other facts trigger."""
    # Rank ~5, mid-pack, no host, not Argentina, no soft/strong draw.
    others = [
        (1, "Brazil", "br", 2200.0),
        (2, "France", "fr", 2150.0),
        (3, "England", "gb-eng", 2100.0),
        (4, "Germany", "de", 2050.0),
    ]
    for tid, name, cc, r in others:
        _make_team(db, tid, name, cc, r)
    _make_team(db, 100, "Italy", "it", 2000.0)  # rank 5

    path = _make_path(
        win_probs=[0.54, 0.52, 0.50, 0.48, 0.46],
        opponent_ids=[1, 2, 3, 4, 4],
        opponent_names=["Brazil", "France", "England", "Germany", "Germany"],
    )
    result = _make_result(
        champion_id=100, champion_name="Italy", champion_code="it",
        win_pct=9.0, reach_final_pct=24.5, reach_semis_pct=42.0, reach_qf_pct=65.0,
        path=path,
    )

    r = generate_winner_rationale(db, result)
    assert r is not None
    labels = [f.label for f in r.rationale_facts]
    assert "Reaches final" in labels
    rf = next(f for f in r.rationale_facts if f.label == "Reaches final")
    assert rf.value == "24.5%"


def test_returns_none_when_no_champion(db):
    """Sim with no champion → rationale is None (caller should skip)."""
    result = TournamentSimResult(
        run_at=datetime(2026, 4, 24),
        n_sims=0,
        seed=42,
        model_version="wc-mc-v1",
        elo_model_version="wc-elo-v1",
        per_team=[],
        most_likely_finals=[],
        most_likely_champion_id=None,
        most_likely_champion_path=[],
    )
    assert generate_winner_rationale(db, result) is None
