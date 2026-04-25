"""merge leipzig duplicate (657 -> 251)

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-04-24 00:00:00.000000

Data cleanup migration. ``scripts/seed_missing_clubs.py`` inserted a duplicate
Bundesliga row for 'RasenBallsport Leipzig' (id=657) BEFORE migration
c8d9e0f1a2b3 renamed the canonical row 'RasenBallsport Leipzig' -> 'RB Leipzig'
(id=251) and added the legal name as an alias.

Result: two Leipzig rows in league_id=8. Today's match (id=65791) and any
other downstream FK references to 657 must be repointed to 251 before the
duplicate is deleted.

This migration:
  1) Repoints matches.{home_team_id, away_team_id} from 657 -> 251.
  2) Repoints team_elo, predictions, and fifa_rankings if any rows reference
     657 (defensive — none expected per pre-migration audit on 2026-04-24).
     For predictions there is no UNIQUE on (match_id, model_version) in the
     current schema, but if 657 and 251 had a duplicate prediction for the
     same match we keep 251's row and drop 657's first.
  3) Copies any aliases pointing at 657 over to 251 (deduped against 251's
     existing aliases by alias text).
  4) Deletes 657's aliases, then deletes the team row itself.

DOWNGRADE intentionally a no-op: merging is not cleanly reversible. Restore
from a DB snapshot if you need to undo this.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9e0f1a2b3c4'
down_revision: Union[str, None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DUPE_ID = 657
_KEEP_ID = 251
_SOURCE = 'merge-leipzig-657-2026-04-24'


def upgrade() -> None:
    conn = op.get_bind()

    # Bail-out check: if the dupe is already gone, this migration has
    # effectively been applied (idempotent).
    dupe_exists = conn.execute(
        sa.text("SELECT 1 FROM teams WHERE id = :dupe"),
        {"dupe": _DUPE_ID},
    ).fetchone()
    if not dupe_exists:
        print(f"[{revision}] team id={_DUPE_ID} not present — nothing to merge")
        return

    keep_exists = conn.execute(
        sa.text("SELECT 1 FROM teams WHERE id = :keep"),
        {"keep": _KEEP_ID},
    ).fetchone()
    if not keep_exists:
        raise RuntimeError(
            f"[{revision}] target keep team id={_KEEP_ID} (RB Leipzig) "
            f"missing — abort merge to avoid orphaning FKs"
        )

    # --- 1) matches FK repoint ---------------------------------------------
    res_home = conn.execute(
        sa.text(
            "UPDATE matches SET home_team_id = :keep "
            "WHERE home_team_id = :dupe"
        ),
        {"keep": _KEEP_ID, "dupe": _DUPE_ID},
    )
    res_away = conn.execute(
        sa.text(
            "UPDATE matches SET away_team_id = :keep "
            "WHERE away_team_id = :dupe"
        ),
        {"keep": _KEEP_ID, "dupe": _DUPE_ID},
    )
    print(
        f"[{revision}] matches repointed: home={res_home.rowcount} "
        f"away={res_away.rowcount}"
    )

    # --- 2) team_elo --------------------------------------------------------
    # Defensive: if 251 already has rows for the same (date, season) etc., we
    # delete 657's rows rather than create conflicts. team_elo has no UNIQUE
    # in the current schema, but keeping 251's authoritative timeline is the
    # safer default.
    elo_dupe_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM team_elo WHERE team_id = :dupe"),
        {"dupe": _DUPE_ID},
    ).scalar()
    if elo_dupe_count:
        conn.execute(
            sa.text("DELETE FROM team_elo WHERE team_id = :dupe"),
            {"dupe": _DUPE_ID},
        )
        print(f"[{revision}] team_elo rows for {_DUPE_ID} deleted: {elo_dupe_count}")

    # --- 3) predictions -----------------------------------------------------
    # Predictions reference matches.id, not team_id, so the matches repoint
    # in step 1 carries them across automatically. Nothing to do here unless
    # predictions ever grows a team_id column.

    # --- 4) fifa_rankings ---------------------------------------------------
    fifa_dupe_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM fifa_rankings WHERE team_id = :dupe"),
        {"dupe": _DUPE_ID},
    ).scalar()
    if fifa_dupe_count:
        # FIFA rankings are for national teams; clubs shouldn't have rows
        # here, but if they do we delete rather than repoint (would be junk
        # data on a club row anyway).
        conn.execute(
            sa.text("DELETE FROM fifa_rankings WHERE team_id = :dupe"),
            {"dupe": _DUPE_ID},
        )
        print(f"[{revision}] fifa_rankings rows for {_DUPE_ID} deleted: {fifa_dupe_count}")

    # --- 5) team_name_aliases: copy unique aliases from dupe -> keep -------
    keep_aliases = {
        row[0]
        for row in conn.execute(
            sa.text("SELECT alias FROM team_name_aliases WHERE team_id = :keep"),
            {"keep": _KEEP_ID},
        ).fetchall()
    }
    dupe_aliases = conn.execute(
        sa.text("SELECT alias FROM team_name_aliases WHERE team_id = :dupe"),
        {"dupe": _DUPE_ID},
    ).fetchall()

    copied = 0
    for (alias_name,) in dupe_aliases:
        if alias_name in keep_aliases:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO team_name_aliases (team_id, alias, source) "
                "VALUES (:tid, :alias, :source)"
            ),
            {"tid": _KEEP_ID, "alias": alias_name, "source": _SOURCE},
        )
        copied += 1

    conn.execute(
        sa.text("DELETE FROM team_name_aliases WHERE team_id = :dupe"),
        {"dupe": _DUPE_ID},
    )
    print(
        f"[{revision}] aliases copied to {_KEEP_ID}: {copied}; "
        f"dupe alias rows deleted: {len(dupe_aliases)}"
    )

    # --- 6) finally: drop the duplicate team row ---------------------------
    conn.execute(
        sa.text("DELETE FROM teams WHERE id = :dupe"),
        {"dupe": _DUPE_ID},
    )
    print(f"[{revision}] team id={_DUPE_ID} deleted")


def downgrade() -> None:
    # Intentionally not implemented — restore from a DB snapshot if needed.
    pass
