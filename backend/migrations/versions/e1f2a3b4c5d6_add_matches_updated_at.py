"""add matches.updated_at

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-04-24 00:00:00.000000

Adds an ``updated_at`` timestamp column to ``matches`` so the score updater
can decide whether a recently-completed match should be cross-checked against
a secondary source (API-Football) within a freshness window. Without this,
the existing ``if match.status == 'completed': continue`` short-circuit locks
in any intermediate score that ever made it into the DB (e.g. Real Betis 0-1
Real Madrid on 2026-04-24, where Betis equalised after our updater ran).

Default + backfill: ``CURRENT_TIMESTAMP`` so existing rows immediately fall
outside the 6-hour re-check window (treating them as already-finalised).
The score_updater path that *changes* a match must set this column going
forward.

Downgrade simply drops the column.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable first (SQLite limitation: can't add NOT NULL with non-constant default
    # in a single ALTER), then backfill, then no need to enforce NOT NULL — the ORM and
    # write paths set it explicitly, and a NULL means "never updated since insert".
    with op.batch_alter_table("matches") as batch_op:
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=True,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )

    # Backfill existing rows so they aren't NULL (newly added column on existing rows
    # may not pick up the server_default in every backend).
    op.execute("UPDATE matches SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("matches") as batch_op:
        batch_op.drop_column("updated_at")
