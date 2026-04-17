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

    # MLFlow / Model loading
    mlflow_tracking_uri: str = "http://localhost:5000"
    model_load_mode: str = "registry"  # 'registry' or 'gcs'

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

    @property
    def is_production(self) -> bool:
        return self.environment != "dev"


settings = Settings()
