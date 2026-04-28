"""merge api_football_id and api_football_predictions branches

Revision ID: e2f3a4b5c6d7
Revises: c9d0e1f2a3b4, d1e2f3a4b5c6
Create Date: 2026-04-27 10:05:00.000000

Merge point for two independent branches that both descend from f2a3b4c5d6e7:

  Branch A: f2a3b4c5d6e7 → a3b4c5d6e7f8 → b8c9d0e1f2a3 → c9d0e1f2a3b4
    - dedupe matches + unique constraint
    - add matches.current_minute
    - add api_football_predictions table

  Branch B: f2a3b4c5d6e7 → d1e2f3a4b5c6
    - add matches.api_football_id column + index

Both branches are orthogonal (different tables / different columns on matches).
No DDL here — this is a bookkeeping-only merge to bring the graph back to a
single head so 'alembic upgrade head' works cleanly.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, tuple[str, ...], None] = ("c9d0e1f2a3b4", "d1e2f3a4b5c6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
