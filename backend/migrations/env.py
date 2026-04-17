"""
backend/migrations/env.py
==========================
Alembic environment configuration.

Uses DATABASE_URL from environment (not from alembic.ini) so the same
alembic setup works in both local development and CI/CD.

Run migrations:
  alembic upgrade head

Create a new migration:
  alembic revision --autogenerate -m "description"

IMPORTANT: All ORM models must be imported in backend/models/__init__.py
for alembic autogenerate to detect them.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all models so alembic autogenerate can see them
from database import Base
import models  # noqa: F401 — importing triggers __init__.py model imports

config = context.config

# Override sqlalchemy.url from env var
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
