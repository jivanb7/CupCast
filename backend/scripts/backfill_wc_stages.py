"""
backend/scripts/backfill_wc_stages.py
======================================
One-time (idempotent) backfill of matches.stage + matches.group_label for
World Cup matches, pulling metadata from ESPN's scoreboard + per-event
summary endpoints.

Strategy
--------
We don't store ESPN's event_id on our match rows, so we rematch by the same
key the seeder uses on insert: (league, match_date, home_team_id, away_team_id).
This means a single scoreboard call covers the whole tournament window and we
only hit the summary endpoint for group-stage matches that actually need a
group_label (any match that's still NULL after round detection).

Safe to re-run:
  - Only updates rows where stage IS NULL (or group_label IS NULL for group
    matches) — already-populated rows are skipped.
  - CURRENT_TIMESTAMP is SQLite-compatible (no NOW()).

Usage:
    cd saas/backend
    conda run -n ml python scripts/backfill_wc_stages.py
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402
from services.espn_fixture_service import (  # noqa: E402
    ESPN_LEAGUES,
    LOOKAHEAD_OVERRIDES,
    _extract_group_label,
    _extract_stage,
    _fetch_event_summary,
    _fetch_scoreboard,
)
from services.fixture_seeder import _resolve_team  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

WC_SLUG = "fifa.world"
WC_LEAGUE_CODE = ESPN_LEAGUES[WC_SLUG]  # "worldcup"

# Window large enough to cover a full tournament (120+ days). We deliberately
# look ahead far past LOOKAHEAD_OVERRIDES so late-added knockouts are captured.
_BACKFILL_DAYS = max(LOOKAHEAD_OVERRIDES.get(WC_SLUG, 120), 200)

# Small delay between summary calls. ESPN has no documented rate limit but
# being polite costs nothing and protects us from silent throttling.
_SUMMARY_CALL_DELAY_S = 0.2


def _window() -> tuple[date, date]:
    """Look slightly into the past to cover already-kicked-off matches too."""
    today = date.today()
    return today - timedelta(days=30), today + timedelta(days=_BACKFILL_DAYS)


def main() -> int:
    db = SessionLocal()
    try:
        from models.league import League
        from models.match import Match

        league = db.query(League).filter(League.code == WC_LEAGUE_CODE).first()
        if not league:
            logger.error("League %r not found — aborting", WC_LEAGUE_CODE)
            return 1

        # Snapshot current state so we can log before/after.
        pre_rows = db.execute(
            text(
                "SELECT COUNT(*) FROM matches WHERE league_id = :lid"
            ),
            {"lid": league.id},
        ).scalar_one()
        pre_null_stage = db.execute(
            text(
                "SELECT COUNT(*) FROM matches WHERE league_id = :lid AND stage IS NULL"
            ),
            {"lid": league.id},
        ).scalar_one()
        logger.info(
            "WC matches in DB: %d total, %d with NULL stage",
            pre_rows,
            pre_null_stage,
        )

        if pre_rows == 0:
            logger.info("No WC matches to backfill — exiting cleanly.")
            return 0

        start, end = _window()
        events = _fetch_scoreboard(WC_SLUG, start, end)
        logger.info("ESPN returned %d events for %s..%s", len(events), start, end)
        if not events:
            logger.warning("ESPN returned no events — nothing to backfill")
            return 0

        stats = {
            "events_total": len(events),
            "events_unmatched": 0,
            "updated_stage": 0,
            "updated_group": 0,
            "unparsed_stage": 0,
            "unparsed_group_stage_events": [],
            "errors": 0,
        }

        for ev in events:
            iso = ev.get("date") or ""
            if not iso:
                continue
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                continue
            match_date = dt.date()

            # Resolve teams via the same path the seeder uses — keeps behavior
            # identical so we match against the same rows that were inserted.
            competitions = ev.get("competitions") or []
            if not competitions:
                continue
            competitors = competitions[0].get("competitors") or []
            home_name = away_name = None
            for c in competitors:
                team_block = c.get("team") or {}
                name = (
                    team_block.get("displayName")
                    or team_block.get("name")
                    or team_block.get("shortDisplayName")
                )
                if c.get("homeAway") == "home":
                    home_name = name
                elif c.get("homeAway") == "away":
                    away_name = name
            if not home_name or not away_name:
                continue

            home_id = _resolve_team(db, home_name, WC_LEAGUE_CODE)
            away_id = _resolve_team(db, away_name, WC_LEAGUE_CODE)
            if not home_id or not away_id:
                # Expected for knockout events whose "team" names are placeholders
                # like "Group A 2nd Place". Not an error.
                stats["events_unmatched"] += 1
                continue

            match = (
                db.query(Match)
                .filter(
                    Match.league_id == league.id,
                    Match.match_date == match_date,
                    Match.home_team_id == home_id,
                    Match.away_team_id == away_id,
                )
                .first()
            )
            if not match:
                stats["events_unmatched"] += 1
                continue

            stage = _extract_stage(ev)
            if stage is None:
                stats["unparsed_stage"] += 1
                logger.warning(
                    "Could not parse stage for event %r (slug=%r)",
                    ev.get("name"),
                    (ev.get("season") or {}).get("slug"),
                )

            need_stage = match.stage is None and stage is not None
            need_group = (
                (match.stage == "group" or stage == "group")
                and match.group_label is None
            )

            if need_stage:
                match.stage = stage
                stats["updated_stage"] += 1

            if need_group:
                summary = _fetch_event_summary(WC_SLUG, str(ev.get("id") or ""))
                label = _extract_group_label(summary) if summary else None
                if label:
                    match.group_label = label
                    stats["updated_group"] += 1
                else:
                    stats["unparsed_group_stage_events"].append(ev.get("name"))
                time.sleep(_SUMMARY_CALL_DELAY_S)

        db.commit()

        # Post-snapshot for reporting.
        post_null_stage = db.execute(
            text(
                "SELECT COUNT(*) FROM matches WHERE league_id = :lid AND stage IS NULL"
            ),
            {"lid": league.id},
        ).scalar_one()
        dist_rows = db.execute(
            text(
                "SELECT COALESCE(stage, 'NULL') AS s, COUNT(*) "
                "FROM matches WHERE league_id = :lid GROUP BY stage ORDER BY s"
            ),
            {"lid": league.id},
        ).all()

        logger.info("Backfill stats: %s", stats)
        logger.info("Stage distribution after backfill:")
        for stage_name, count in dist_rows:
            logger.info("  %s: %d", stage_name, count)
        logger.info(
            "Null-stage WC rows: %d -> %d", pre_null_stage, post_null_stage
        )
        return 0

    except Exception as e:
        db.rollback()
        logger.exception("Backfill failed: %s", e)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
