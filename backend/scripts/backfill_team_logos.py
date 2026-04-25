"""
backend/scripts/backfill_team_logos.py
========================================
One-shot script to populate ``teams.logo_url`` for *club* teams using
API-Football's ``/teams?league=X&season=Y`` endpoint.

Why this exists
  The Dashboard "Featured Prediction" was rendering team initials
  (e.g. "DA" / "RM") instead of crests because ``teams.logo_url`` was never
  backfilled for clubs. National teams already render via flag-icons keyed
  off ``country_code`` and must NOT be touched here.

Multi-season coverage
  Many DB rows are *stale* — clubs that played in a tracked league a few
  seasons ago, then got promoted/relegated. The current API-Football season
  has no record of them, so a single-season backfill leaves them logo-less.
  This script walks several seasons per league (default 2022-2025), dedupes
  by API-Football team ID across seasons (keeping the most recent payload
  for each ID), and matches the union against the DB.

Scope
  - club teams only (``team_type = 'club'``)
  - all leagues in :data:`LEAGUE_API_FOOTBALL_IDS` (player_availability_service)
    plus MLS (api-football league_id = 253), which the existing service map
    omits because MLS live-scores go through ESPN.
  - ``worldcup`` is intentionally skipped (national teams).

Idempotency
  Only writes when ``logo_url IS NULL`` or differs from the new URL.
  Defensive WHERE clause also requires ``team_type = 'club'`` to make it
  impossible to accidentally stamp a logo onto a national team row.

Usage
    cd backend && conda run -n ml python scripts/backfill_team_logos.py
    cd backend && conda run -n ml python scripts/backfill_team_logos.py --seasons 2021,2022,2023,2024,2025
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import unicodedata
from pathlib import Path
from typing import Optional

import requests

# Make backend importable when run as `python scripts/backfill_team_logos.py`
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Load .env from saas/ root (one level above backend/) so API_FOOTBALL_KEYS
# is available even when invoked outside of the FastAPI lifespan.
try:
    from dotenv import load_dotenv

    load_dotenv(_BACKEND_DIR.parent / ".env")
except ImportError:
    pass

from sqlalchemy.orm import Session  # noqa: E402

from database import SessionLocal  # noqa: E402
from models.league import League  # noqa: E402
from models.team import Team, TeamNameAlias  # noqa: E402
from services.player_availability_service import LEAGUE_API_FOOTBALL_IDS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_team_logos")

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
INTER_CALL_SLEEP_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 20

# API-Football league IDs to backfill. Mirrors LEAGUE_API_FOOTBALL_IDS but adds
# MLS (253), which the live-score / odds path doesn't use because MLS goes
# through ESPN there. We still want crests for MLS clubs in the DB.
LEAGUES_TO_BACKFILL: dict[str, int] = {
    **LEAGUE_API_FOOTBALL_IDS,
    "mls": 253,
}

SKIP_LEAGUES = {
    "worldcup",         # national teams; handled by flag-icons
}

# Default seasons to walk per league. API-Football keys seasons by start year.
# 2022 → 2022-23, 2025 → 2025-26. Four seasons should cover virtually every
# stale club currently in the DB without burning the rate budget (11 leagues
# × 4 seasons = 44 calls, comfortably under the 100/day free-tier cap).
DEFAULT_SEASONS: list[int] = [2022, 2023, 2024, 2025]


def _current_season() -> int:
    """API-Football keys seasons by start year. July is the cutover.

    2025-26 → 2025, 2026-27 → 2026, etc.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1


def _get_api_keys() -> list[str]:
    raw = os.getenv("API_FOOTBALL_KEYS") or os.getenv("API_FOOTBALL_KEY") or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    return keys


def _fetch_teams_for_league(
    api_league_id: int, season: int, key: str
) -> Optional[list[dict]]:
    """Single GET to /teams?league=X&season=Y. Returns None on failure."""
    url = f"{API_FOOTBALL_BASE}/teams"
    headers = {"x-apisports-key": key}
    params = {"league": api_league_id, "season": season}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        logger.error("network error league=%d season=%d: %s", api_league_id, season, exc)
        return None

    if resp.status_code == 429:
        logger.error("rate limited (429) on league=%d — bail", api_league_id)
        return None
    if resp.status_code == 401 or resp.status_code == 403:
        logger.error("auth failure (HTTP %d) — check API_FOOTBALL_KEYS", resp.status_code)
        return None
    if resp.status_code != 200:
        logger.error(
            "HTTP %d league=%d season=%d body=%s",
            resp.status_code, api_league_id, season, resp.text[:200],
        )
        return None

    try:
        payload = resp.json()
    except ValueError as exc:
        logger.error("JSON decode error league=%d: %s", api_league_id, exc)
        return None

    return payload.get("response", []) or []


def _normalize(s: Optional[str]) -> str:
    """Casefold + strip diacritics for forgiving name comparison.

    Example: "Deportivo Alavés" → "deportivo alaves".
    """
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", s)
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return no_accents.strip().lower()


# Common suffixes/prefixes the API drops or adds vs our canonical names.
# Strip these from BOTH sides during fuzzy comparison.
_FILLER_TOKENS = {
    "fc", "cf", "afc", "sc", "ac", "ca", "ud", "sd", "cd",
    "city", "town", "united", "utd", "athletic", "club",
    "de", "le", "the", "f.c.", "c.f.",
}


def _tokens(name: str) -> set[str]:
    """Tokenized normalized name with filler words removed.

    Used as a last-resort fuzzy: if the meaningful tokens of the API name
    are a subset of a DB team's tokens (or vice versa), it's a match.
    """
    norm = _normalize(name).replace(".", " ").replace("-", " ")
    return {t for t in norm.split() if t and t not in _FILLER_TOKENS}


def _resolve_club_team(
    db: Session,
    api_name: str,
    db_league_id: int,
    club_index: list[Team],
) -> Optional[Team]:
    """Match an API-Football team name to a *club* row in our DB.

    Strategy (all club-only — never returns a national team):
      1. Exact normalized canonical_name match (handles case + accents)
      2. Normalized alias match
      3. Normalized short_name match
      4. League-scoped startswith / substring
      5. Token-set match: API tokens equal DB tokens, or one contains the
         other and the smaller side has >= 2 distinguishing tokens
         (prevents 1-token false positives like "Reading" → "Slavia").
         Prefer same-league candidates first.
    """
    if not api_name:
        return None

    api_norm = _normalize(api_name)
    api_tokens = _tokens(api_name)

    # 1) exact normalized canonical
    for t in club_index:
        if _normalize(t.canonical_name) == api_norm:
            return t

    # 2) alias lookup (case- and accent-insensitive via Python loop — alias
    #    table is small enough that a full scan is fine for a one-shot)
    aliases = (
        db.query(TeamNameAlias)
        .join(Team, Team.id == TeamNameAlias.team_id)
        .filter(Team.team_type == "club")
        .all()
    )
    for a in aliases:
        if _normalize(a.alias) == api_norm:
            return db.query(Team).filter(Team.id == a.team_id).first()

    # 3) normalized short_name
    for t in club_index:
        if t.short_name and _normalize(t.short_name) == api_norm:
            return t

    # 4) startswith / substring on canonical (league-scoped first, then global)
    def _scan_substring(pool: list[Team]) -> Optional[Team]:
        for t in pool:
            cn = _normalize(t.canonical_name)
            if cn.startswith(api_norm + " ") or cn.endswith(" " + api_norm):
                return t
        for t in pool:
            cn = _normalize(t.canonical_name)
            if api_norm and api_norm in cn:
                return t
        return None

    same_league = [t for t in club_index if t.league_id == db_league_id]
    hit = _scan_substring(same_league)
    if hit:
        return hit

    # 5) token-set match — tighten to avoid 1-token collisions
    if len(api_tokens) >= 1:
        # Require >=2 shared meaningful tokens unless API name is a single
        # distinctive token (>= 5 chars) that matches a DB token exactly.
        def _token_match(pool: list[Team]) -> Optional[Team]:
            best: Optional[tuple[int, Team]] = None
            for t in pool:
                db_tokens = _tokens(t.canonical_name)
                if not db_tokens:
                    continue
                shared = api_tokens & db_tokens
                if not shared:
                    continue
                # subset either way → strong candidate
                subset = api_tokens.issubset(db_tokens) or db_tokens.issubset(api_tokens)
                # accept if (a) >=2 shared tokens, or (b) one shared token
                # which is >=5 chars AND it's a subset relationship.
                if len(shared) >= 2 or (
                    subset and any(len(tok) >= 5 for tok in shared)
                ):
                    score = len(shared) * 10 - abs(len(api_tokens) - len(db_tokens))
                    if best is None or score > best[0]:
                        best = (score, t)
            return best[1] if best else None

        hit = _token_match(same_league)
        if hit:
            return hit
        # global fallback (e.g. UCL: domestic-league teams)
        hit = _token_match(club_index)
        if hit:
            return hit

    # global substring as a last resort (UCL etc.)
    return _scan_substring(club_index)


def _parse_seasons_arg(value: str) -> list[int]:
    """Parse a comma-separated string of season years into a sorted unique list.

    Raises argparse.ArgumentTypeError on malformed input so the CLI prints
    a usage message instead of a stack trace.
    """
    out: list[int] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        try:
            year = int(token)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"invalid season {token!r}: must be an integer year"
            ) from exc
        if year < 2000 or year > 2100:
            raise argparse.ArgumentTypeError(
                f"season {year} out of plausible range 2000-2100"
            )
        out.append(year)
    if not out:
        raise argparse.ArgumentTypeError("--seasons must list at least one year")
    # Sort ascending, dedupe, then keep ascending order so the per-season
    # loop sees older seasons first and the most-recent overwrites in the dedup.
    return sorted(set(out))


def backfill_logos(seasons: Optional[list[int]] = None) -> int:
    """Run the backfill across multiple seasons. Returns 0 on success.

    Parameters
    ----------
    seasons:
        Iterable of API-Football season start-years to walk per league. The
        list is sorted ascending so that newer-season payloads overwrite
        older ones in the per-league dedup dict (we keep the most recent
        ``logo`` URL per ``team.id``).
    """
    keys = _get_api_keys()
    if not keys:
        logger.error("API_FOOTBALL_KEYS not set in env — aborting")
        return 2
    key = keys[0]

    seasons_list = sorted(set(seasons)) if seasons else list(DEFAULT_SEASONS)
    logger.info(
        "using seasons=%s, %d API key(s) loaded",
        seasons_list, len(keys),
    )

    db: Session = SessionLocal()
    try:
        # snapshot: how many national rows have a logo_url right now? must be unchanged.
        national_logo_before = (
            db.query(Team)
            .filter(Team.team_type == "national")
            .filter(Team.logo_url.isnot(None))
            .count()
        )
        clubs_with_before = (
            db.query(Team)
            .filter(Team.team_type == "club")
            .filter(Team.logo_url.isnot(None))
            .count()
        )

        per_league: list[dict] = []
        total_updated = 0
        total_unchanged = 0
        unmatched_global: list[tuple[str, str]] = []  # (league_code, api_name)

        # One-shot global club index — resolver does its own filtering.
        club_index: list[Team] = (
            db.query(Team).filter(Team.team_type == "club").all()
        )

        for league_code, api_league_id in LEAGUES_TO_BACKFILL.items():
            if league_code in SKIP_LEAGUES:
                logger.info("skip league=%s (national teams handled via flag-icons)", league_code)
                continue

            league_obj = db.query(League).filter(League.code == league_code).first()
            if league_obj is None:
                logger.warning("league %s not in DB — skipping", league_code)
                continue

            # Per-league dedup map: api_team_id → {name, logo, country, season_seen}.
            # We iterate seasons ascending so the most-recent season's payload
            # naturally overwrites older ones for any duplicated team id.
            deduped: dict[int, dict] = {}
            per_season_counts: list[dict] = []
            league_hard_fail = False

            for season in seasons_list:
                logger.info(
                    "fetching league=%s (api_id=%d, season=%d)",
                    league_code, api_league_id, season,
                )
                teams_payload = _fetch_teams_for_league(api_league_id, season, key)
                # Always pace between calls — even on failure — to stay polite.
                time.sleep(INTER_CALL_SLEEP_SECONDS)

                if teams_payload is None:
                    # Soft-fail per (league, season): log and move on. A bad
                    # season parameter for one league should not abort the run.
                    logger.warning(
                        "league=%s season=%d: fetch failed, skipping this season",
                        league_code, season,
                    )
                    league_hard_fail = True
                    per_season_counts.append({
                        "season": season,
                        "api_returned": 0,
                        "new_ids": 0,
                        "error": True,
                    })
                    continue

                new_ids = 0
                for entry in teams_payload:
                    team_blob = entry.get("team", {}) or {}
                    api_id = team_blob.get("id")
                    api_name = (team_blob.get("name") or "").strip()
                    logo_url = (team_blob.get("logo") or "").strip()
                    country = (team_blob.get("country") or "").strip()
                    if api_id is None or not api_name or not logo_url:
                        continue
                    if api_id not in deduped:
                        new_ids += 1
                    deduped[int(api_id)] = {
                        "name": api_name,
                        "logo": logo_url,
                        "country": country,
                        "season_seen": season,
                    }

                logger.info(
                    "league=%s season=%d: api_returned=%d new_ids=%d",
                    league_code, season, len(teams_payload), new_ids,
                )
                per_season_counts.append({
                    "season": season,
                    "api_returned": len(teams_payload),
                    "new_ids": new_ids,
                    "error": False,
                })

            # Now run the existing match-and-update logic over the deduped set.
            updated = 0
            unchanged = 0
            unmatched: list[str] = []
            updated_examples: list[tuple[str, str, int]] = []  # (db_name, api_name, season)

            for api_id, info in deduped.items():
                api_name = info["name"]
                logo_url = info["logo"]

                db_team = _resolve_club_team(db, api_name, league_obj.id, club_index)
                if db_team is None:
                    unmatched.append(api_name)
                    continue

                # defensive: never write to a national row
                if db_team.team_type != "club":
                    logger.error(
                        "refusing to write logo for non-club team id=%s name=%s",
                        db_team.id, db_team.canonical_name,
                    )
                    continue

                if db_team.logo_url == logo_url:
                    unchanged += 1
                    continue

                # Track stale-team rescues: a row whose logo was previously
                # NULL is one we wouldn't have caught with single-season fetch.
                was_null = db_team.logo_url is None
                db_team.logo_url = logo_url
                updated += 1
                if was_null:
                    updated_examples.append(
                        (db_team.canonical_name, api_name, info["season_seen"])
                    )

            db.commit()

            logger.info(
                "league=%s: deduped=%d updated=%d unchanged=%d unmatched=%d",
                league_code, len(deduped), updated, unchanged, len(unmatched),
            )
            for name in unmatched:
                logger.warning("  unmatched %s: %r", league_code, name)
                unmatched_global.append((league_code, name))

            per_league.append({
                "league": league_code,
                "deduped": len(deduped),
                "updated": updated,
                "unchanged": unchanged,
                "unmatched": len(unmatched),
                "per_season": per_season_counts,
                "updated_examples": updated_examples,
                "had_failure": league_hard_fail,
            })
            total_updated += updated
            total_unchanged += unchanged

        # post-run sanity: national rows must be untouched
        national_logo_after = (
            db.query(Team)
            .filter(Team.team_type == "national")
            .filter(Team.logo_url.isnot(None))
            .count()
        )

        clubs_with = (
            db.query(Team)
            .filter(Team.team_type == "club")
            .filter(Team.logo_url.isnot(None))
            .count()
        )
        clubs_without = (
            db.query(Team)
            .filter(Team.team_type == "club")
            .filter(Team.logo_url.is_(None))
            .count()
        )

        print()
        print("=" * 72)
        print("BACKFILL SUMMARY (multi-season)")
        print("=" * 72)
        print(f"seasons walked: {seasons_list}")
        print()
        # League-level summary
        print(f"  {'league':<16} {'deduped':>8} {'updated':>8} "
              f"{'unchanged':>10} {'unmatched':>10}")
        print("  " + "-" * 56)
        for row in per_league:
            print(
                f"  {row['league']:<16} {row['deduped']:>8} "
                f"{row['updated']:>8} {row['unchanged']:>10} {row['unmatched']:>10}"
            )
        print()
        # Per-(league, season) breakdown
        print("Per-(league, season) breakdown (api_returned / new_ids):")
        for row in per_league:
            parts = []
            for ps in row["per_season"]:
                tag = "ERR" if ps["error"] else f"{ps['api_returned']}/{ps['new_ids']}"
                parts.append(f"{ps['season']}={tag}")
            print(f"  {row['league']:<16} {'  '.join(parts)}")
        print()
        print("-" * 72)
        print(f"clubs with logo_url:     {clubs_with}  (was {clubs_with_before}, "
              f"delta +{clubs_with - clubs_with_before})")
        print(f"clubs without logo_url:  {clubs_without}")
        print(f"total club rows updated: {total_updated}")
        print(f"total club rows unchanged: {total_unchanged}")
        print(
            f"national w/ logo_url:    {national_logo_after} "
            f"(was {national_logo_before} — must be equal)"
        )

        # Highlight stale-team rescues — rows that were NULL before the run
        # and now have a logo sourced from an older season.
        rescues = [
            (row["league"], db_name, api_name, season)
            for row in per_league
            for (db_name, api_name, season) in row["updated_examples"]
        ]
        if rescues:
            print()
            print(f"Stale-team rescues ({len(rescues)} rows newly populated):")
            for lg, db_name, api_name, season in rescues:
                tag = "" if db_name == api_name else f"  (api: {api_name!r})"
                print(f"  [{lg}] {db_name}  ← season {season}{tag}")

        if unmatched_global:
            print()
            print(f"Unmatched ({len(unmatched_global)}):")
            for lg, name in unmatched_global:
                print(f"  [{lg}] {name}")

        if national_logo_after != national_logo_before:
            logger.error("INVARIANT BROKEN: national logo_url count changed")
            return 4
        return 0
    finally:
        db.close()


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backfill teams.logo_url across multiple API-Football seasons.",
    )
    p.add_argument(
        "--seasons",
        type=_parse_seasons_arg,
        default=list(DEFAULT_SEASONS),
        help=(
            "Comma-separated list of season start-years to walk per league. "
            f"Default: {','.join(str(s) for s in DEFAULT_SEASONS)}"
        ),
    )
    return p


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()
    sys.exit(backfill_logos(seasons=args.seasons))
