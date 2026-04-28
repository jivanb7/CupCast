"""
backend/services/league_track_record.py
=========================================
Per-league rolling accuracy helper used to gate value-pick badges.

The core problem this solves:
  Our model's edge detector flags "I disagree with the bookmaker" whenever
  model_prob - implied_prob > threshold. But that signal is only meaningful
  when our model is actually better than naive in that league. In leagues
  where we have 29-38% accuracy, the edge flag is noise — and displaying
  "+5.5% Value Edge" there actively misleads users.

Public API
----------
get_league_accuracy_map(db) → dict[str, float]
    Returns a dict mapping league code → accuracy fraction (0..1) computed
    over predictions with was_correct IS NOT NULL in the trailing 30 days.
    Result is cached for CACHE_TTL_SECONDS (5 min). The db session is only
    used on a cache miss.

gate_value_picks(is_value_pick, league_code, accuracy_map) → (bool, str | None)
    Given the stored is_value_pick flag, the league code for the match, and
    the accuracy map returned by get_league_accuracy_map(), returns:
      - (True, None)                    if the pick passes (accuracy >= threshold)
      - (False, "<reason string>")      if the pick is suppressed
      - passes through (False, None)    if is_value_pick was already False

Threshold
---------
VALUE_PICK_ACCURACY_THRESHOLD = 0.50

0.50 is the naive-home baseline in 3-way classification (for EPL-style
leagues). A league where we score below 0.50 means our model is no better
than "always pick home" — we should not be broadcasting edge calls there.

Cache strategy
--------------
Module-level dict + timestamp. LRU_cache with TTL is awkward because
the DB session is not hashable. Instead we store the last result and the
time it was computed; if the clock has not advanced past TTL we return
the cached copy. Thread-safe enough for the read-heavy API pattern
(worst case: two requests race and both re-query on a cold start — that
is not harmful).
"""

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

VALUE_PICK_ACCURACY_THRESHOLD: float = 0.50
"""Minimum 30-day rolling accuracy a league must have for value picks to show."""

CACHE_TTL_SECONDS: int = 300
"""How long (seconds) the accuracy map is considered fresh. 5 minutes."""

MIN_SAMPLE_SIZE: int = 10
"""Minimum number of evaluated predictions required before we gate on accuracy.

If a league has fewer than MIN_SAMPLE_SIZE evaluated predictions in the
last 30 days, we treat it as UNKNOWN and allow value picks through rather
than suppressing them due to insufficient data.
"""

# --------------------------------------------------------------------------
# Module-level cache
# --------------------------------------------------------------------------

_cache: Optional[dict[str, float]] = None
_cache_ts: Optional[float] = None  # Unix timestamp of last population


def _is_cache_fresh() -> bool:
    import time
    if _cache is None or _cache_ts is None:
        return False
    return (time.time() - _cache_ts) < CACHE_TTL_SECONDS


def _populate_cache(db: Session) -> dict[str, float]:
    """Query the DB and return a fresh league-accuracy map. Updates module cache."""
    global _cache, _cache_ts
    import time

    from models.league import League
    from models.match import Match
    from models.prediction import Prediction

    cutoff = date.today() - timedelta(days=30)

    rows = (
        db.query(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .filter(
            Prediction.was_correct.isnot(None),
            Match.match_date >= cutoff,
            Match.league_id.isnot(None),
        )
        .all()
    )

    # Collect league_id → {correct, total}
    league_id_stats: dict[int, dict] = {}
    for pred, match in rows:
        lid = match.league_id
        if lid not in league_id_stats:
            league_id_stats[lid] = {"correct": 0, "total": 0}
        league_id_stats[lid]["total"] += 1
        if pred.was_correct:
            league_id_stats[lid]["correct"] += 1

    if not league_id_stats:
        logger.debug("league_track_record: no evaluated predictions in last 30 days")
        _cache = {}
        _cache_ts = time.time()
        return {}

    # Batch-load league codes for the IDs we saw
    league_ids = list(league_id_stats.keys())
    leagues_by_id = {
        lg.id: lg
        for lg in db.query(League).filter(League.id.in_(league_ids)).all()
    }

    accuracy_map: dict[str, float] = {}
    for lid, stats in league_id_stats.items():
        league_obj = leagues_by_id.get(lid)
        if not league_obj or not league_obj.code:
            continue
        if stats["total"] < MIN_SAMPLE_SIZE:
            # Insufficient sample — log and skip (picks pass through)
            logger.debug(
                "league_track_record: %s has only %d evaluated rows in 30d, "
                "skipping accuracy gate",
                league_obj.code,
                stats["total"],
            )
            continue
        accuracy_map[league_obj.code] = round(stats["correct"] / stats["total"], 4)

    logger.debug("league_track_record: refreshed accuracy map %s", accuracy_map)
    _cache = accuracy_map
    _cache_ts = time.time()
    return accuracy_map


def get_league_accuracy_map(db: Session) -> dict[str, float]:
    """Return the per-league 30-day rolling accuracy map, using cache when fresh.

    Args:
        db: SQLAlchemy session. Only used on a cache miss.

    Returns:
        dict mapping league code (e.g. "E0", "I1") to accuracy fraction.
        Leagues with fewer than MIN_SAMPLE_SIZE evaluated rows in the last
        30 days are omitted — callers treat missing keys as "unknown / pass".
    """
    if _is_cache_fresh():
        return _cache  # type: ignore[return-value]
    return _populate_cache(db)


def gate_value_picks(
    is_value_pick: bool,
    league_code: Optional[str],
    accuracy_map: dict[str, float],
) -> tuple[bool, Optional[str]]:
    """Decide whether to pass or suppress a value-pick badge.

    Args:
        is_value_pick:  The stored DB flag (set by edge_service at inference time).
        league_code:    League code for the match (e.g. "E0"). None → unknown.
        accuracy_map:   Map from get_league_accuracy_map().

    Returns:
        (effective_is_value_pick, gated_reason)

        If the pick is suppressed, effective_is_value_pick is False and
        gated_reason is a human-readable string explaining why.
        If the pick passes or was already False, gated_reason is None.
    """
    # Pick was already False — nothing to gate, pass through cleanly.
    if not is_value_pick:
        return False, None

    # No league code or league not in accuracy map → insufficient data to gate.
    # We pass the pick through rather than suppressing due to missing data.
    if not league_code or league_code not in accuracy_map:
        return True, None

    accuracy = accuracy_map[league_code]
    if accuracy < VALUE_PICK_ACCURACY_THRESHOLD:
        reason = (
            f"model accuracy {round(accuracy * 100, 1)}% in this league "
            f"is below the {round(VALUE_PICK_ACCURACY_THRESHOLD * 100, 0):.0f}% threshold"
        )
        return False, reason

    return True, None
