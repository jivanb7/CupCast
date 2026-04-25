"""
backend/main.py
================
FastAPI application factory.

Registers all routers, configures CORS, adds health check endpoint,
and manages application lifespan (startup/shutdown hooks).

Startup:
  - Create all DB tables (via Base.metadata.create_all) — safe for SQLite dev.
    For PostgreSQL/production, use Alembic migrations instead.
  - Log MLFlow tracking URI
  (Production model is loaded lazily on first prediction request,
   not at startup, to keep cold-start time fast.)

CORS:
  Allows all origins in development. In production, restrict to the
  frontend Cloud Run URL. Configure via ALLOWED_ORIGINS env var if needed.

API prefix: /api/v1

Endpoints registered:
  /api/v1/matches/*    → api/matches.py
  /api/v1/predictions/* → api/predictions.py
  /api/v1/leagues/*    → api/leagues.py
  /api/v1/teams/*      → api/teams.py
  /api/v1/worldcup/*   → api/worldcup.py
  /api/v1/model/*      → api/model_perf.py
  /api/v1/admin/*      → api/admin.py (protected by ADMIN_API_KEY header)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.matches import router as matches_router
from api.predictions import router as predictions_router
from api.leagues import router as leagues_router
from api.teams import router as teams_router
from api.worldcup import router as worldcup_router
from api.world_cup import router as world_cup_router
from api.model_perf import router as model_perf_router
from api.admin import router as admin_router
from api.live import router as live_router
from database import engine, Base

# Import all models so Base.metadata knows about all tables
import models  # noqa: F401

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — create all tables if they don't exist (SQLite dev mode).
    # In production against PostgreSQL, Alembic handles schema migrations.
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified / created.")
    except Exception as e:
        logger.error("Database initialization failed: %s — server starting with degraded DB", e)

    # Export MLflow credentials from settings (.env) into os.environ.
    # MLflow's client reads tracking URI / username / password directly from
    # os.environ, NOT from the Settings object — so without this hop,
    # local dev relying on a .env file silently falls back to defaults
    # and `mlflow.load_model()` fails with auth or "model not found" errors.
    # Cloud Run sets these as container env vars directly, so this is a no-op
    # in production but a real fix for any environment that uses .env.
    import os as _os
    from config import settings as _settings
    _os.environ.setdefault("MLFLOW_TRACKING_URI", _settings.mlflow_tracking_uri)
    if _settings.mlflow_tracking_username:
        _os.environ.setdefault("MLFLOW_TRACKING_USERNAME", _settings.mlflow_tracking_username)
    if _settings.mlflow_tracking_password:
        _os.environ.setdefault("MLFLOW_TRACKING_PASSWORD", _settings.mlflow_tracking_password)
    logger.info("MLflow tracking URI configured: %s", _settings.mlflow_tracking_uri)

    # Security warning for default admin key
    if _settings.admin_api_key == "changeme":
        logger.warning("SECURITY: admin_api_key is set to default 'changeme' — set ADMIN_API_KEY in .env for production")

    # Start background refresh scheduler (only if ENABLE_SCHEDULER=true)
    from services.refresh_scheduler import start_scheduler, stop_scheduler
    try:
        start_scheduler()
    except Exception as e:
        logger.error("Scheduler failed to start: %s — continuing without scheduled tasks", e)

    # Single background thread: refresh fixtures → seed → predict → backfill scores
    # Order matters: fixtures must be seeded as "scheduled" before score backfill
    # marks them as "completed", otherwise predictions can't be written.
    #
    # Production (Cloud Run): skipped. Cloud Run spins up new instances on cold
    # start, and running the full pipeline every cold start would hammer the DB
    # and the upstream APIs. In prod, Cloud Scheduler hits /admin/* on the
    # schedule defined in infra/gcp/scheduler.sh instead.
    from config import settings as _prod_settings
    _is_prod = _prod_settings.environment == "production"
    from threading import Thread

    def _startup_data_refresh():
        import subprocess, sys
        from pathlib import Path

        # Step 1: Download + process fresh fixtures
        try:
            from services.data_service import trigger_data_refresh, trigger_prediction_generation
            print("[STARTUP] Step 1/4: Refreshing fixtures...", flush=True)
            if trigger_data_refresh():
                # Step 2: Seed new fixtures into DB as "scheduled"
                print("[STARTUP] Step 2/4: Seeding fixtures to DB...", flush=True)
                seed_script = Path(__file__).resolve().parent.parent / "scripts" / "seed_database.py"
                result = subprocess.run(
                    [sys.executable, str(seed_script)],
                    cwd=str(Path(__file__).resolve().parent.parent),
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    print(f"[STARTUP] Seed failed: {result.stderr[-300:]}", flush=True)

                # Step 2b: Seed UCL fixtures (separate from domestic seed script)
                try:
                    from services.ucl_fixture_service import seed_ucl_fixtures_to_db
                    from database import SessionLocal
                    db = SessionLocal()
                    try:
                        ucl_count = seed_ucl_fixtures_to_db(db)
                        print(f"[STARTUP] Seeded {ucl_count} UCL fixtures", flush=True)
                    finally:
                        db.close()
                except Exception as e:
                    print(f"[STARTUP] UCL fixture seeding failed: {e}", flush=True)

                # Step 3: Generate predictions for scheduled matches
                print("[STARTUP] Step 3/4: Generating predictions...", flush=True)
                trigger_prediction_generation()
                print("[STARTUP] Predictions done", flush=True)
            else:
                print("[STARTUP] Fixture refresh failed, skipping seed + predictions", flush=True)
        except Exception as e:
            print(f"[STARTUP] Fixture refresh error: {e}", flush=True)

        # Step 4: Backfill scores (runs after predictions so scheduled matches get predictions first)
        try:
            from database import SessionLocal
            from services.score_updater import update_scores
            print("[STARTUP] Step 4/4: Backfilling scores...", flush=True)
            db = SessionLocal()
            try:
                stats = update_scores(db)
                print(f"[STARTUP] Score backfill: {stats}", flush=True)
            finally:
                db.close()
        except Exception as e:
            print(f"[STARTUP] Score backfill failed: {e}", flush=True)

        print("[STARTUP] All startup tasks complete", flush=True)

    if _is_prod:
        logger.info("Startup data-refresh thread skipped (prod — Cloud Scheduler handles this)")
    else:
        Thread(target=_startup_data_refresh, daemon=True, name="startup-refresh").start()

    # Initialize API-Football key rotator from comma-separated key list
    from config import settings
    from services.api_key_rotator import init_rotator
    api_football_keys = [k.strip() for k in settings.api_football_keys.split(",") if k.strip()]
    if api_football_keys:
        init_rotator(api_football_keys)

    # Auto-start live score polling if any API key is configured.
    # Production: skipped. In-process polling doesn't survive Cloud Run scale-to-zero
    # and duplicates across concurrent instances. Cloud Scheduler drives
    # /admin/scores/update every 2 min during match windows instead
    # (see infra/gcp/scheduler.sh).
    from services.live_score_service import live_scores
    if _is_prod:
        logger.info("Live score polling skipped (prod — Cloud Scheduler handles this)")
    else:
        try:
            has_api_football = bool(api_football_keys)
            if settings.football_data_org_api_key or has_api_football:
                live_scores.configure(
                    api_key=settings.football_data_org_api_key,
                    poll_interval=10,
                    use_api_football_rotator=has_api_football,
                )
                live_scores.start()
        except Exception as e:
            logger.error("Live score polling failed to start: %s — continuing without live scores", e)

    yield

    # Shutdown
    try:
        live_scores.stop()
    except Exception:
        pass
    try:
        stop_scheduler()
    except Exception:
        pass


app = FastAPI(
    title="CupCast API",
    description="ML-powered soccer match predictions",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO (security-reviewer): restrict in production
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Health check — required by Docker Compose healthcheck and GCP Cloud Run
@app.get("/health", tags=["system"])
def health_check():
    from sqlalchemy import text
    from database import SessionLocal
    db_status = "connected"
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception:
        db_status = "unavailable"
    return {"status": "ok", "database": db_status}


app.include_router(matches_router, prefix="/api/v1")
app.include_router(predictions_router, prefix="/api/v1")
app.include_router(leagues_router, prefix="/api/v1")
app.include_router(teams_router, prefix="/api/v1")
app.include_router(worldcup_router, prefix="/api/v1")
app.include_router(world_cup_router, prefix="/api/v1")
app.include_router(model_perf_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(live_router, prefix="/api/v1")
