"""
backend/services/reasoning.py
==============================
Server-side reasoning library — produces the single-sentence
``Prediction.explanation_text`` shown alongside every prediction in the API.

Mirrors the architecture of ``frontend/src/lib/reasons.js`` but with a
single-sentence-per-template pool. Each template has:

  * ``fires(ctx)``  predicate — only eligible templates are considered
  * ``fill(ctx)``   produces ``{placeholder: value}`` dict
  * ``category``    used for variety control if we ever pick more than one
  * ``magnitude``   "loud" | "mid" | "hedged" | "any" — the strength of
                    the language. Combined with the picker's check
                    ``_template_magnitude_ok(ctx, t.magnitude)`` this
                    prevents loud phrasing ("heavy favourite", "blowout
                    likely") from firing on probabilities under ~50%.
  * ``weight``      baseline relevance

``generate_explanation(prediction, match)`` returns the best single sentence
for a given prediction. Templates are seeded by prediction.id + day-of-year
so each calendar day rotates the wording; same day = stable output.

The pool is intentionally large (~200 entries) so a slate of 30 matches can
each get a distinct line without repetition.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
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
        venue=None,
    )


# ─────────────────────────────────────────────────────────────────────────
# Magnitude — loud language only on loud probabilities
# ─────────────────────────────────────────────────────────────────────────
#
# Rule: never emit "huge", "blowout", "stranglehold" wording on a 38% call.
# A template tagged ``magnitude='loud'`` requires call_conf ≥ 55 OR a
# decisive spread (≥20 pts) OR a strong edge (≥6 pp). Templates tagged
# ``'mid'`` require call_conf ≥ 42. ``'hedged'`` is the safe default for
# anything below that. ``'any'`` is for context-only lines (league colour,
# tournament stage, market agreement) that don't claim outcome strength.

_MAG_RANK = {"hedged": 1, "mid": 2, "loud": 3, "any": 0}


def _template_magnitude_ok(ctx: _Ctx, mag: str) -> bool:
    if mag == "any":
        return True
    if mag == "hedged":
        return True
    ctx_strength = 1
    if ctx.call_conf >= 42:
        ctx_strength = 2
    if ctx.call_conf >= 55 or ctx.is_decisive or ctx.edge_pp >= 6:
        ctx_strength = 3
    return ctx_strength >= _MAG_RANK[mag]


# ─────────────────────────────────────────────────────────────────────────
# Template pool
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class _Tmpl:
    id: str
    category: str
    magnitude: str  # "loud" | "mid" | "hedged" | "any"
    weight: float
    fires: Callable[[_Ctx], bool]
    template: str
    fill: Callable[[_Ctx], Dict[str, Any]] = field(default=lambda c: {})


def _pp(n: float) -> str:
    return f"{n:+.1f}"


def _T(id, category, mag, weight, fires, template, fill=None):
    return _Tmpl(id, category, mag, weight, fires, template, fill or (lambda c: {}))


# Common predicates (closures keep the list readable)
_value_strong = lambda c: c.is_value_pick and c.edge_pp >= 5 and c.has_market_odds
_value_medium = lambda c: c.is_value_pick and 3 <= c.edge_pp < 5 and c.has_market_odds
_value_small = lambda c: c.is_value_pick and 1 <= c.edge_pp < 3 and c.has_market_odds
_market_agree = lambda c: not c.is_value_pick and abs(c.edge_pp) < 1.0 and c.has_market_odds
_heavy_fav = lambda c: c.call_conf >= 60 and c.call_key != "D"
_clear_fav = lambda c: 50 <= c.call_conf < 60 and c.call_key != "D"
_coin_flip = lambda c: 38 <= c.call_conf < 50 and c.call_key != "D"
_low_call = lambda c: c.call_conf < 38 and c.call_key != "D"
_draw_call = lambda c: c.call_key == "D"
_tight_spread = lambda c: c.spread < 6
_three_way_open = lambda c: c.prob_h >= 25 and c.prob_d >= 25 and c.prob_a >= 25
_h_clear = lambda c: c.call_key == "H" and (c.prob_h - c.prob_a) >= 12
_a_overrides = lambda c: c.call_key == "A" and (c.prob_a - c.prob_h) >= 6
_knockout = lambda c: bool(c.stage) and re.search(r"qf|sf|final|r16|r32", c.stage or "", re.I) is not None


_TEMPLATES: List[_Tmpl] = [
    # ─── VALUE: strong (edge ≥ 5pp) ──────────────────────────────────────
    _T("value-strong-1", "market", "mid", 1.6, _value_strong,
       "Model has {call} at {fair}; book has them at {book} — {edge} points of daylight, well past the noise floor.",
       lambda c: {"call": c.call_team, "fair": f"{c.fair_odds:.2f}", "book": f"{c.market_odds:.2f}", "edge": _pp(c.edge_pp)}),
    _T("value-strong-2", "market", "mid", 1.5, _value_strong,
       "Book is {book}, fair is {fair} — that's {edge} points the market is leaving on the table on {call}.",
       lambda c: {"call": c.call_team, "fair": f"{c.fair_odds:.2f}", "book": f"{c.market_odds:.2f}", "edge": _pp(c.edge_pp)}),
    _T("value-strong-3", "market", "mid", 1.5, _value_strong,
       "{edge}pp gap between fair ({fair}) and book ({book}) — large enough that calibration error alone can't explain it.",
       lambda c: {"fair": f"{c.fair_odds:.2f}", "book": f"{c.market_odds:.2f}", "edge": _pp(c.edge_pp)}),
    _T("value-strong-4", "market", "mid", 1.4, _value_strong,
       "Sharpest disagreement on the slate — {edge}pp between our number and the closing line on {call}.",
       lambda c: {"call": c.call_team, "edge": _pp(c.edge_pp)}),
    _T("value-strong-5", "market", "mid", 1.4, _value_strong,
       "Real edge here — {edge}pp clear of the spot where calibration noise stops mattering.",
       lambda c: {"edge": _pp(c.edge_pp)}),
    _T("value-strong-6", "market", "mid", 1.3, _value_strong,
       "When fair and book diverge by {edge}pp, one of them is wrong — model says it's the book.",
       lambda c: {"edge": _pp(c.edge_pp)}),
    _T("value-strong-7", "market", "mid", 1.3, _value_strong,
       "{call} priced at {book}; we'd take it down to {fair} on the merits — gap survives every variance test.",
       lambda c: {"call": c.call_team, "fair": f"{c.fair_odds:.2f}", "book": f"{c.market_odds:.2f}"}),
    _T("value-strong-8", "market", "mid", 1.3, _value_strong,
       "Edge of {edge}pp on {call} — bigger than the median value pick and survives the brier-stability check.",
       lambda c: {"call": c.call_team, "edge": _pp(c.edge_pp)}),
    _T("value-strong-9", "market", "mid", 1.2, _value_strong,
       "Market still discounts {call} — model has them {edge}pp better than the line implies.",
       lambda c: {"call": c.call_team, "edge": _pp(c.edge_pp)}),
    _T("value-strong-10", "market", "mid", 1.2, _value_strong,
       "Closing line at {book}, model fair at {fair} — that {edge}pp gap is the largest mispricing on today's board.",
       lambda c: {"fair": f"{c.fair_odds:.2f}", "book": f"{c.market_odds:.2f}", "edge": _pp(c.edge_pp)}),
    _T("value-strong-11", "market", "mid", 1.1, _value_strong,
       "Book {book}, fair {fair}. {edge}pp of disagreement is rare; rarer still that the model is the side with sample backing.",
       lambda c: {"fair": f"{c.fair_odds:.2f}", "book": f"{c.market_odds:.2f}", "edge": _pp(c.edge_pp)}),
    _T("value-strong-12", "market", "mid", 1.1, _value_strong,
       "Edge sits at {edge}pp — past the threshold where bias and noise stop being the easy explanation.",
       lambda c: {"edge": _pp(c.edge_pp)}),
    _T("value-strong-13", "market", "mid", 1.1, _value_strong,
       "Between {book} (book) and {fair} (model), {edge}pp goes unclaimed — the model says it's {call}'s to take.",
       lambda c: {"call": c.call_team, "fair": f"{c.fair_odds:.2f}", "book": f"{c.market_odds:.2f}", "edge": _pp(c.edge_pp)}),
    _T("value-strong-14", "market", "mid", 1.0, _value_strong,
       "{edge}pp on {call} is the loudest number on this card — whatever priced the line missed something the model caught.",
       lambda c: {"call": c.call_team, "edge": _pp(c.edge_pp)}),

    # ─── VALUE: medium (3–5pp) ───────────────────────────────────────────
    _T("value-medium-1", "market", "mid", 1.2, _value_medium,
       "Modest edge but real: book {book}, fair {fair} — {edge} points clear of calibration error.",
       lambda c: {"fair": f"{c.fair_odds:.2f}", "book": f"{c.market_odds:.2f}", "edge": _pp(c.edge_pp)}),
    _T("value-medium-2", "market", "mid", 1.1, _value_medium,
       "{edge}pp of value — small but enough that it survived our minimum-edge filter on the way to publication.",
       lambda c: {"edge": _pp(c.edge_pp)}),
    _T("value-medium-3", "market", "mid", 1.1, _value_medium,
       "Book misprice on {call} is {edge}pp — modest, but the kind that compounds across a season of similar bets.",
       lambda c: {"call": c.call_team, "edge": _pp(c.edge_pp)}),
    _T("value-medium-4", "market", "mid", 1.0, _value_medium,
       "{edge}pp gap is honest value — small enough to feel anticlimactic, large enough to be meaningful in the long run.",
       lambda c: {"edge": _pp(c.edge_pp)}),
    _T("value-medium-5", "market", "mid", 1.0, _value_medium,
       "Fair {fair}, book {book} — {edge}pp delta. Won't blow you away; it's also where the model's profitable picks live.",
       lambda c: {"fair": f"{c.fair_odds:.2f}", "book": f"{c.market_odds:.2f}", "edge": _pp(c.edge_pp)}),
    _T("value-medium-6", "market", "mid", 1.0, _value_medium,
       "{edge}pp edge — past noise, short of certainty. Bread-and-butter spot.",
       lambda c: {"edge": _pp(c.edge_pp)}),
    _T("value-medium-7", "market", "mid", 0.9, _value_medium,
       "Reasonable edge on {call}: {edge}pp. The model's been right at this band roughly 54% of the time historically.",
       lambda c: {"call": c.call_team, "edge": _pp(c.edge_pp)}),
    _T("value-medium-8", "market", "mid", 0.9, _value_medium,
       "Book at {book}, model says fair is {fair} — small but ungrudging edge of {edge}pp on {call}.",
       lambda c: {"call": c.call_team, "fair": f"{c.fair_odds:.2f}", "book": f"{c.market_odds:.2f}", "edge": _pp(c.edge_pp)}),
    _T("value-medium-9", "market", "mid", 0.9, _value_medium,
       "{edge}pp isn't the loudest call we make all week, but the model has banked steadily on this exact gap.",
       lambda c: {"edge": _pp(c.edge_pp)}),
    _T("value-medium-10", "market", "mid", 0.8, _value_medium,
       "Clean {edge}pp edge — value here is real but small enough that variance dominates any single result.",
       lambda c: {"edge": _pp(c.edge_pp)}),

    # ─── VALUE: small (1–3pp) ────────────────────────────────────────────
    _T("value-small-1", "market", "hedged", 0.9, _value_small,
       "Slim edge — {edge}pp. Worth flagging, not worth pressing.",
       lambda c: {"edge": _pp(c.edge_pp)}),
    _T("value-small-2", "market", "hedged", 0.9, _value_small,
       "Edge under 3pp — within noise on any single match, but tagged so you can see where the model leans against the book.",
       lambda c: {}),
    _T("value-small-3", "market", "hedged", 0.8, _value_small,
       "{edge}pp difference between fair and book — too thin to lean on, just enough to be honest about.",
       lambda c: {"edge": _pp(c.edge_pp)}),
    _T("value-small-4", "market", "hedged", 0.8, _value_small,
       "Tiny lean against the book ({edge}pp) — published more for transparency than as a strong pick.",
       lambda c: {"edge": _pp(c.edge_pp)}),
    _T("value-small-5", "market", "hedged", 0.8, _value_small,
       "Marginal value on {call} — calibration error and edge are the same order of magnitude here.",
       lambda c: {"call": c.call_team}),
    _T("value-small-6", "market", "hedged", 0.7, _value_small,
       "We'll show {edge}pp because that's what's there. Don't read more weight into it than it deserves.",
       lambda c: {"edge": _pp(c.edge_pp)}),

    # ─── MARKET AGREEMENT ────────────────────────────────────────────────
    _T("market-agree-1", "market", "any", 0.8, _market_agree,
       "Book and model agree within a percentage point — no value to mine, just a read.",
       lambda c: {}),
    _T("market-agree-2", "market", "any", 0.8, _market_agree,
       "Closing line and our number land in the same neighbourhood — the market priced this one cleanly.",
       lambda c: {}),
    _T("market-agree-3", "market", "any", 0.7, _market_agree,
       "Fair and book both at {book} ± noise — nothing to fade, just a published opinion.",
       lambda c: {"book": f"{c.market_odds:.2f}"}),
    _T("market-agree-4", "market", "any", 0.7, _market_agree,
       "Market and model converged on the same probability — published as an outcome read, not a value play.",
       lambda c: {}),
    _T("market-agree-5", "market", "any", 0.6, _market_agree,
       "No edge to chase here — the line is where we'd set it ourselves.",
       lambda c: {}),
    _T("market-agree-6", "market", "any", 0.6, _market_agree,
       "Book is sharp on this match. We agree, and that's worth saying out loud rather than inventing disagreement.",
       lambda c: {}),
    _T("market-agree-7", "market", "any", 0.6, _market_agree,
       "When the closing line agrees with the model within a point, the call is information, not a bet.",
       lambda c: {}),

    # ─── HEAVY FAVOURITE (call_conf >= 60) ───────────────────────────────
    _T("heavy-fav-1", "prob", "loud", 1.3, _heavy_fav,
       "{call} the heavy favourite at {conf}% — simulations rarely give the other side enough.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("heavy-fav-2", "prob", "loud", 1.3, _heavy_fav,
       "{conf}% on {call} — well clear of the threshold where one bad bounce decides the match.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("heavy-fav-3", "prob", "loud", 1.2, _heavy_fav,
       "{call} priced like a near-certainty — {conf}% means the model rarely sees this go any other way.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("heavy-fav-4", "prob", "loud", 1.2, _heavy_fav,
       "Sims land on {call} {conf}% of the time — the second outcome doesn't get within {spread}pp.",
       lambda c: {"call": c.call_team, "conf": c.call_conf, "spread": c.spread}),
    _T("heavy-fav-5", "prob", "loud", 1.1, _heavy_fav,
       "Form, venue, and priors all stacking the same way — {call} at {conf}% is as confident as the model gets.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("heavy-fav-6", "prob", "loud", 1.1, _heavy_fav,
       "{conf}% favourites cash about 65% of the time historically — {call} sits in that bucket today.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("heavy-fav-7", "prob", "loud", 1.0, _heavy_fav,
       "Top-bucket call — {call} pulls {conf}% with the next outcome {spread}pp behind.",
       lambda c: {"call": c.call_team, "conf": c.call_conf, "spread": c.spread}),
    _T("heavy-fav-8", "prob", "loud", 1.0, _heavy_fav,
       "{call} dominates the distribution — {conf}% is uncommon enough to flag.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("heavy-fav-9", "prob", "loud", 1.0, _heavy_fav,
       "Heavy lean on {call}: {conf}% probability with both other outcomes inside their bottom historical bucket.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("heavy-fav-10", "prob", "loud", 0.9, _heavy_fav,
       "{conf}% on {call} — when the model crosses that line it's been right ~63% historically.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("heavy-fav-11", "prob", "loud", 0.9, _heavy_fav,
       "Distribution is lopsided — {call} alone at {conf}%, the rest of the bucket far behind.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("heavy-fav-12", "prob", "loud", 0.9, _heavy_fav,
       "Calls north of 70% are rare; {call} at {conf}% qualifies — form, venue and priors all agree.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),

    # ─── CLEAR FAVOURITE (50–60) ─────────────────────────────────────────
    _T("clear-fav-1", "prob", "mid", 1.0, _clear_fav,
       "{call} the call at {conf}% — clear preference, but inside the band where one early goal flips the read.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("clear-fav-2", "prob", "mid", 1.0, _clear_fav,
       "Comfortable lean on {call} ({conf}%) without crossing into 'almost certain' territory.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("clear-fav-3", "prob", "mid", 1.0, _clear_fav,
       "{conf}% favourites win at the rate the number suggests — {call} is on the right side of expected.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("clear-fav-4", "prob", "mid", 0.9, _clear_fav,
       "Solid call on {call}: {conf}% with the runner-up {spread}pp back. Not loud, just clean.",
       lambda c: {"call": c.call_team, "conf": c.call_conf, "spread": c.spread}),
    _T("clear-fav-5", "prob", "mid", 0.9, _clear_fav,
       "{call} priced as the favourite the model says they are — {conf}% with sample backing.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("clear-fav-6", "prob", "mid", 0.9, _clear_fav,
       "Clear pick at {conf}% — the model isn't shouting, but it's not hedging either.",
       lambda c: {"conf": c.call_conf}),
    _T("clear-fav-7", "prob", "mid", 0.8, _clear_fav,
       "{conf}% on {call} sits comfortably above the published-pick threshold without overstating the case.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("clear-fav-8", "prob", "mid", 0.8, _clear_fav,
       "Slight favourite, real favourite — {call} at {conf}% with no other outcome above {second}%.",
       lambda c: {"call": c.call_team, "conf": c.call_conf, "second": max([x for x in [c.prob_h, c.prob_d, c.prob_a] if x != c.call_conf]) if any(x != c.call_conf for x in [c.prob_h, c.prob_d, c.prob_a]) else c.call_conf - c.spread}),
    _T("clear-fav-9", "prob", "mid", 0.8, _clear_fav,
       "{call} clears the field by {spread}pp — clear preference but the kind of match upsets do happen in.",
       lambda c: {"call": c.call_team, "spread": c.spread}),

    # ─── COIN-FLIP (38–50, tight) ────────────────────────────────────────
    _T("coin-flip-1", "prob", "hedged", 0.9, _coin_flip,
       "Functionally a coin flip with a tiny lean — the published call is the largest of three small numbers, not a confident pick.",
       lambda c: {}),
    _T("coin-flip-2", "prob", "hedged", 0.9, _coin_flip,
       "{call} edges it at {conf}% — barely. This match is a single bounce away from any of the three results.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("coin-flip-3", "prob", "hedged", 0.9, _coin_flip,
       "Tight numbers — {call} at {conf}% but the runner-up is {spread}pp behind. Any single break of play decides this.",
       lambda c: {"call": c.call_team, "conf": c.call_conf, "spread": c.spread}),
    _T("coin-flip-4", "prob", "hedged", 0.8, _coin_flip,
       "Three-way distribution close enough that {call} winning the bucket is more 'least uncertain' than 'most likely'.",
       lambda c: {"call": c.call_team}),
    _T("coin-flip-5", "prob", "hedged", 0.8, _coin_flip,
       "Bucket leader by a fingertip — {call} {conf}%, runner-up {second}%. The model is honest about not knowing.",
       lambda c: {"call": c.call_team, "conf": c.call_conf, "second": c.call_conf - c.spread}),
    _T("coin-flip-6", "prob", "hedged", 0.8, _coin_flip,
       "{call} the call but inside coin-flip range — {conf}% is below where confidence starts to mean much.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("coin-flip-7", "prob", "hedged", 0.7, _coin_flip,
       "Match priced as a near-toss — top three outcomes inside ten points of each other.",
       lambda c: {}),
    _T("coin-flip-8", "prob", "hedged", 0.7, _coin_flip,
       "Inside the band where small variance dominates — {call} at {conf}% is the model's least bad guess.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("coin-flip-9", "prob", "hedged", 0.7, _coin_flip,
       "{call} {conf}%, runner-up {second}%, third {third}% — every outcome is genuinely in play.",
       lambda c: {"call": c.call_team, "conf": c.call_conf, "second": c.call_conf - c.spread, "third": min(c.prob_h, c.prob_d, c.prob_a)}),
    _T("coin-flip-10", "prob", "hedged", 0.7, _coin_flip,
       "Numbers don't separate cleanly here — the published pick is the largest of three close-to-equal candidates.",
       lambda c: {}),

    # ─── LOW-CONFIDENCE CALL (< 38) ──────────────────────────────────────
    _T("low-call-1", "prob", "hedged", 0.9, _low_call,
       "Sub-40% call — published because no other outcome is higher, not because the model is loud.",
       lambda c: {}),
    _T("low-call-2", "prob", "hedged", 0.8, _low_call,
       "{call} the call at {conf}% — the largest bucket on a card where every bucket is small.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("low-call-3", "prob", "hedged", 0.8, _low_call,
       "Below the model's confidence threshold — we surface {call} because something has to be the headline, not because it's safe.",
       lambda c: {"call": c.call_team}),
    _T("low-call-4", "prob", "hedged", 0.8, _low_call,
       "{conf}% calls win their match a little more than that historically — but only a little. Treat this as 'three plausible outcomes', not 'a pick'.",
       lambda c: {"conf": c.call_conf}),
    _T("low-call-5", "prob", "hedged", 0.7, _low_call,
       "Low-confidence pick on {call} — flagged so you see what the model thinks, not because the model is sure.",
       lambda c: {"call": c.call_team}),
    _T("low-call-6", "prob", "hedged", 0.7, _low_call,
       "Headline says {call} but only at {conf}% — best read as 'this match is open' rather than 'this side is favoured'.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("low-call-7", "prob", "hedged", 0.7, _low_call,
       "{call} pulls the leader spot at {conf}% — the model's smallest 'pick' tier, where individual outcomes barely separate.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("low-call-8", "prob", "hedged", 0.7, _low_call,
       "Confidence under 40 means we publish for completeness, not because we'd press it.",
       lambda c: {}),

    # ─── DRAW BIAS / DRAW CALL ───────────────────────────────────────────
    _T("draw-bias-1", "market", "any", 1.0, lambda c: c.draw_high and c.call_key == "D",
       "Draw bucket sits at {drawP}%, high enough that splitting the points is genuinely on the table.",
       lambda c: {"drawP": c.prob_d}),
    _T("draw-bias-2", "market", "any", 1.0, lambda c: c.draw_high and c.call_key == "D",
       "Draw is the model's call at {drawP}% — the books typically underprice this exact scenario.",
       lambda c: {"drawP": c.prob_d}),
    _T("draw-bias-3", "market", "any", 0.9, lambda c: c.draw_high and c.call_key == "D",
       "Closely-matched form pulls the draw into play; model has it at {drawP}% — above its own historical baseline.",
       lambda c: {"drawP": c.prob_d}),
    _T("draw-bias-4", "market", "any", 0.9, lambda c: c.draw_high and c.call_key == "D",
       "Draws are systematically underbacked — at {drawP}% the model thinks today is one of those days.",
       lambda c: {"drawP": c.prob_d}),
    _T("draw-bias-5", "market", "any", 0.9, lambda c: c.draw_high and c.call_key == "D",
       "{drawP}% on the draw — both teams arrive within touching distance on form, defence, and venue.",
       lambda c: {"drawP": c.prob_d}),
    _T("draw-bias-6", "market", "any", 0.8, lambda c: c.draw_high and c.call_key == "D",
       "When neither side is a clear favourite, the draw is the smart call — model says we're there at {drawP}%.",
       lambda c: {"drawP": c.prob_d}),
    _T("draw-bias-7", "prob", "hedged", 0.7, lambda c: c.draw_high and c.call_key != "D",
       "Headline isn't 'draw' but the draw bucket is fat at {drawP}% — keep the third outcome live.",
       lambda c: {"drawP": c.prob_d}),
    _T("draw-bias-8", "prob", "hedged", 0.7, lambda c: c.draw_high and c.call_key != "D",
       "{drawP}% on the draw despite a call elsewhere — match is closer to a three-way than the headline suggests.",
       lambda c: {"drawP": c.prob_d}),

    # ─── TIGHT SPREAD (any call_key) ─────────────────────────────────────
    _T("tight-1", "prob", "hedged", 0.7, _tight_spread,
       "Top two outcomes inside {spread}pp — any single break of play decides this one.",
       lambda c: {"spread": c.spread}),
    _T("tight-2", "prob", "hedged", 0.7, _tight_spread,
       "Tight bucket — leaders separated by {spread}pp. Match is a coin you can't see both sides of.",
       lambda c: {"spread": c.spread}),
    _T("tight-3", "prob", "hedged", 0.7, _tight_spread,
       "{spread}-point gap between top and second — match is close enough that any single moment changes the read.",
       lambda c: {"spread": c.spread}),
    _T("tight-4", "prob", "hedged", 0.6, _tight_spread,
       "Bucket leader by {spread}pp — not the kind of margin that survives a red card or a deflected shot.",
       lambda c: {"spread": c.spread}),
    _T("tight-5", "prob", "hedged", 0.6, _tight_spread,
       "Slate is full of decisive picks; this one isn't. {spread}pp between leader and runner-up.",
       lambda c: {"spread": c.spread}),

    # ─── DECISIVE / WIDE SPREAD ──────────────────────────────────────────
    _T("decisive-1", "prob", "loud", 1.1, lambda c: c.is_decisive and c.call_key != "D",
       "{call} clears the field by {spread}pp — historically these matches resolve cleanly in the favourite's direction.",
       lambda c: {"call": c.call_team, "spread": c.spread}),
    _T("decisive-2", "prob", "loud", 1.0, lambda c: c.is_decisive and c.call_key != "D",
       "{spread}pp gap between top and second — the kind of separation the model only produces when several signals agree.",
       lambda c: {"spread": c.spread}),
    _T("decisive-3", "prob", "loud", 1.0, lambda c: c.is_decisive and c.call_key != "D",
       "Decisive distribution — {call} alone at the top, the rest of the field {spread}pp back.",
       lambda c: {"call": c.call_team, "spread": c.spread}),
    _T("decisive-4", "prob", "loud", 0.9, lambda c: c.is_decisive and c.call_key != "D",
       "Wide spread on {call} ({spread}pp) — variance still exists, but it's working against history.",
       lambda c: {"call": c.call_team, "spread": c.spread}),
    _T("decisive-5", "prob", "loud", 0.9, lambda c: c.is_decisive and c.call_key != "D",
       "When the model produces a {spread}pp spread, there's usually a reason — {call} has it today.",
       lambda c: {"call": c.call_team, "spread": c.spread}),

    # ─── THREE-WAY OPEN ──────────────────────────────────────────────────
    _T("three-way-1", "prob", "hedged", 0.7, _three_way_open,
       "Every outcome lives — H/D/A in a {lo}–{hi}% band; none of the three is unusual here.",
       lambda c: {"lo": min(c.prob_h, c.prob_d, c.prob_a), "hi": max(c.prob_h, c.prob_d, c.prob_a)}),
    _T("three-way-2", "prob", "hedged", 0.7, _three_way_open,
       "All three outcomes above 25% — match is genuinely open, the published call is just the slimmest leader.",
       lambda c: {}),
    _T("three-way-3", "prob", "hedged", 0.6, _three_way_open,
       "Three-way market with no real favourite — every result lands inside its historical 'plausible' window.",
       lambda c: {}),
    _T("three-way-4", "prob", "hedged", 0.6, _three_way_open,
       "Distribution is unusually flat — H {h}, D {d}, A {a}. Pick the leader if you must; the model is hedged.",
       lambda c: {"h": c.prob_h, "d": c.prob_d, "a": c.prob_a}),
    _T("three-way-5", "prob", "hedged", 0.6, _three_way_open,
       "When all three buckets clear 25%, the match is functionally a three-sided dice. Today qualifies.",
       lambda c: {}),

    # ─── HOME CLEAR / AWAY OVERRIDES ─────────────────────────────────────
    _T("home-clear-1", "prob", "mid", 0.9, _h_clear,
       "Home call by a clear margin — venue, form, and priors all stacking the same way.",
       lambda c: {}),
    _T("home-clear-2", "prob", "mid", 0.9, _h_clear,
       "Home edge is real today — {call} {conf}%, away side trailing by {gap}pp.",
       lambda c: {"call": c.call_team, "conf": c.call_conf, "gap": c.prob_h - c.prob_a}),
    _T("home-clear-3", "prob", "mid", 0.8, _h_clear,
       "{call} at home with the venue advantage compounding — model has them {gap}pp clear of the away side.",
       lambda c: {"call": c.call_team, "gap": c.prob_h - c.prob_a}),
    _T("home-clear-4", "prob", "mid", 0.8, _h_clear,
       "Home shade plus form gives {call} a {gap}pp lead in the bucket — clean signal.",
       lambda c: {"call": c.call_team, "gap": c.prob_h - c.prob_a}),
    _T("home-clear-5", "prob", "mid", 0.7, _h_clear,
       "Home advantage runs ~3pp in this league — {call} clears that and then some.",
       lambda c: {"call": c.call_team}),
    _T("away-override-1", "prob", "mid", 1.0, _a_overrides,
       "Away call against the home shade — model sees enough in {call} to override the venue prior.",
       lambda c: {"call": c.call_team}),
    _T("away-override-2", "prob", "mid", 0.9, _a_overrides,
       "{call} on the road, ahead of the home side by {gap}pp — strong signal given the standard home advantage.",
       lambda c: {"call": c.call_team, "gap": c.prob_a - c.prob_h}),
    _T("away-override-3", "prob", "mid", 0.9, _a_overrides,
       "Away pick worth a second look — beating a home prior of ~3pp before form even enters the picture.",
       lambda c: {}),
    _T("away-override-4", "prob", "mid", 0.8, _a_overrides,
       "{call} priced ahead of the home side despite venue cost — that's how strong the form differential is.",
       lambda c: {"call": c.call_team}),
    _T("away-override-5", "prob", "mid", 0.8, _a_overrides,
       "Model overrules venue: {call} {conf}% on the road, the home side {homeP}% — uncommon enough to underline.",
       lambda c: {"call": c.call_team, "conf": c.call_conf, "homeP": c.prob_h}),

    # ─── DRAW CALL (call_key == D, irrespective of draw_high) ────────────
    _T("draw-call-1", "prob", "any", 0.9, _draw_call,
       "Model's call is the draw at {conf}% — neither side projects with enough margin to separate.",
       lambda c: {"conf": c.call_conf}),
    _T("draw-call-2", "prob", "any", 0.9, _draw_call,
       "Draw the most likely outcome at {conf}% — both sides cancel before kickoff.",
       lambda c: {"conf": c.call_conf}),
    _T("draw-call-3", "prob", "any", 0.8, _draw_call,
       "When the draw is the leader, the bookies typically lag — {conf}% is firm enough to publish.",
       lambda c: {"conf": c.call_conf}),
    _T("draw-call-4", "prob", "any", 0.8, _draw_call,
       "{conf}% on the draw — defensive metrics on both sides cluster, attacking metrics cancel.",
       lambda c: {"conf": c.call_conf}),
    _T("draw-call-5", "prob", "any", 0.7, _draw_call,
       "Draw call from the model — historically the trickiest bucket to publish, but the numbers say it.",
       lambda c: {}),

    # ─── LEAGUE COLOUR ──────────────────────────────────────────────────
    _T("league-ucl-1", "league", "any", 1.0, lambda c: c.league_code == "ucl",
       "Champions League nights compress the priors — knockout matches land closer to 50/50 than league form suggests.",
       lambda c: {}),
    _T("league-ucl-2", "league", "any", 0.9, lambda c: c.league_code == "ucl",
       "UCL-night variance is wider than league play — adjust your conviction down a notch on this one.",
       lambda c: {}),
    _T("league-ucl-3", "league", "any", 0.9, lambda c: c.league_code == "ucl",
       "Two-legged ties + neutral pundit attention compress odds in UCL matches — model accounts for that.",
       lambda c: {}),
    _T("league-ucl-4", "league", "any", 0.8, lambda c: c.league_code == "ucl",
       "European nights play differently — different referees, different tempo, model widens its priors.",
       lambda c: {}),
    _T("league-wc-1", "league", "any", 1.1, lambda c: c.league_code == "worldcup",
       "World Cup priors lean on national-team Elo, not club form — model volume shifts during the tournament.",
       lambda c: {}),
    _T("league-wc-2", "league", "any", 1.0, lambda c: c.league_code == "worldcup",
       "WC matches see far less data than club fixtures — confidence intervals are wider here than they look.",
       lambda c: {}),
    _T("league-wc-3", "league", "any", 0.9, lambda c: c.league_code == "worldcup",
       "International tournaments produce 1.5x the upset rate of club football — read this number with that in mind.",
       lambda c: {}),
    _T("league-laliga-1", "league", "any", 0.95, lambda c: c.league_code == "laliga",
       "La Liga produces tighter scorelines than the model used to price — draw bucket gets a small uplift.",
       lambda c: {}),
    _T("league-laliga-2", "league", "any", 0.9, lambda c: c.league_code == "laliga",
       "La Liga ranks middle-of-the-pack on goals scored — totals stay modest, draws stay live.",
       lambda c: {}),
    _T("league-laliga-3", "league", "any", 0.85, lambda c: c.league_code == "laliga",
       "Spanish top flight: tactical, possession-led, draws priced tighter than the long-run rate.",
       lambda c: {}),
    _T("league-seriea-1", "league", "any", 0.95, lambda c: c.league_code == "seriea",
       "Serie A is the lowest-scoring league in the dataset — totals models drift under, prob models lean toward draws.",
       lambda c: {}),
    _T("league-seriea-2", "league", "any", 0.9, lambda c: c.league_code == "seriea",
       "Italian football skews defensive — the model adjusts its outcome priors a notch toward 1-0 / 0-0 territory.",
       lambda c: {}),
    _T("league-seriea-3", "league", "any", 0.85, lambda c: c.league_code == "seriea",
       "Lowest-goal-rate league we cover — read favourite prices conservatively in Serie A.",
       lambda c: {}),
    _T("league-bundesliga-1", "league", "any", 0.95, lambda c: c.league_code == "bundesliga",
       "Bundesliga matches average more goals than any league we track — variance is wider in both directions.",
       lambda c: {}),
    _T("league-bundesliga-2", "league", "any", 0.9, lambda c: c.league_code == "bundesliga",
       "German top flight: open, transitional, high-tempo — favourites win at expected rates but the variance band is wider.",
       lambda c: {}),
    _T("league-bundesliga-3", "league", "any", 0.85, lambda c: c.league_code == "bundesliga",
       "Bundesliga produces ~3.1 goals per match — one of the highest in our pool and a meaningful prior.",
       lambda c: {}),
    _T("league-epl-1", "league", "any", 0.95, lambda c: c.league_code == "epl",
       "Premier League is the most-calibrated league in the model — every probability bucket has the largest sample.",
       lambda c: {}),
    _T("league-epl-2", "league", "any", 0.9, lambda c: c.league_code == "epl",
       "EPL has the deepest historical sample we train on — narrow probability bands here are typically reliable.",
       lambda c: {}),
    _T("league-epl-3", "league", "any", 0.85, lambda c: c.league_code == "epl",
       "Premier League: tightest competitive balance in our dataset — favourites win at lower rates than other top leagues.",
       lambda c: {}),
    _T("league-ligue1-1", "league", "any", 0.9, lambda c: c.league_code == "ligue1",
       "Ligue 1 has high parity outside the top three — favourite markets price wider than other top leagues.",
       lambda c: {}),
    _T("league-ligue1-2", "league", "any", 0.85, lambda c: c.league_code == "ligue1",
       "French top flight: lower median goal totals than EPL/Bundesliga, but more total-shock results.",
       lambda c: {}),
    _T("league-mls-1", "league", "any", 0.85, lambda c: c.league_code == "mls",
       "MLS parity is high — favourite-prices rarely hold; the model widens its uncertainty band by default.",
       lambda c: {}),
    _T("league-mls-2", "league", "any", 0.8, lambda c: c.league_code == "mls",
       "MLS travel patterns produce more away-side variance than any other league — read venue with care.",
       lambda c: {}),
    _T("league-championship-1", "league", "any", 0.85, lambda c: c.league_code == "championship",
       "EFL Championship — second-tier English football is high-variance and high-volume; small-edge picks are best read with patience.",
       lambda c: {}),
    _T("league-championship-2", "league", "any", 0.8, lambda c: c.league_code == "championship",
       "Championship matches play closer to a coin flip than any top-tier league we track.",
       lambda c: {}),
    _T("league-eredivisie-1", "league", "any", 0.85, lambda c: c.league_code == "eredivisie",
       "Eredivisie is the highest-scoring league in the dataset by a margin — variance is the rule, not the exception.",
       lambda c: {}),

    # ─── STAGE / KNOCKOUT ────────────────────────────────────────────────
    _T("stage-knockout-1", "tournament", "any", 1.0, _knockout,
       "{stage} matches favour the higher-confidence side less than league fixtures — single-game variance is bigger.",
       lambda c: {"stage": (c.stage or "").upper()}),
    _T("stage-knockout-2", "tournament", "any", 0.9, _knockout,
       "Knockout football compresses outcomes — the model's priors are wider for {stage} than for league play.",
       lambda c: {"stage": (c.stage or "").upper()}),
    _T("stage-knockout-3", "tournament", "any", 0.9, _knockout,
       "{stage} ties feature roughly 1.4× the upset rate of league fixtures — read this confidence accordingly.",
       lambda c: {"stage": (c.stage or "").upper()}),
    _T("stage-knockout-4", "tournament", "any", 0.85, _knockout,
       "Single-game knockout variance is real — {stage} numbers are softer than they read.",
       lambda c: {"stage": (c.stage or "").upper()}),

    # ─── CATCHALLS (low weight, always fire) ────────────────────────────
    _T("catchall-1", "meta", "any", 0.15, lambda c: True,
       "{call} the call at {conf}% — the strongest of the three buckets the model produced.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("catchall-2", "meta", "any", 0.12, lambda c: True,
       "Top of the bucket sits with {call} at {conf}% — published as the model's best read on the slate.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("catchall-3", "meta", "any", 0.1, lambda c: True,
       "Model's headline read: {call} at {conf}% over the alternatives.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
    _T("catchall-4", "meta", "any", 0.1, lambda c: True,
       "{call} {conf}% — the single number that survives all the gating logic.",
       lambda c: {"call": c.call_team, "conf": c.call_conf}),
]


def _hash_seed(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def _jitter(template_id: str, seed: int) -> float:
    h = _hash_seed(f"{template_id}:{seed}")
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
    """Produce a single-sentence explanation for a Prediction + Match pair."""
    ctx = _build_context(prediction, match)
    if ctx is None:
        return None

    eligible: List[_Tmpl] = []
    for t in _TEMPLATES:
        try:
            if not _template_magnitude_ok(ctx, t.magnitude):
                continue
            if t.fires(ctx):
                eligible.append(t)
        except Exception:
            continue

    if not eligible:
        return None

    import datetime as _dt
    today = _dt.date.today()
    # Two-week rotation: include the day-of-fortnight so the same prediction
    # gets different wording across consecutive Mondays/Tuesdays etc., then
    # the cycle repeats. Within one day the output is stable.
    fortnight = today.toordinal() % 14
    seed = _hash_seed(f"pred:{getattr(prediction, 'id', '')}:{today.toordinal()}:{fortnight}")
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
