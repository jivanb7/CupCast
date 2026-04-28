"""add api_football_id to matches

Revision ID: d1e2f3a4b5c6
Revises: f2a3b4c5d6e7
Create Date: 2026-04-27 10:00:00.000000

Adds matches.api_football_id — the API-Football fixture ID for rows seeded from
the API-Football data source (UCL fixtures, odds-injected matches, etc.).

Why this column exists:
  The api_football_predictions_service previously mapped every internal Match
  row → API-Football fixture ID at query time via a team-name fuzzy lookup
  against /fixtures. That resolver matched only ~81 of 600+ matches attempted
  in a recent backfill — canonical name mismatches between our DB and API-Football
  caused silent skips for the majority of rows.

  Storing the fixture ID at seed time (when we already have the raw API response
  in hand) eliminates the lookup entirely for API-Football-sourced rows and
  reduces prediction coverage failures to a near-zero floor. Legacy rows from
  football-data.co.uk CSV ingest remain NULL; those still use the name-resolver
  fallback.

Schema decisions:
  - nullable=True: historical CSV rows have no API-Football ID.
  - NOT unique: multiple rows could theoretically share a fixture ID if a match
    is re-seeded under a different internal ID (edge case), and NULL rows from
    CSV ingest must not conflict. A non-unique index is sufficient for the
    fast-path lookup in api_football_predictions_service.
  - Integer: API-Football fixture IDs fit in a 32-bit int.

Down: drops the index then the column. Safe — no data relies on this column
for integrity; the predictions service falls back to the name resolver.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("api_football_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_matches_api_football_id",
        "matches",
        ["api_football_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_matches_api_football_id", table_name="matches")
    op.drop_column("matches", "api_football_id")
