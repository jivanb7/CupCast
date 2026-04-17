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
_running = False


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
    except Exception as e:
        logger.error("Scheduler: score update failed — %s", e)
    finally:
        db.close()


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
    global _running

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

    logger.info(
        "Scheduler started: fixture seeds at 01/10/18 UTC, scores every %dh, "
        "players at 05:00, data at 06:00, predictions at 07:00 UTC",
        score_interval,
    )

    try:
        _running = True
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        _running = False


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
    """Signal the scheduler to stop (it will exit on next check)."""
    global _running
    _running = False
    logger.info("Scheduler stop requested")
