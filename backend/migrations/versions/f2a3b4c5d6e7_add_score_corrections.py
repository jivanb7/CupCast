"""add score_corrections audit table

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-04-24 12:00:00.000000

Persistent audit log of every score correction the system makes after a match
was first marked 'completed'. Two writers populate this table:

  - scripts/revalidate_recent_scores.py (batch cross-check vs API-Football)
  - services/score_updater.py (in-window 6-hour catch-up writes)

Each row captures the before/after score, who made the change (``source``),
how many predictions had to be re-evaluated, and a ``run_id`` that groups
corrections from the same revalidation pass.

Why a separate table (vs reusing match.updated_at):
  match.updated_at only tells you *that* a match changed. The audit log lets
  the health endpoint count corrections per window, future alerting can fire
  on bursts, and we can debug "what did this match used to be" after the fact.

Index strategy:
  - (match_id) — pull a single match's audit trail
  - (corrected_at desc) — the health endpoint scans recent corrections
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "score_corrections",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "match_id",
            sa.Integer(),
            sa.ForeignKey("matches.id"),
            nullable=False,
        ),
        sa.Column(
            "corrected_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("before_home_goals", sa.SmallInteger(), nullable=True),
        sa.Column("before_away_goals", sa.SmallInteger(), nullable=True),
        sa.Column("before_result", sa.String(length=1), nullable=True),
        sa.Column("after_home_goals", sa.SmallInteger(), nullable=False),
        sa.Column("after_away_goals", sa.SmallInteger(), nullable=False),
        sa.Column("after_result", sa.String(length=1), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column(
            "predictions_reevaluated",
            sa.SmallInteger(),
            nullable=True,
            server_default=sa.text("0"),
        ),
        sa.Column("run_id", sa.String(length=40), nullable=False),
    )
    op.create_index(
        "ix_score_corrections_match_id", "score_corrections", ["match_id"]
    )
    op.create_index(
        "ix_score_corrections_corrected_at",
        "score_corrections",
        [sa.text("corrected_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_score_corrections_corrected_at", table_name="score_corrections")
    op.drop_index("ix_score_corrections_match_id", table_name="score_corrections")
    op.drop_table("score_corrections")
