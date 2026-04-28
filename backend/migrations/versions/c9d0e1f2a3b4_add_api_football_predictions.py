"""add api_football_predictions table

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-04-27 09:00:00.000000

Adds the api_football_predictions table which stores API-Football's proprietary
win-probability estimates (home / draw / away percentages) for each fixture.

These probabilities are ingested as ML features. API-Football's internal model
already aggregates lineup quality, xG history, and recent team form, so ingesting
their output gives our own model indirect access to all that signal without us
having to build or maintain the underlying features ourselves.

Schema decisions:
  - match_id is UNIQUE — one row per fixture, upserted on every refresh.
  - prob_home/draw/away are Float nullable — API-Football does not always
    return a percent block (e.g. postponed fixtures). NULL means "not available"
    and the feature-engineering layer should handle it as a missing feature.
  - raw_payload is JSONB nullable — preserves the full /predictions response for
    forward compatibility (goals estimate, advice string, winner comment, etc.)
    without requiring another API call when we want to extract new sub-features.
  - fetched_at has a server default so INSERT without explicit value still gets
    a timestamp.

Down: drops the table entirely. No data is irreplaceable — a re-run of
refresh_api_football_predictions.py --mode backfill restores it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_football_predictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "match_id",
            sa.Integer(),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prob_home", sa.Float(), nullable=True),
        sa.Column("prob_draw", sa.Float(), nullable=True),
        sa.Column("prob_away", sa.Float(), nullable=True),
        # Use JSONB on Postgres for indexing/querying sub-keys later;
        # fall back to plain JSON on SQLite (local dev).
        sa.Column(
            "raw_payload",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", name="uq_apifp_match_id"),
    )

    op.create_index(
        "ix_apifp_match_id",
        "api_football_predictions",
        ["match_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_apifp_match_id", table_name="api_football_predictions")
    op.drop_table("api_football_predictions")
