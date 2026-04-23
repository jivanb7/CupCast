"""
backend/config.py
==================
Application configuration via Pydantic Settings.
Reads from environment variables (or .env file via python-dotenv).

All env var names match .env.example exactly.
Import and use `settings` singleton throughout the application.

Usage:
    from config import settings
    url = settings.database_url
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve SQLite path relative to backend/ dir so it works regardless of cwd
_BACKEND_DIR = Path(__file__).resolve().parent
_DEFAULT_DB_URL = f"sqlite:///{_BACKEND_DIR / 'cupcast_dev.db'}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Environment: "dev" uses SQLite, anything else uses DATABASE_URL as-is (Postgres)
    environment: str = "dev"

    # Database — defaults to SQLite for local dev (absolute path).
    # In production, set DATABASE_URL to a Postgres connection string.
    database_url: str = _DEFAULT_DB_URL

    # MLflow tracking server — the backend resolves `models:/<name>@prod`
    # URIs at load time, so Cloud Run must be able to reach this host.
    # In prod this is the Caddy-fronted HTTPS endpoint with basic auth.
    mlflow_tracking_uri: str = "http://localhost:5000"
    # Basic auth credentials for the tracking server. MLflow picks these up
    # automatically from MLFLOW_TRACKING_USERNAME/PASSWORD env vars — we
    # still declare them here so pydantic validates they're set in prod.
    mlflow_tracking_username: str = ""
    mlflow_tracking_password: str = ""

    # Registered model names in the MLflow Model Registry. The `@prod` alias
    # resolves to whichever version is currently in production — flip the
    # alias after retraining to promote a new model with no redeploy.
    mlflow_model_club: str = "cupcast-club-model"
    mlflow_model_club_top5: str = "cupcast-club-top5-model"
    mlflow_model_intl: str = "cupcast-international-model"

    # GCP (optional — only required in production)
    gcp_project_id: str = ""
    gcs_bucket: str = ""
    gcp_region: str = "us-central1"

    # Admin endpoint protection
    admin_api_key: str = "changeme"

    # Football-Data.org API (for top-league live scores)
    football_data_org_api_key: str = ""

    # API-Football (api-sports.io) — covers lower leagues + MLS
    # Comma-separated list of keys, e.g. "key1,key2,key3"
    # Up to 6 keys supported; each key gets 100 req/day = 600 total.
    api_football_keys: str = ""

    # SQLAlchemy pool config (for Postgres connection pooling)
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True

    # Background refresh scheduler (APScheduler). "true" to enable locally.
    # In GCP production, keep false and use Cloud Scheduler to hit /admin/*.
    enable_scheduler: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment != "dev"


settings = Settings()
