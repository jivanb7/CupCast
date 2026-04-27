"""
backend/services/reasoning.py
==============================
Server-side reasoning library — produces the single-sentence
``Prediction.explanation_text`` shown alongside every prediction in the API.

Mirrors the architecture of ``frontend/src/lib/reasons.js`` but with a
smaller, single-sentence-per-template pool. Each template has:

  * ``fires(ctx)``  predicate — only eligible templates are considered
  * ``fill(ctx)``   produces ``{placeholder: value}`` dict
  * ``category``    used for variety control if we ever pick more than one
  * ``weight``      baseline relevance

``generate_explanation(prediction, match)`` returns the best single sentence
for a given prediction. Templates are deterministic given the prediction id
so the explanation is stable across page loads (different from the
frontend's per-visit rotation, which is intentional — the persisted DB row
should not flicker).

Adding a new signal is a one-line addition to ``_build_context``; templates
that gate on it can then ``fires`` against ``ctx``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────
# Context
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class _Ctx:
    home: str
    away: str
    call_team: str
    call_key: str  # 'H' | 'D' | 'A'
    call_conf: int  # 0..100
    edge_pp: float  # in percentage points
    is_value_pick: bool
    fair_odds: float
    market_odds: float
    league_code: str
    league_name: str
    stage: Optional[str]
    status: str
    prob_h: int
    prob_d: int
    prob_a: int
    spread: int
    is_tight: bool
    is_decisive: bool
    draw_high: bool
    has_market_odds: bool
    venue: Optional[str]


def _build_context(prediction, match) -> Optional[_Ctx]:
    if prediction is None or match is None:
        return None

    pH = float(prediction.prob_home_win or 0.0)
    pD = float(prediction.prob_draw or 0.0)
    pA = float(prediction.prob_away_win or 0.0)

    # Round to integer percentages summing to 100 (largest-remainder).
    raw = [pH * 100, pD * 100, pA * 100]
    total = sum(raw)
    if total < 1:
        h_pp, d_pp, a_pp = 34, 33, 33
    else:
        floors = [int(x) for x in raw]
        remainders = sorted(((i, raw[i] - floors[i]) for i in range(3)), key=lambda kv: -kv[1])
        drift = 100 - sum(floors)
        for k in range(min(drift, 3)):
            floors[remainders[k][0]] += 1
        h_pp, d_pp, a_pp = floors

    def _team_name(t):
        if t is None:
            return None
        # Team model uses canonical_name; tolerate either to keep this
        # importable from contexts that pass a SimpleNamespace shim.
        return getattr(t, "canonical_name", None) or getattr(t, "name", None)

    home_name = _team_name(getattr(match, "home_team", None)) or "Home"
    away_name = _team_name(getattr(match, "away_team", None)) or "Away"

    call_key = (prediction.predicted_result or "H").upper()
    if call_key == "H":
        call_team = home_name
        call_pp = h_pp
    elif call_key == "A":
        call_team = away_name
        call_pp = a_pp
    else:
        call_team = "Draw"
        call_pp = d_pp

    sorted_pp = sorted([h_pp, d_pp, a_pp], reverse=True)
    spread = sorted_pp[0] - sorted_pp[1]

    edge_field = {"H": "edge_home", "D": "edge_draw", "A": "edge_away"}.get(call_key, "edge_home")
    edge_raw = getattr(prediction, edge_field, None)
    edge_pp = round(float(edge_raw) * 100, 1) if edge_raw is not None else 0.0

    fair = round(100.0 / call_pp, 2) if call_pp > 0 else 0.0
    if prediction.odds_home or prediction.odds_draw or prediction.odds_away:
        market = (
            prediction.odds_home if call_key == "H"
            else prediction.odds_away if call_key == "A"
            else prediction.odds_draw
        )
        market = float(market) if market else 0.0
    else:
        market = 0.0

    league = getattr(match, "league", None)
    return _Ctx(
        home=home_name,
        away=away_name,
        call_team=call_team,
        call_key=call_key,
        call_conf=call_pp,
        edge_pp=edge_pp,
        is_value_pick=bool(prediction.is_value_pick),
        fair_odds=fair,
        market_odds=market,
        league_code=getattr(league, "code", "") or "",
        league_name=getattr(league, "name", "") or "",
        stage=getattr(match, "stage", None),
        status=str(getattr(match, "status", "scheduled") or "scheduled").lower(),
        prob_h=h_pp,
        prob_d=d_pp,
        prob_a=a_pp,
        spread=spread,
        is_tight=spread < 8,
        is_decisive=spread >= 25,
        draw_high=d_pp >= 30,
        has_market_odds=market > 0,
        venue=None,  # backend has no venue column today
    )


# ─────────────────────────────────────────────────────────────────────────
# Template pool — single-sentence explanations
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class _Tmpl:
    id: str
    category: str
    weight: float
    fires: Callable[[_Ctx], bool]
    template: str
    fill: Callable[[_Ctx], Dict[str, Any]]


def _pp(n: float) -> str:
    """+1.5 → '+1.5'; -0.4 → '-0.4'."""
    return f"{n:+.1f}"


_TEMPLATES: List[_Tmpl] = [
    _Tmpl(
        id="value-strong",
        category="market",
        weight=1.6,
        fires=lambda c: c.is_value_pick and c.edge_pp >= 5 and c.has_market_odds,
        template=(
            "Model has {call} at {fair}; book has them at {book} — "
            "{edge} points of daylight, well past the noise floor."
        ),
        fill=lambda c: {
            "call": c.call_team,
            "fair": f"{c.fair_odds:.2f}",
            "book": f"{c.market_odds:.2f}",
            "edge": _pp(c.edge_pp),
        },
    ),
    _Tmpl(
        id="value-medium",
        category="market",
        weight=1.2,
        fires=lambda c: c.is_value_pick and 3 <= c.edge_pp < 5 and c.has_market_odds,
        template="Modest edge but real: book {book}, fair {fair} — {edge} points clear of calibration error.",
        fill=lambda c: {
            "fair": f"{c.fair_odds:.2f}",
            "book": f"{c.market_odds:.2f}",
            "edge": _pp(c.edge_pp),
        },
    ),
    _Tmpl(
        id="market-agree",
        category="market",
        weight=0.8,
        fires=lambda c: not c.is_value_pick and abs(c.edge_pp) < 1.0 and c.has_market_odds,
        template="Book and model agree within a percentage point — no value to mine, just a read.",
        fill=lambda c: {},
    ),
    _Tmpl(
        id="draw-bias",
        category="market",
        weight=1.0,
        fires=lambda c: c.draw_high and c.call_key == "D",
        template="Draw bucket sits at {drawP}%, high enough that splitting the points is genuinely on the table.",
        fill=lambda c: {"drawP": c.prob_d},
    ),
    _Tmpl(
        id="prob-tight",
        category="prob",
        weight=0.7,
        fires=lambda c: c.is_tight and c.call_conf < 45,
        template=(
            "Tight numbers — top two outcomes inside {spread}; "
            "any single break of play decides this one."
        ),
        fill=lambda c: {"spread": "1 point" if c.spread == 1 else f"{c.spread} points"},
    ),
    _Tmpl(
        id="prob-decisive",
        category="prob",
        weight=1.1,
        fires=lambda c: c.is_decisive and c.call_key != "D",
        template="{call} the heavy favourite at {conf}% — simulations rarely give the other side enough.",
        fill=lambda c: {"call": c.call_team, "conf": c.call_conf},
    ),
    _Tmpl(
        id="prob-three-way",
        category="prob",
        weight=0.7,
        fires=lambda c: c.prob_h > 25 and c.prob_d > 25 and c.prob_a > 25,
        template="Every outcome lives — H/D/A in a {lo}–{hi}% band; none of the three is unusual here.",
        fill=lambda c: {
            "lo": min(c.prob_h, c.prob_d, c.prob_a),
            "hi": max(c.prob_h, c.prob_d, c.prob_a),
        },
    ),
    _Tmpl(
        id="prob-low-call",
        category="prob",
        weight=0.9,
        fires=lambda c: c.call_conf < 38 and c.call_key != "D",
        template="Sub-40% call — published because no other outcome is higher, not because the model is loud.",
        fill=lambda c: {},
    ),
    _Tmpl(
        id="prob-very-high",
        category="prob",
        weight=0.7,
        fires=lambda c: c.call_conf >= 70,
        template="Calls north of 70% are rare — form, venue, and priors all stacking the same way.",
        fill=lambda c: {},
    ),
    _Tmpl(
        id="league-ucl",
        category="league",
        weight=1.0,
        fires=lambda c: c.league_code == "ucl",
        template="Champions League nights compress the priors — knockout matches land closer to 50/50 than league form suggests.",
        fill=lambda c: {},
    ),
    _Tmpl(
        id="league-wc",
        category="league",
        weight=1.1,
        fires=lambda c: c.league_code == "worldcup",
        template="World Cup priors lean on national-team Elo, not club form — model volume shifts during the tournament.",
        fill=lambda c: {},
    ),
    _Tmpl(
        id="league-laliga",
        category="league",
        weight=0.95,
        fires=lambda c: c.league_code == "laliga",
        template="La Liga produces tighter scorelines than the model used to price — draw bucket gets a small uplift.",
        fill=lambda c: {},
    ),
    _Tmpl(
        id="league-seriea",
        category="league",
        weight=0.95,
        fires=lambda c: c.league_code == "seriea",
        template="Serie A is the lowest-scoring league in the dataset — totals models drift under, prob models lean toward draws.",
        fill=lambda c: {},
    ),
    _Tmpl(
        id="league-bundesliga",
        category="league",
        weight=0.95,
        fires=lambda c: c.league_code == "bundesliga",
        template="Bundesliga matches average more goals than any league we track — variance is wider in both directions.",
        fill=lambda c: {},
    ),
    _Tmpl(
        id="league-epl",
        category="league",
        weight=0.95,
        fires=lambda c: c.league_code == "epl",
        template="Premier League is the most-calibrated league in the model — every probability bucket has the largest sample.",
        fill=lambda c: {},
    ),
    _Tmpl(
        id="stage-knockout",
        category="tournament",
        weight=1.0,
        fires=lambda c: bool(c.stage) and re.search(r"qf|sf|final|r16|r32", c.stage or "", re.I) is not None,
        template="{stage} matches favour the higher-confidence side less than league fixtures — single-game variance is bigger.",
        fill=lambda c: {"stage": (c.stage or "").upper()},
    ),
    _Tmpl(
        id="home-call-clear",
        category="prob",
        weight=0.7,
        fires=lambda c: c.call_key == "H" and (c.prob_h - c.prob_a) >= 15,
        template="Home call by a clear margin — venue, form, and priors all stacking the same way.",
        fill=lambda c: {},
    ),
    _Tmpl(
        id="away-override-home",
        category="prob",
        weight=0.9,
        fires=lambda c: c.call_key == "A" and (c.prob_a - c.prob_h) >= 8,
        template="Away call against the home shade — model sees enough in {call} to override the venue prior.",
        fill=lambda c: {"call": c.call_team},
    ),
    _Tmpl(
        id="catchall",
        category="meta",
        weight=0.1,
        fires=lambda c: True,
        template="{call} the call at {conf}% — the strongest of the three buckets the model produced.",
        fill=lambda c: {"call": c.call_team, "conf": c.call_conf},
    ),
]


def _hash_seed(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def _jitter(template_id: str, seed: int) -> float:
    h = _hash_seed(f"{template_id}:{seed}")
    # [-0.5, +0.5] — wide enough that templates with similar weights actually
    # trade wins across the slate so explanations don't all look identical.
    return (h / 0xFFFFFFFF) * 1.0 - 0.5


def _fill(template: str, vars: Dict[str, Any]) -> str:
    def repl(match: re.Match) -> str:
        k = match.group(1)
        return str(vars[k]) if k in vars else match.group(0)

    return re.sub(r"\{(\w+)\}", repl, template)


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────

def generate_explanation(prediction, match) -> Optional[str]:
    """Produce a single-sentence explanation for a Prediction + Match pair.

    Returns None if there's not enough data to build a context (e.g. the
    prediction is missing required probability fields).
    """
    ctx = _build_context(prediction, match)
    if ctx is None:
        return None

    eligible: List[_Tmpl] = []
    for t in _TEMPLATES:
        try:
            if t.fires(ctx):
                eligible.append(t)
        except Exception:
            continue

    if not eligible:
        return None

    # Daily-rotating seed: day-of-year + prediction.id. This means a fresh
    # backfill on a new calendar day picks a different template; same day
    # backfills are idempotent. Pair this with a daily admin cron that re-
    # runs the backfill so explanation_text stays fresh without flickering
    # mid-session for any one user.
    import datetime as _dt
    today = _dt.date.today()
    seed = _hash_seed(f"pred:{getattr(prediction, 'id', '')}:{today.toordinal()}")
    eligible.sort(key=lambda t: -(t.weight + _jitter(t.id, seed)))
    pick = eligible[0]

    try:
        vars = pick.fill(ctx) or {}
    except Exception:
        vars = {}
    text = _fill(pick.template, vars)
    return text.strip() or None


def template_count() -> int:
    """Diagnostic — for the admin endpoint to report template-pool size."""
    return len(_TEMPLATES)


__all__ = ["generate_explanation", "template_count"]
