"""add match_player_stats table

Revision ID: f3b4c5d6e7f8
Revises: e2f3a4b5c6d7
Create Date: 2026-04-29 23:30:00.000000

Adds a per-match per-player statistics table populated from API-Football's
/fixtures/players endpoint. One row per (match_id, player_api_football_id);
the unique constraint lets the cron-driven sync upsert rather than insert
on every refresh (running totals tick up during the match).

Used by:
  - services/match_player_stats_service (write side, fired by the existing
    cupcast-match-stats-sync cron every 5 min)
  - api/matches.get_match (read side, surfaces goal scorers + carded
    players to the MatchDetail page)
  - future ML feature pipeline (player form, in-form-goalscorer signals)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3b4c5d6e7f8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "match_player_stats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "match_id",
            sa.Integer(),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            sa.Integer(),
            sa.ForeignKey("teams.id"),
            nullable=False,
        ),
        sa.Column("player_api_football_id", sa.Integer(), nullable=False),
        sa.Column("player_name", sa.String(length=255), nullable=False),
        sa.Column("player_photo_url", sa.String(length=512), nullable=True),
        sa.Column("position", sa.String(length=8), nullable=True),
        sa.Column("jersey_number", sa.Integer(), nullable=True),
        sa.Column("minutes_played", sa.Integer(), nullable=True),
        sa.Column("rating", sa.Numeric(3, 1), nullable=True),
        sa.Column("goals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assists", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shots_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shots_on", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("yellow_cards", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("red_cards", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_starter", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "fetched_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "match_id",
            "player_api_football_id",
            name="uq_match_player_stats_match_player",
        ),
    )
    op.create_index(
        "ix_match_player_stats_match_id",
        "match_player_stats",
        ["match_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_match_player_stats_match_id", table_name="match_player_stats"
    )
    op.drop_table("match_player_stats")
