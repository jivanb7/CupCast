"""
scripts/backfill_ucl.py
========================
One-time script to pull historical UCL match data from API-Football.
Saves raw JSON responses and a cleaned CSV to ml/data/raw/ucl/.

Run: cd cupcast && conda run -n ml python scripts/backfill_ucl.py

API endpoint: GET https://v3.football.api-sports.io/fixtures?league=2&season={year}
  - league=2 is UEFA Champions League in API-Football
  - season is the start year (e.g., 2024 = 2024-25 UCL season)

Output:
  ml/data/raw/ucl/api_response_{season}.json  — raw API response per season
  ml/data/raw/ucl/ucl_matches.csv             — all completed matches, standard format

Columns in ucl_matches.csv:
  match_date, home_team, away_team, home_goals, away_goals, result,
  ht_home_goals, ht_away_goals, league_code, season, round
"""

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "ml"))

from services.api_key_rotator import init_rotator, get_api_football_key, mark_key_exhausted
from src.team_name_mapping import resolve_team_name

# ── Constants ─────────────────────────────────────────────────────────────────
UCL_LEAGUE_ID = 2
# Seasons to backfill: 2015-16 through 2024-25 (start years 2015–2024)
SEASONS = list(range(2015, 2025))
API_BASE_URL = "https://v3.football.api-sports.io"

OUTPUT_DIR = PROJECT_ROOT / "ml" / "data" / "raw" / "ucl"
OUTPUT_CSV = OUTPUT_DIR / "ucl_matches.csv"


# ── Key rotator init ──────────────────────────────────────────────────────────
def _load_api_keys() -> list[str]:
    """Load API-Football keys from .env or environment."""
    # Try loading from .env file directly
    env_path = PROJECT_ROOT / "backend" / ".env"
    keys_raw = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("API_FOOTBALL_KEYS="):
                keys_raw = line.split("=", 1)[1].strip()
                break

    # Fall back to environment variable
    if not keys_raw:
        keys_raw = os.environ.get("API_FOOTBALL_KEYS", "")

    keys = [k.strip() for k in keys_raw.split(",") if k.strip()]
    if not keys:
        print("ERROR: No API_FOOTBALL_KEYS found. Set them in backend/.env")
        sys.exit(1)

    return keys


# ── API call helpers ──────────────────────────────────────────────────────────
def _fetch_season(season: int) -> dict | None:
    """Fetch all fixtures for a UCL season. Returns the raw API response dict."""
    url = f"{API_BASE_URL}/fixtures"
    params = {"league": UCL_LEAGUE_ID, "season": season}

    key = get_api_football_key()
    headers = {"x-apisports-key": key}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
    except requests.RequestException as e:
        print(f"  [season {season}] Network error: {e}")
        return None

    if resp.status_code == 429:
        print(f"  [season {season}] 429 — key exhausted, marking and retrying with next key")
        mark_key_exhausted(key)
        # One retry with the next key
        key2 = get_api_football_key()
        headers2 = {"x-apisports-key": key2}
        try:
            resp = requests.get(url, headers=headers2, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"  [season {season}] Retry network error: {e}")
            return None
        if resp.status_code == 429:
            mark_key_exhausted(key2)
            print(f"  [season {season}] Second key also 429 — skipping this season")
            return None

    if resp.status_code != 200:
        print(f"  [season {season}] HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    data = resp.json()
    print(f"  [season {season}] API response: {data.get('results', '?')} fixtures returned")
    return data


# ── Fixture parsing ───────────────────────────────────────────────────────────
def _parse_fixture(fixture: dict, season: int) -> dict | None:
    """
    Parse a single API-Football fixture dict into our standard row format.
    Returns None if the match is not completed (status != "FT").
    """
    status_short = fixture.get("fixture", {}).get("status", {}).get("short", "")
    if status_short != "FT":
        return None  # Not a completed match — skip

    match_date_raw = fixture.get("fixture", {}).get("date", "")
    match_date = match_date_raw[:10] if match_date_raw else None  # "YYYY-MM-DD"

    home_name_raw = fixture.get("teams", {}).get("home", {}).get("name", "")
    away_name_raw = fixture.get("teams", {}).get("away", {}).get("name", "")

    home_goals = fixture.get("goals", {}).get("home")
    away_goals = fixture.get("goals", {}).get("away")

    # Halftime scores
    ht = fixture.get("score", {}).get("halftime", {})
    ht_home = ht.get("home")
    ht_away = ht.get("away")

    # Round (e.g. "Group A - 1", "Quarter-finals", "Final")
    round_name = fixture.get("league", {}).get("round", "")

    # Resolve team names to canonical form
    home_team = resolve_team_name(home_name_raw, source="api_football_ucl")
    away_team = resolve_team_name(away_name_raw, source="api_football_ucl")

    # Compute result
    if home_goals is None or away_goals is None:
        return None  # Goals not recorded — treat as incomplete

    if home_goals > away_goals:
        result = "H"
    elif away_goals > home_goals:
        result = "A"
    else:
        result = "D"

    return {
        "match_date": match_date,
        "home_team": home_team,
        "away_team": away_team,
        "home_goals": int(home_goals),
        "away_goals": int(away_goals),
        "result": result,
        "ht_home_goals": int(ht_home) if ht_home is not None else None,
        "ht_away_goals": int(ht_away) if ht_away is not None else None,
        "league_code": "UCL",
        "season": season,
        "round": round_name,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Initialize rotator
    keys = _load_api_keys()
    init_rotator(keys)
    print(f"Initialized API key rotator with {len(keys)} keys")

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {OUTPUT_DIR}")

    all_rows: list[dict] = []
    total_fixtures = 0
    total_completed = 0

    for season in SEASONS:
        print(f"\nFetching UCL season {season}-{season + 1}...")
        data = _fetch_season(season)

        if data is None:
            print(f"  [season {season}] No data returned — skipping")
            # Still save an empty response file so we know we tried
            raw_path = OUTPUT_DIR / f"api_response_{season}.json"
            raw_path.write_text(json.dumps({"season": season, "error": "no_data"}, indent=2))
            # Rate limit delay before next call
            time.sleep(1)
            continue

        # Save raw API response for debugging / re-processing
        raw_path = OUTPUT_DIR / f"api_response_{season}.json"
        raw_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"  Saved raw response: {raw_path.name}")

        fixtures = data.get("response", [])
        season_fixtures = len(fixtures)
        total_fixtures += season_fixtures

        season_rows = []
        for fixture in fixtures:
            row = _parse_fixture(fixture, season)
            if row is not None:
                season_rows.append(row)

        total_completed += len(season_rows)
        all_rows.extend(season_rows)
        print(f"  {season_fixtures} fixtures total — {len(season_rows)} completed (FT)")

        # Be polite to the API — 1 second between calls
        time.sleep(1)

    # Build DataFrame and save CSV
    print(f"\nTotal: {total_fixtures} fixtures across {len(SEASONS)} seasons")
    print(f"Completed matches (FT): {total_completed}")

    if not all_rows:
        print("WARNING: No completed matches found — CSV not written")
        return

    df = pd.DataFrame(all_rows, columns=[
        "match_date", "home_team", "away_team",
        "home_goals", "away_goals", "result",
        "ht_home_goals", "ht_away_goals",
        "league_code", "season", "round",
    ])

    # Sort by date ascending
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    df = df.sort_values("match_date").reset_index(drop=True)

    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved {len(df)} rows to {OUTPUT_CSV}")

    # Print a sample and basic stats
    print(f"\nSeason distribution:")
    print(df.groupby("season").size().to_string())

    print(f"\nResult distribution:")
    print(df["result"].value_counts().to_string())

    # Report any unmapped team names (teams that passed through unchanged with a warning)
    # These appear as raw names not found in TEAM_NAME_MAP
    from src.team_name_mapping import validate_mapping_coverage
    all_teams = list(df["home_team"].unique()) + list(df["away_team"].unique())
    unresolved = validate_mapping_coverage(all_teams, source="api_football_ucl")
    if unresolved:
        print(f"\nWARNING: {len(unresolved)} team name(s) not in TEAM_NAME_MAP:")
        for name in sorted(set(unresolved)):
            print(f"  - '{name}'")
        print("Add these to ml/src/team_name_mapping.py before running the full pipeline.")
    else:
        print("\nAll team names resolved successfully.")


if __name__ == "__main__":
    main()
