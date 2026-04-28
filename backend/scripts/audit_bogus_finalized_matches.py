"""
backend/scripts/audit_bogus_finalized_matches.py
=================================================
Read-only audit of matches that were prematurely finalized as 0-0 draws
(or with other hallmarks of a corrupted score-update write).

Three classes of suspect rows are flagged:

  CLASS A — Null-kickoff 0-0 completed
    status='completed' AND kickoff_time IS NULL
    AND home_goals=0 AND away_goals=0
    AND match_date >= today - days_back (default 60)
    These are the primary hallmark of the PSG/Bayern-style bug: a
    placeholder-seeded fixture that was never played yet got finalized.

  CLASS B — Future completed
    status='completed' AND match_date > today
    Logically impossible. A match in the future cannot be completed.

  CLASS C — Null-kickoff completed (regardless of score)
    status='completed' AND kickoff_time IS NULL
    AND match_date >= today - days_back
    Superset of Class A. Any completed row without a kickoff_time should
    be treated as suspect — the pipeline only writes kickoff_time when it
    has a real fixture from the API, so NULL strongly implies a seed row
    that was never properly matched to a live feed event.

Usage:
    cd saas/backend
    conda run -n ml python scripts/audit_bogus_finalized_matches.py
    conda run -n ml python scripts/audit_bogus_finalized_matches.py --days-back 90
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _print_table(title: str, rows: list[dict]) -> None:
    """Print a simple ASCII table for a list of dicts sharing the same keys."""
    if not rows:
        print(f"\n{title}: (none)\n")
        return

    cols = list(rows[0].keys())
    widths = {c: max(len(c), max(len(str(r[c])) for r in rows)) for c in cols}

    sep = "+-" + "-+-".join("-" * widths[c] for c in cols) + "-+"
    header = "| " + " | ".join(c.ljust(widths[c]) for c in cols) + " |"

    print(f"\n{title} ({len(rows)} row{'s' if len(rows) != 1 else ''}):")
    print(sep)
    print(header)
    print(sep)
    for r in rows:
        print("| " + " | ".join(str(r[c]).ljust(widths[c]) for c in cols) + " |")
    print(sep)


def audit(days_back: int = 60) -> dict:
    today = date.today()
    cutoff = (today - timedelta(days=days_back)).isoformat()
    today_iso = today.isoformat()

    db = SessionLocal()
    try:
        # --- Class A: null-kickoff 0-0 completed within window ---
        class_a_rows = db.execute(
            text(
                """
                SELECT
                    m.id            AS match_id,
                    l.code          AS league_code,
                    m.match_date,
                    ht.canonical_name  AS home_team,
                    at.canonical_name  AS away_team,
                    COALESCE(m.home_goals, 0) AS home_goals,
                    COALESCE(m.away_goals, 0) AS away_goals,
                    m.result,
                    m.updated_at,
                    (SELECT COUNT(*) FROM predictions p
                     WHERE p.match_id = m.id)    AS has_predictions
                FROM matches m
                LEFT JOIN leagues  l  ON l.id = m.league_id
                LEFT JOIN teams    ht ON ht.id = m.home_team_id
                LEFT JOIN teams    at ON at.id = m.away_team_id
                WHERE m.status       = 'completed'
                  AND m.kickoff_time IS NULL
                  AND m.home_goals   = 0
                  AND m.away_goals   = 0
                  AND m.match_date  >= :cutoff
                ORDER BY m.match_date DESC
                """
            ),
            {"cutoff": cutoff},
        ).fetchall()

        # --- Class B: future date + completed (logically impossible) ---
        class_b_rows = db.execute(
            text(
                """
                SELECT
                    m.id            AS match_id,
                    l.code          AS league_code,
                    m.match_date,
                    ht.canonical_name  AS home_team,
                    at.canonical_name  AS away_team,
                    m.home_goals,
                    m.away_goals,
                    m.result,
                    m.updated_at,
                    (SELECT COUNT(*) FROM predictions p
                     WHERE p.match_id = m.id)    AS has_predictions
                FROM matches m
                LEFT JOIN leagues  l  ON l.id = m.league_id
                LEFT JOIN teams    ht ON ht.id = m.home_team_id
                LEFT JOIN teams    at ON at.id = m.away_team_id
                WHERE m.status    = 'completed'
                  AND m.match_date > :today
                ORDER BY m.match_date ASC
                """
            ),
            {"today": today_iso},
        ).fetchall()

        # --- Class C: null-kickoff completed within window (any score) ---
        class_c_rows = db.execute(
            text(
                """
                SELECT
                    m.id            AS match_id,
                    l.code          AS league_code,
                    m.match_date,
                    ht.canonical_name  AS home_team,
                    at.canonical_name  AS away_team,
                    m.home_goals,
                    m.away_goals,
                    m.result,
                    m.updated_at,
                    (SELECT COUNT(*) FROM predictions p
                     WHERE p.match_id = m.id)    AS has_predictions
                FROM matches m
                LEFT JOIN leagues  l  ON l.id = m.league_id
                LEFT JOIN teams    ht ON ht.id = m.home_team_id
                LEFT JOIN teams    at ON at.id = m.away_team_id
                WHERE m.status       = 'completed'
                  AND m.kickoff_time IS NULL
                  AND m.match_date  >= :cutoff
                ORDER BY m.match_date DESC
                """
            ),
            {"cutoff": cutoff},
        ).fetchall()

        def _to_dicts(rows) -> list[dict]:
            return [dict(r._mapping) for r in rows]

        a_dicts = _to_dicts(class_a_rows)
        b_dicts = _to_dicts(class_b_rows)
        c_dicts = _to_dicts(class_c_rows)

        # Class C minus Class A — rows that have non-zero scores but null kickoff
        a_ids = {r["match_id"] for r in a_dicts}
        c_only = [r for r in c_dicts if r["match_id"] not in a_ids]

        print(f"\n=== Bogus-Finalized Match Audit (today={today}, window={days_back}d) ===")

        _print_table(
            "CLASS A — null-kickoff 0-0 completed [HIGHEST PRIORITY]",
            a_dicts,
        )
        _print_table(
            "CLASS B — future date + completed [IMPOSSIBLE]",
            b_dicts,
        )
        _print_table(
            "CLASS C (additional) — null-kickoff completed with non-zero score [SUSPECT]",
            c_only,
        )

        # Unique across all three classes
        all_ids = a_ids | {r["match_id"] for r in b_dicts} | {r["match_id"] for r in c_dicts}
        total_preds = sum(r["has_predictions"] for r in a_dicts + b_dicts + c_only)

        print(f"\nSummary:")
        print(f"  Class A (0-0 null-kickoff completed):          {len(a_dicts)}")
        print(f"  Class B (future + completed):                  {len(b_dicts)}")
        print(f"  Class C (all null-kickoff completed, in win):  {len(c_dicts)}")
        print(f"  Unique suspect match count:                    {len(all_ids)}")
        print(f"  Predictions at risk (was_correct may be bad):  {total_preds}")
        print()

        return {
            "class_a": a_dicts,
            "class_b": b_dicts,
            "class_c": c_dicts,
            "total_suspect": len(all_ids),
            "total_predictions_at_risk": total_preds,
        }

    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit matches prematurely finalized with bogus scores."
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=60,
        help="How many days back to look for Class A/C rows (default 60).",
    )
    args = parser.parse_args()

    audit(days_back=args.days_back)
    return 0


if __name__ == "__main__":
    sys.exit(main())
