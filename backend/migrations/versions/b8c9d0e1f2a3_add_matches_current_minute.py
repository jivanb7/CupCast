"""add matches.current_minute

Revision ID: b8c9d0e1f2a3
Revises: a3b4c5d6e7f8
Create Date: 2026-04-26 19:35:00.000000

Adds a small ``current_minute`` column (e.g. "33'", "45'+2'", "HT", "67'") so
the live-score sync can persist ESPN's authoritative match clock to the DB.
Without this column the minute lived in the per-instance in-memory cache,
and Cloud Run runs up to 3 instances — so the API request landed on a
different instance from the cron most of the time and silently returned
None or a stale value. With the value in the DB, every instance reads the
same fresh minute and the LIVE ticker on the frontend tracks ESPN within
~60 s (the cron cadence).

NULL when the match is not in play. Cleared back to NULL when the match
finalises so completed-match cards don't carry a stale ticker.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("matches") as batch_op:
        batch_op.add_column(
            sa.Column("current_minute", sa.String(length=10), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("matches") as batch_op:
        batch_op.drop_column("current_minute")
