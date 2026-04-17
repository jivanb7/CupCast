"""
scripts/fetch_xg_data.py
=========================
Fetch match-level xG data from Understat for top 5 European leagues.
Saves to ml/data/raw/xg/understat_xg.csv

Understat covers: EPL, La Liga, Bundesliga, Serie A, Ligue 1
Seasons available: 2014 onwards

Run: cd cupcast && conda run -n ml python scripts/fetch_xg_data.py
"""

import logging
import time
from pathlib import Path

import pandas as pd
from understatapi import UnderstatClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
XG_DIR = PROJECT_ROOT / "ml" / "data" / "raw" / "xg"
XG_DIR.mkdir(parents=True, exist_ok=True)

# Understat league names → our league codes
UNDERSTAT_LEAGUES = {
    "EPL": "E0",
    "La_liga": "SP1",
    "Bundesliga": "D1",
    "Serie_A": "I1",
    "Ligue_1": "F1",
}

# Seasons to fetch (Understat uses calendar year of season start)
SEASONS = list(range(2014, 2026))  # 2014-15 through 2025-26


def fetch_all_xg() -> pd.DataFrame:
    """Fetch xG data for all leagues and seasons."""
    client = UnderstatClient()
    all_rows = []

    for understat_name, league_code in UNDERSTAT_LEAGUES.items():
        for season in SEASONS:
            try:
                results = client.league(league=understat_name).get_match_data(season=str(season))
                if not results:
                    logger.info("  %s %d: no data", understat_name, season)
                    continue

                for match in results:
                    if not match.get("isResult"):
                        continue  # Skip unplayed matches

                    home_team = match.get("h", {}).get("title", "")
                    away_team = match.get("a", {}).get("title", "")
                    xg_home = float(match.get("xG", {}).get("h", 0))
                    xg_away = float(match.get("xG", {}).get("a", 0))
                    goals_home = int(match.get("goals", {}).get("h", 0))
                    goals_away = int(match.get("goals", {}).get("a", 0))
                    match_date = match.get("datetime", "")[:10]  # "YYYY-MM-DD"

                    all_rows.append({
                        "match_date": match_date,
                        "home_team": home_team,
                        "away_team": away_team,
                        "league_code": league_code,
                        "season": season,
                        "xg_home": xg_home,
                        "xg_away": xg_away,
                        "goals_home": goals_home,
                        "goals_away": goals_away,
                    })

                logger.info("  %s %d: %d matches", understat_name, season, len(results))
            except Exception as e:
                logger.warning("  %s %d: failed — %s", understat_name, season, e)

            # Respectful delay between requests
            time.sleep(1.5)

    df = pd.DataFrame(all_rows)
    logger.info("Total xG records: %d", len(df))
    return df


def main():
    logger.info("Fetching xG data from Understat...")
    df = fetch_all_xg()

    if len(df) > 0:
        out_path = XG_DIR / "understat_xg.csv"
        df.to_csv(out_path, index=False)
        logger.info("Saved %d records to %s", len(df), out_path)

        # Summary
        print(f"\n{'League':<15} {'Matches':>8} {'Seasons':>8}")
        print("-" * 35)
        for code in UNDERSTAT_LEAGUES.values():
            subset = df[df["league_code"] == code]
            seasons = subset["season"].nunique()
            print(f"{code:<15} {len(subset):>8} {seasons:>8}")
    else:
        logger.error("No xG data fetched!")


if __name__ == "__main__":
    main()
