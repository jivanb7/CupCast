"""rename rb leipzig and add club aliases

Revision ID: c8d9e0f1a2b3
Revises: 56a015708c89
Create Date: 2026-04-24 00:00:00.000000

Two related fixes for the logo backfill (logo-backfill-2026-04-24):

  1) Rename the German Bundesliga side from its legal name
     'RasenBallsport Leipzig' to its branded name 'RB Leipzig' so the
     UI matches what every fan, broadcaster and API-Football call them.
     The legal name is preserved as an alias so historical importers
     (and any feed that uses the long form) still resolve.

  2) Add a handful of short-form aliases the API-Football payload uses
     but our seed canonical names don't cover, so the strict-match logo
     backfill can find:
       - Wolverhampton Wanderers ← 'Wolves'
       - Queens Park Rangers     ← 'QPR'
       - Stade Rennais FC        ← 'Rennes', 'Stade Rennais'

  Each alias is tagged source='logo-backfill-2026-04-24' for clean
  reverse-out in downgrade().

The migration resolves team_id at runtime (env-safe). If a candidate's
canonical_name isn't present in the DB, the alias is skipped with a
warning rather than blowing up.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, None] = '56a015708c89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCE = 'logo-backfill-2026-04-24'

# (alias, canonical_name) — canonical_name resolved post-rename, so the
# RB Leipzig aliases reference the new name.
_ALIASES = [
    # Bundesliga: keep legal name resolvable after the rename.
    ('RasenBallsport Leipzig', 'RB Leipzig'),
    ('RasenBallsport Lpz',     'RB Leipzig'),
    # EPL / Championship short forms used by API-Football + most feeds.
    ('Wolves',                 'Wolverhampton Wanderers'),
    ('QPR',                    'Queens Park Rangers'),
    # Ligue 1 — API-Football returns 'Rennes', our canonical is the long form.
    ('Rennes',                 'Stade Rennais FC'),
    ('Stade Rennais',          'Stade Rennais FC'),
]


def upgrade() -> None:
    conn = op.get_bind()

    # --- 1) Rename RasenBallsport Leipzig → RB Leipzig --------------------
    # Idempotent: only renames if the old name is still present.
    conn.execute(
        sa.text(
            "UPDATE teams SET canonical_name = 'RB Leipzig' "
            "WHERE canonical_name = 'RasenBallsport Leipzig'"
        )
    )

    # --- 2) Insert aliases ------------------------------------------------
    for alias_name, canonical_name in _ALIASES:
        row = conn.execute(
            sa.text("SELECT id FROM teams WHERE canonical_name = :name"),
            {"name": canonical_name},
        ).fetchone()
        if row is None:
            # Don't fail the whole migration on a missing seed row — log
            # and skip. The logo backfill will surface anything still
            # unmatched.
            print(
                f"[c8d9e0f1a2b3] skipping alias {alias_name!r}: "
                f"team {canonical_name!r} not found"
            )
            continue
        team_id = row[0]

        existing = conn.execute(
            sa.text(
                "SELECT id FROM team_name_aliases "
                "WHERE alias = :alias AND team_id = :tid"
            ),
            {"alias": alias_name, "tid": team_id},
        ).fetchone()
        if existing:
            continue

        conn.execute(
            sa.text(
                "INSERT INTO team_name_aliases (team_id, alias, source) "
                "VALUES (:team_id, :alias, :source)"
            ),
            {"team_id": team_id, "alias": alias_name, "source": _SOURCE},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse the alias inserts first (FK-safe — they reference teams.id,
    # which is unchanged either way).
    conn.execute(
        sa.text("DELETE FROM team_name_aliases WHERE source = :source"),
        {"source": _SOURCE},
    )

    # Reverse the rename.
    conn.execute(
        sa.text(
            "UPDATE teams SET canonical_name = 'RasenBallsport Leipzig' "
            "WHERE canonical_name = 'RB Leipzig'"
        )
    )
