"""
backend/services/refresh_scheduler.py
========================================
Background scheduler for periodic data refresh tasks.

Uses APScheduler to run:
  1. Score updates — every 2 hours during match days (Tue-Wed, Sat-Sun), every 6h otherwise
  2. Fixture refresh — daily at 06:00 UTC (download new fixture CSVs)
  3. Prediction refresh — daily at 07:00 UTC (re-run batch inference after new scores)

The scheduler is started once from FastAPI's lifespan and runs in a background thread.
It does NOT block the event loop.

Usage:
  from services.refresh_scheduler import start_scheduler, stop_scheduler

  # In FastAPI lifespan:
  async def lifespan(app):
      start_scheduler()
      yield
      stop_scheduler()

Configuration:
  Set ENABLE_SCHEDULER=true in .env to activate (disabled by default for dev).
  Set SCHEDULER_SCORE_INTERVAL_HOURS to override the 2-hour default.
"""

import logging
import os
from datetime import datetime
from threading import Thread
from typing import Optional

logger = logging.getLogger(__name__)

_scheduler_thread: Optional[Thread] = None
_scheduler = None  # BlockingScheduler instance, set from _scheduler_loop
_running = False
_scheduler = None  # Holds the BlockingScheduler instance so stop_scheduler can call shutdown()


def _get_db_session():
    """Create a fresh DB session for scheduler tasks (not request-scoped)."""
    from database import SessionLocal
    return SessionLocal()


def _run_score_update():
    """Scheduled task: update match scores from football-data.co.uk."""
    logger.info("Scheduler: starting score update at %s", datetime.utcnow().isoformat())
    db = _get_db_session()
    try:
        from services.score_updater import update_scores
        stats = update_scores(db)
        logger.info("Scheduler: score update done — %s", stats)

        # After scores are applied, append live Elo updates for any WC matches
        # that just completed. Kept in this hook (not inside update_scores) so
        # score ingestion stays agnostic of the rating system.
        try:
            elo_stats = _apply_wc_live_elo_updates(db)
            if elo_stats["updated"] or elo_stats["errors"]:
                logger.info("Scheduler: WC elo live-update — %s", elo_stats)
        except Exception as e:
            logger.error("Scheduler: WC elo live-update failed — %s", e)
    except Exception as e:
        logger.error("Scheduler: score update failed — %s", e)
    finally:
        db.close()


def _apply_wc_live_elo_updates(db) -> dict:
    """Append live_update rows to team_elo for recently-completed WC matches.

    Finds WC matches with status='completed' that don't yet have a matching
    `live_update` row in team_elo for their match_date, computes the new
    ratings via national_elo.update_elo, and writes two rows (home + away).

    Idempotent: the UNIQUE(team_id, as_of_date, source) constraint and the
    per-match existence check prevent double-applying an update if the
    scheduler fires twice.
    """
    from sqlalchemy import and_
    from models.league import League
    from models.match import Match
    from models.team_elo import TeamElo
    from services.national_elo import infer_k, update_elo

    stats = {"updated": 0, "skipped_no_prior_elo": 0, "errors": 0}

    wc_league = db.query(League).filter(League.code == "worldcup").first()
    if not wc_league:
        return stats

    # Candidate matches: completed WC games with a known result.
    completed = (
        db.query(Match)
        .filter(
            Match.league_id == wc_league.id,
            Match.status == "completed",
            Match.home_goals.isnot(None),
            Match.away_goals.isnot(None),
        )
        .all()
    )

    for match in completed:
        # Has a live_update already been written for either team on this
        # match_date? If yes, assume this match was processed. (Two WC games
        # for the same team on the same date is impossible.)
        existing = (
            db.query(TeamElo.id)
            .filter(
                TeamElo.team_id.in_([match.home_team_id, match.away_team_id]),
                TeamElo.as_of_date == match.match_date,
                TeamElo.source == "live_update",
            )
            .first()
        )
        if existing:
            continue

        # Latest rating for each team (strictly before today; fine to include
        # today's historical_backfill row if that's all we have).
        home_row = (
            db.query(TeamElo.rating)
            .filter(TeamElo.team_id == match.home_team_id)
            .order_by(TeamElo.as_of_date.desc(), TeamElo.id.desc())
            .limit(1)
            .first()
        )
        away_row = (
            db.query(TeamElo.rating)
            .filter(TeamElo.team_id == match.away_team_id)
            .order_by(TeamElo.as_of_date.desc(), TeamElo.id.desc())
            .limit(1)
            .first()
        )
        if not home_row or not away_row:
            stats["skipped_no_prior_elo"] += 1
            continue

        try:
            k = infer_k(match.match_importance, match.tournament)
            new_home, new_away = update_elo(
                float(home_row[0]),
                float(away_row[0]),
                int(match.home_goals),
                int(match.away_goals),
                k_constant=k,
                is_neutral=bool(match.is_neutral_venue),
            )
            db.add(TeamElo(
                team_id=match.home_team_id,
                rating=new_home,
                as_of_date=match.match_date,
                source="live_update",
            ))
            db.add(TeamElo(
                team_id=match.away_team_id,
                rating=new_away,
                as_of_date=match.match_date,
                source="live_update",
            ))
            stats["updated"] += 1
        except Exception as e:
            logger.warning("WC elo update failed for match %d: %s", match.id, e)
            stats["errors"] += 1

    if stats["updated"]:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("Failed to commit WC elo live-updates: %s", e)
            stats["errors"] += 1
    return stats


def _run_fixture_refresh():
    """Scheduled task: download latest fixture CSVs and seed new matches."""
    logger.info("Scheduler: starting fixture refresh at %s", datetime.utcnow().isoformat())
    try:
        from services.data_service import trigger_data_refresh
        success = trigger_data_refresh()
        logger.info("Scheduler: fixture refresh %s", "succeeded" if success else "failed")
    except Exception as e:
        logger.error("Scheduler: fixture refresh failed — %s", e)


def _run_prediction_refresh():
    """Scheduled task: re-generate predictions for upcoming matches."""
    logger.info("Scheduler: starting prediction refresh at %s", datetime.utcnow().isoformat())
    db = _get_db_session()
    try:
        from services.prediction_service import generate_batch_predictions
        count = generate_batch_predictions(db)
        logger.info("Scheduler: generated %d predictions", count)
    except Exception as e:
        logger.error("Scheduler: prediction refresh failed — %s", e)
    finally:
        db.close()


def _run_fixture_seed():
    """Scheduled task: seed upcoming fixtures from Football-Data.org + CSV."""
    logger.info("Scheduler: starting fixture seeding at %s", datetime.utcnow().isoformat())
    db = _get_db_session()
    try:
        from services.fixture_seeder import seed_all_fixtures
        stats = seed_all_fixtures(db)
        logger.info("Scheduler: fixture seeding done — %s", stats)
    except Exception as e:
        logger.error("Scheduler: fixture seeding failed — %s", e)
    finally:
        db.close()


def _run_odds_refresh():
    """Scheduled task: refresh bookmaker odds + value-pick flags.

    Runs after prediction refresh so it can overwrite the edge fields that
    generate_batch_predictions zeros out. Calls API-Football /fixtures + /odds
    per tracked league (~50 requests total per run).
    """
    logger.info("Scheduler: starting odds refresh at %s", datetime.utcnow().isoformat())
    db = _get_db_session()
    try:
        from services.odds_service import refresh_all_leagues_odds
        stats = refresh_all_leagues_odds(db)
        logger.info(
            "Scheduler: odds refresh done — matches=%d predictions=%d",
            stats.get("total_matches_updated", 0),
            stats.get("total_predictions_updated", 0),
        )
    except Exception as e:
        logger.error("Scheduler: odds refresh failed — %s", e)
    finally:
        db.close()


def _run_player_refresh():
    """Scheduled task: refresh player top scorers and injuries for all leagues.

    Calls API-Football /players/topscorers and /injuries for each of the 10
    tracked leagues (~20 API calls total). Runs at 05:00 UTC, before the
    fixture refresh at 06:00 UTC and predictions at 07:00 UTC.
    """
    logger.info("Scheduler: starting player refresh at %s", datetime.utcnow().isoformat())
    db = _get_db_session()
    try:
        from services.player_availability_service import refresh_all_leagues
        stats = refresh_all_leagues(db)
        logger.info("Scheduler: player refresh done — %s", stats)
    except Exception as e:
        logger.error("Scheduler: player refresh failed — %s", e)
    finally:
        db.close()


def _scheduler_loop():
    """Main scheduler loop using APScheduler."""
    global _running, _scheduler

    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        logger.warning(
            "APScheduler not installed — scheduler disabled. "
            "Install with: pip install apscheduler"
        )
        return

    scheduler = BlockingScheduler()
    _scheduler = scheduler

    score_interval = int(os.environ.get("SCHEDULER_SCORE_INTERVAL_HOURS", "2"))

    # Score updates: every N hours
    scheduler.add_job(
        _run_score_update,
        IntervalTrigger(hours=score_interval),
        id="score_update",
        name="Update match scores",
        replace_existing=True,
    )

    # Fixture seeding: 3x daily — night, morning, evening (UTC)
    # Seeds upcoming matches from Football-Data.org API + fixtures CSV
    for hour in [1, 10, 18]:
        scheduler.add_job(
            _run_fixture_seed,
            CronTrigger(hour=hour, minute=0),
            id=f"fixture_seed_{hour:02d}",
            name=f"Seed upcoming fixtures ({hour:02d}:00 UTC)",
            replace_existing=True,
        )

    # Player data refresh: daily at 05:00 UTC (before predictions)
    scheduler.add_job(
        _run_player_refresh,
        CronTrigger(hour=5, minute=0),
        id="player_refresh",
        name="Refresh player data",
        replace_existing=True,
    )

    # Data pipeline refresh: daily at 06:00 UTC (download CSVs, update scores)
    scheduler.add_job(
        _run_fixture_refresh,
        CronTrigger(hour=6, minute=0),
        id="fixture_refresh",
        name="Refresh data pipeline",
        replace_existing=True,
    )

    # Prediction refresh: daily at 07:00 UTC (after fixtures + scores are updated)
    scheduler.add_job(
        _run_prediction_refresh,
        CronTrigger(hour=7, minute=0),
        id="prediction_refresh",
        name="Refresh predictions",
        replace_existing=True,
    )

    # Odds refresh: 07:30 UTC (right after predictions — overwrites zeroed edges)
    # and 15:00 UTC (mid-day top-up for late-priced matches)
    for hour, minute in [(7, 30), (15, 0)]:
        scheduler.add_job(
            _run_odds_refresh,
            CronTrigger(hour=hour, minute=minute),
            id=f"odds_refresh_{hour:02d}{minute:02d}",
            name=f"Refresh bookmaker odds ({hour:02d}:{minute:02d} UTC)",
            replace_existing=True,
        )

    logger.info(
        "Scheduler started: fixture seeds at 01/10/18 UTC, scores every %dh, "
        "players at 05:00, data at 06:00, predictions at 07:00, odds at 07:30+15:00 UTC",
        score_interval,
    )

    try:
        _running = True
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        _running = False
        _scheduler = None


def start_scheduler():
    """Start the background scheduler thread (no-op if ENABLE_SCHEDULER != 'true')."""
    global _scheduler_thread

    if os.environ.get("ENABLE_SCHEDULER", "").lower() != "true":
        logger.info("Scheduler disabled (set ENABLE_SCHEDULER=true to enable)")
        return

    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.warning("Scheduler already running")
        return

    _scheduler_thread = Thread(target=_scheduler_loop, daemon=True, name="refresh-scheduler")
    _scheduler_thread.start()
    logger.info("Scheduler thread started")


def stop_scheduler():
    """Shut down the APScheduler cleanly so in-flight jobs can finish their DB work.

    No-op if the scheduler was never started. Cloud Run shutdown hits this on
    SIGTERM; without a real shutdown, DB sessions owned by in-flight jobs would
    leak because BlockingScheduler.shutdown() was never called.
    """
    global _running, _scheduler
    _running = False
    scheduler = _scheduler
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler shutdown complete")
        except Exception as e:
            logger.warning("Scheduler shutdown raised: %s", e)
    else:
        logger.info("Scheduler stop requested (not running)")
