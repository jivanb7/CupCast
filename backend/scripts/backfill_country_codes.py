"""
backend/scripts/backfill_country_codes.py
==========================================
Idempotent backfill of teams.country_code for all 48 World Cup national teams.

Updates only rows where team_type='national' and canonical_name matches an
entry in NATIONAL_TEAM_COUNTRY_CODES. Safe to re-run — already-set codes
are overwritten with the same value (no harm done).

Usage:
    cd saas/backend
    conda run -n ml python scripts/backfill_country_codes.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402
from services.national_team_codes import NATIONAL_TEAM_COUNTRY_CODES  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    db = SessionLocal()
    try:
        # Pull all national teams once.
        rows = db.execute(
            text("SELECT id, canonical_name FROM teams WHERE team_type = 'national'")
        ).fetchall()
        db_nationals: dict[str, int] = {r[1]: r[0] for r in rows}

        updated = 0
        not_in_db: list[str] = []

        for canonical_name, code in NATIONAL_TEAM_COUNTRY_CODES.items():
            if canonical_name not in db_nationals:
                not_in_db.append(canonical_name)
                continue
            team_id = db_nationals[canonical_name]
            db.execute(
                text(
                    """
                    UPDATE teams
                    SET country_code = :code,
                        created_at   = created_at
                    WHERE id = :team_id
                      AND team_type = 'national'
                    """
                ),
                {"code": code, "team_id": team_id},
            )
            updated += 1

        db.commit()

        logger.info("Updated %d teams with country_code.", updated)

        if not_in_db:
            logger.warning(
                "%d team(s) in the mapping dict were NOT found in the DB: %s",
                len(not_in_db),
                ", ".join(not_in_db),
            )

        # Report any national team in the DB that has no country_code after backfill.
        missing_code = db.execute(
            text(
                "SELECT canonical_name FROM teams "
                "WHERE team_type = 'national' AND (country_code IS NULL OR country_code = '')"
                " ORDER BY canonical_name"
            )
        ).fetchall()
        if missing_code:
            logger.warning(
                "%d national team(s) still have no country_code (not in mapping dict): %s",
                len(missing_code),
                ", ".join(r[0] for r in missing_code),
            )
        else:
            logger.info("All national teams in the DB now have a country_code.")

    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
