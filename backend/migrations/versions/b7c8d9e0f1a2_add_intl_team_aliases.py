"""add intl team aliases

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-04-24 00:00:00.000000

Adds 6 aliases discovered during the intl-audit-2026-04-24 pass:
  - ESPN uses variant spellings that don't match our canonical names.
  - These cover all WC 2026 qualifier name mismatches found in the ESPN
    scoreboard feed for fifa.world.
  - Source tag 'intl-audit-2026-04-24' makes every inserted row traceable.

Parquet (intl_matches.parquet) audit notes:
  - 285 total unresolved team names (333 unique teams, 48 canonical in DB).
  - 274 are correctly absent (non-WC nations, micronations, historical/regional
    teams, and Republic of Congo which is distinct from DRC).
  - 10 are WC 2026 qualifiers missing from the seed (Category C — handled
    separately, not this migration): Albania, Costa Rica, Denmark, Hungary,
    Poland, Romania, Serbia, Slovakia, Ukraine, Venezuela.
  - 1 potential alias candidate ('Congo') was rejected because the parquet
    uses both 'Congo' and 'Democratic Republic of Congo' as distinct entries
    in the same match rows (verified row 5790, 6011, etc.), so mapping Congo
    to DRC would be factually wrong.
  - Net Category A from parquet: 0 aliases.

ESPN (fifa.world scoreboard) audit notes:
  - 62 unresolved names; 56 are bracket placeholders (Group X Winner/2nd,
    Round of 32/16, Third Place Group combos) — correctly absent.
  - 6 are real WC 2026 team name variants that map to existing canonical teams.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCE = 'intl-audit-2026-04-24'

# Each entry: (alias, canonical_name)
# team_id resolved via SELECT at runtime so this migration is environment-safe.
_ALIASES = [
    ('Bosnia-Herzegovina', 'Bosnia and Herzegovina'),
    ('Congo DR',           'Democratic Republic of Congo'),
    ('Curacao',            'Curaçao'),
    ('Czechia',            'Czech Republic'),
    ('Ivory Coast',        "Côte d'Ivoire"),
    ('Türkiye',            'Turkey'),
]


def upgrade() -> None:
    conn = op.get_bind()

    for alias_name, canonical_name in _ALIASES:
        # Resolve team_id at migration time — portable across SQLite and Postgres.
        row = conn.execute(
            sa.text("SELECT id FROM teams WHERE canonical_name = :name"),
            {"name": canonical_name},
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"Cannot insert alias {alias_name!r}: canonical team "
                f"{canonical_name!r} not found in teams table. "
                f"Ensure seed_database.py has run before this migration."
            )
        team_id = row[0]

        # Skip if this exact alias already exists (idempotent re-run safety).
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
    op.execute(
        sa.text(
            "DELETE FROM team_name_aliases WHERE source = :source"
        ).bindparams(source=_SOURCE)
    )
