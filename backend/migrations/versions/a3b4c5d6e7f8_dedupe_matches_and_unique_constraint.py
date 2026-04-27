"""dedupe matches + dedupe DC United team + add matches unique constraint

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-04-25 17:00:00.000000

Two production data integrity bugs prompted this migration:

1. The user reported the same fixture appearing twice on /matches with
   conflicting predictions (e.g. Manchester United vs Brentford on Apr 27,
   one card picked Draw 34%, the other picked Brentford 37%). DB inspection
   showed 26 duplicate match groups across the next 14 days, plus a handful
   of completed-match dupes from earlier this week. Each group is exactly
   two rows created within ~1 minute of each other, suggesting a manual
   re-run of the seeder before dedup was tightened up.

2. The MLS team `D.C. United` (id 406) and `DC United` (id 408) are the same
   real-world club stored as two separate rows. ESPN/CSV sources hand us
   slightly different spellings, our `_resolve_team()` lookup picks one or
   the other inconsistently, and the result is yet more duplicate fixtures.

This migration runs in this order so each step is safe by the time the next
needs it:

  1. Merge team 408 into 406 (repoint matches FKs + aliases, then DELETE 408).
  2. Resnapshot match duplicates (step 1 may have created new ones once the
     team-id collapse is in place).
  3. For each match-dupe group, pick canonical = MIN(id), then for every
     non-canonical row:
       a. Repoint score_corrections.match_id   (no UC there — plain UPDATE).
       b. Reconcile predictions: for each (match_id, model_version) pair the
          dupe holds, if the canonical already has the same model_version we
          keep whichever was created later and DELETE the other; otherwise
          we repoint to the canonical. This respects uq_prediction_match_model.
       c. DELETE the duplicate match row.
  4. Finally, add the UNIQUE constraint that should always have been here:
     UNIQUE (home_team_id, away_team_id, league_id, match_date).

After this constraint exists, no future seeder bug can recreate the dupes;
fixture_seeder + espn_fixture_service are also being switched to PostgreSQL
ON CONFLICT DO UPDATE in the same branch so the IntegrityError surfaces as a
no-op merge rather than an exception.

Idempotent: each step bails out cleanly if the work is already done.
DOWNGRADE intentionally a no-op — restore from a snapshot if needed.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# DC United merge: keep the lower id (406, "D.C. United") because that's the
# row matched by canonical_name in our existing TEAM_NAME_MAP.
_DC_DUPE_ID = 408
_DC_KEEP_ID = 406
_MIGRATION_SOURCE = 'dedupe-matches-2026-04-25'


def upgrade() -> None:
    conn = op.get_bind()

    # SQLite (local dev) lacks ARRAY_AGG / pg_constraint and the production
    # dedup work this migration addresses doesn't exist there. No-op so the
    # local chain can continue to b8c9d0e1f2a3.
    if conn.dialect.name == "sqlite":
        print(f"[{revision}] sqlite dialect — skipping Postgres-only dedup work")
        return

    # ------------------------------------------------------------------
    # 1) Merge "DC United" (id 408) into "D.C. United" (id 406)
    # ------------------------------------------------------------------
    dupe_team_exists = conn.execute(
        sa.text("SELECT 1 FROM teams WHERE id = :dupe"),
        {"dupe": _DC_DUPE_ID},
    ).fetchone()

    if dupe_team_exists:
        keep_team_exists = conn.execute(
            sa.text("SELECT 1 FROM teams WHERE id = :keep"),
            {"keep": _DC_KEEP_ID},
        ).fetchone()
        if not keep_team_exists:
            raise RuntimeError(
                f"[{revision}] target team id={_DC_KEEP_ID} (D.C. United) "
                "missing — abort merge to avoid orphan FKs"
            )

        res_home = conn.execute(
            sa.text(
                "UPDATE matches SET home_team_id = :keep "
                "WHERE home_team_id = :dupe"
            ),
            {"keep": _DC_KEEP_ID, "dupe": _DC_DUPE_ID},
        )
        res_away = conn.execute(
            sa.text(
                "UPDATE matches SET away_team_id = :keep "
                "WHERE away_team_id = :dupe"
            ),
            {"keep": _DC_KEEP_ID, "dupe": _DC_DUPE_ID},
        )
        print(
            f"[{revision}] DC United merge: matches repointed home={res_home.rowcount} "
            f"away={res_away.rowcount}"
        )

        # team_elo / fifa_rankings — defensive, no UC here so plain delete-on-dupe
        for table in ("team_elo", "fifa_rankings"):
            n = conn.execute(
                sa.text(f"SELECT COUNT(*) FROM {table} WHERE team_id = :dupe"),
                {"dupe": _DC_DUPE_ID},
            ).scalar()
            if n:
                conn.execute(
                    sa.text(f"DELETE FROM {table} WHERE team_id = :dupe"),
                    {"dupe": _DC_DUPE_ID},
                )
                print(f"[{revision}] {table} rows for {_DC_DUPE_ID} deleted: {n}")

        # Aliases: copy any non-redundant aliases over, then delete dupe's.
        keep_aliases = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT alias FROM team_name_aliases WHERE team_id = :keep"),
                {"keep": _DC_KEEP_ID},
            ).fetchall()
        }
        dupe_aliases = conn.execute(
            sa.text("SELECT alias FROM team_name_aliases WHERE team_id = :dupe"),
            {"dupe": _DC_DUPE_ID},
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
                {"tid": _DC_KEEP_ID, "alias": alias_name, "source": _MIGRATION_SOURCE},
            )
            copied += 1
        conn.execute(
            sa.text("DELETE FROM team_name_aliases WHERE team_id = :dupe"),
            {"dupe": _DC_DUPE_ID},
        )

        # Also add 'DC United' itself as an alias on the canonical row so future
        # source variants resolve correctly.
        if 'DC United' not in keep_aliases:
            conn.execute(
                sa.text(
                    "INSERT INTO team_name_aliases (team_id, alias, source) "
                    "VALUES (:tid, :alias, :source) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"tid": _DC_KEEP_ID, "alias": "DC United", "source": _MIGRATION_SOURCE},
            )

        # Finally drop the duplicate team row.
        conn.execute(
            sa.text("DELETE FROM teams WHERE id = :dupe"),
            {"dupe": _DC_DUPE_ID},
        )
        print(f"[{revision}] team id={_DC_DUPE_ID} (DC United) deleted; aliases copied: {copied}")
    else:
        print(f"[{revision}] DC United dupe (id={_DC_DUPE_ID}) not present — skipping team merge")

    # ------------------------------------------------------------------
    # 2) Resnapshot match dupe groups (after team merge)
    # ------------------------------------------------------------------
    dupe_groups = conn.execute(
        sa.text("""
            SELECT home_team_id, away_team_id, league_id, match_date,
                   ARRAY_AGG(id ORDER BY id) AS ids
            FROM matches
            GROUP BY home_team_id, away_team_id, league_id, match_date
            HAVING COUNT(*) > 1
        """)
    ).fetchall()

    if not dupe_groups:
        print(f"[{revision}] no match dupes found — skipping match dedup")
    else:
        total_pred_repointed = 0
        total_pred_deleted = 0
        total_corr_repointed = 0
        total_matches_deleted = 0

        for row in dupe_groups:
            ids = list(row.ids)
            canonical = ids[0]
            dupes = ids[1:]

            for dupe in dupes:
                # 3a) score_corrections — no UC, plain repoint
                res_corr = conn.execute(
                    sa.text(
                        "UPDATE score_corrections SET match_id = :keep "
                        "WHERE match_id = :dupe"
                    ),
                    {"keep": canonical, "dupe": dupe},
                )
                total_corr_repointed += res_corr.rowcount or 0

                # 3b) predictions — must respect uq_prediction_match_model.
                # For every (model_version) the dupe holds, decide:
                #   - canonical also has it: keep the more-recent one, delete other.
                #   - canonical doesn't:    repoint dupe's row to canonical.
                dupe_preds = conn.execute(
                    sa.text(
                        "SELECT id, model_version, created_at "
                        "FROM predictions WHERE match_id = :dupe"
                    ),
                    {"dupe": dupe},
                ).fetchall()

                for pred in dupe_preds:
                    canonical_pred = conn.execute(
                        sa.text(
                            "SELECT id, created_at FROM predictions "
                            "WHERE match_id = :keep AND model_version = :mv"
                        ),
                        {"keep": canonical, "mv": pred.model_version},
                    ).fetchone()

                    if canonical_pred is None:
                        # Free to repoint.
                        conn.execute(
                            sa.text(
                                "UPDATE predictions SET match_id = :keep WHERE id = :pid"
                            ),
                            {"keep": canonical, "pid": pred.id},
                        )
                        total_pred_repointed += 1
                    else:
                        # Conflict: keep the newer prediction, delete the older.
                        # (created_at can be NULL on legacy rows — treat NULL as oldest.)
                        dupe_ts = pred.created_at
                        keep_ts = canonical_pred.created_at
                        if dupe_ts is not None and (keep_ts is None or dupe_ts > keep_ts):
                            # Dupe's prediction is newer — overwrite canonical's.
                            conn.execute(
                                sa.text("DELETE FROM predictions WHERE id = :pid"),
                                {"pid": canonical_pred.id},
                            )
                            conn.execute(
                                sa.text(
                                    "UPDATE predictions SET match_id = :keep WHERE id = :pid"
                                ),
                                {"keep": canonical, "pid": pred.id},
                            )
                            total_pred_repointed += 1
                            total_pred_deleted += 1
                        else:
                            # Canonical's is newer (or same age) — drop the dupe's.
                            conn.execute(
                                sa.text("DELETE FROM predictions WHERE id = :pid"),
                                {"pid": pred.id},
                            )
                            total_pred_deleted += 1

                # 3c) Drop the duplicate match row.
                conn.execute(
                    sa.text("DELETE FROM matches WHERE id = :dupe"),
                    {"dupe": dupe},
                )
                total_matches_deleted += 1

        print(
            f"[{revision}] match dedup: groups={len(dupe_groups)} "
            f"matches_deleted={total_matches_deleted} "
            f"predictions_repointed={total_pred_repointed} "
            f"predictions_deleted={total_pred_deleted} "
            f"score_corrections_repointed={total_corr_repointed}"
        )

    # ------------------------------------------------------------------
    # 4) Add the unique constraint we should have started with
    # ------------------------------------------------------------------
    existing_uc = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = 'matches' AND c.conname = 'uq_match_fixture'"
        )
    ).fetchone()
    if existing_uc:
        print(f"[{revision}] uq_match_fixture already present — skipping create")
    else:
        op.create_unique_constraint(
            "uq_match_fixture",
            "matches",
            ["home_team_id", "away_team_id", "league_id", "match_date"],
        )
        print(f"[{revision}] added UNIQUE constraint uq_match_fixture")


def downgrade() -> None:
    # Match dedup is not cleanly reversible. To roll back the unique constraint
    # alone (e.g. emergency hotfix), do it manually:
    #   ALTER TABLE matches DROP CONSTRAINT uq_match_fixture;
    pass
