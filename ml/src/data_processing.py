"""
ml/src/data_processing.py
==========================
Read raw CSVs, clean, standardize, and write unified parquet files.

Input:  data/raw/ (CSV files from data_ingestion.py)
Output: data/processed/
  - club_matches.parquet      One row per club league match, all leagues
  - intl_matches.parquet      One row per international match
  - fifa_rankings.parquet     One row per team per ranking date
  - fixtures.parquet          Upcoming scheduled matches (no result yet)
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ml.src.config import (
    CLUB_LEAGUES,
    LEAGUE_SEASONS,
    PROCESSED_DIR,
    RAW_DIR,
    RESULT_TO_INT,
)
from ml.src.team_name_mapping import resolve_team_name, validate_mapping_coverage

logger = logging.getLogger(__name__)

# Canonical column name mapping for football-data.co.uk CSVs
FDUK_COLUMN_MAP = {
    "Div": "league_code",
    "\ufeffDiv": "league_code",  # BOM variant
    "Date": "match_date",
    "HomeTeam": "home_team",
    "AwayTeam": "away_team",
    "FTHG": "home_goals",
    "FTAG": "away_goals",
    "FTR": "result",
    "HTHG": "ht_home_goals",
    "HTAG": "ht_away_goals",
    "HTR": "ht_result",
    "HS": "home_shots",
    "AS": "away_shots",
    "HST": "home_shots_on_target",
    "AST": "away_shots_on_target",
    "HC": "home_corners",
    "AC": "away_corners",
    "HF": "home_fouls",
    "AF": "away_fouls",
    "HY": "home_yellow_cards",
    "AY": "away_yellow_cards",
    "HR": "home_red_cards",
    "AR": "away_red_cards",
    "B365H": "odds_home",
    "B365D": "odds_draw",
    "B365A": "odds_away",
}

REQUIRED_COLUMNS = [
    "match_date", "home_team", "away_team",
    "home_goals", "away_goals", "result",
]

OPTIONAL_STAT_COLUMNS = [
    "home_shots", "away_shots",
    "home_shots_on_target", "away_shots_on_target",
    "home_corners", "away_corners",
    "home_fouls", "away_fouls",
    "home_yellow_cards", "away_yellow_cards",
    "home_red_cards", "away_red_cards",
]


def _parse_date_column(series: pd.Series) -> pd.Series:
    """Parse dates from football-data.co.uk which uses dd/mm/yy or dd/mm/yyyy."""
    # Try dd/mm/yyyy first, then dd/mm/yy
    parsed = pd.to_datetime(series, format="%d/%m/%Y", errors="coerce")
    mask_na = parsed.isna() & series.notna()
    if mask_na.any():
        parsed_2 = pd.to_datetime(series[mask_na], format="%d/%m/%y", errors="coerce")
        parsed.loc[mask_na] = parsed_2
    # Final fallback: let pandas infer
    still_na = parsed.isna() & series.notna()
    if still_na.any():
        parsed_3 = pd.to_datetime(series[still_na], dayfirst=True, errors="coerce")
        parsed.loc[still_na] = parsed_3
    return parsed


def _season_label(season_code: str) -> str:
    """Convert season code like '2526' to '2025-26'."""
    if len(season_code) != 4:
        return season_code
    start = int("20" + season_code[:2]) if int(season_code[:2]) < 50 else int("19" + season_code[:2])
    end_short = season_code[2:]
    return f"{start}-{end_short}"


def load_single_league_csv(file_path: Path, league_code: str, season: str) -> pd.DataFrame:
    """Load a single football-data.co.uk CSV file, rename columns, resolve team names."""
    try:
        df = pd.read_csv(file_path, encoding="latin-1")
    except Exception as e:
        logger.error("Failed to read %s: %s", file_path, e)
        return pd.DataFrame()

    if df.empty:
        logger.warning("Empty CSV file: %s", file_path)
        return pd.DataFrame()

    # Drop completely empty rows
    df = df.dropna(how="all")

    if df.empty:
        logger.warning("All rows empty after cleanup: %s", file_path)
        return pd.DataFrame()

    # Strip BOM and whitespace from column names
    df.columns = [c.strip().lstrip("\ufeff").lstrip("ï»¿") for c in df.columns]

    # Rename columns
    df = df.rename(columns=FDUK_COLUMN_MAP, errors="ignore")

    # Overwrite league_code from argument (more reliable than CSV Div column)
    df["league_code"] = league_code
    df["season"] = _season_label(season)

    # Parse dates
    if "match_date" in df.columns:
        df["match_date"] = _parse_date_column(df["match_date"])

    # Resolve team names
    if "home_team" in df.columns:
        df["home_team"] = df["home_team"].apply(
            lambda x: resolve_team_name(str(x), source="football_data_uk") if pd.notna(x) else x
        )
    if "away_team" in df.columns:
        df["away_team"] = df["away_team"].apply(
            lambda x: resolve_team_name(str(x), source="football_data_uk") if pd.notna(x) else x
        )

    # Cast numeric stat columns to nullable Int64
    int_cols = ["home_goals", "away_goals", "ht_home_goals", "ht_away_goals"] + OPTIONAL_STAT_COLUMNS
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    # Cast odds to float
    for col in ["odds_home", "odds_draw", "odds_away"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Add missing optional stat columns as NA
    for col in OPTIONAL_STAT_COLUMNS + ["odds_home", "odds_draw", "odds_away"]:
        if col not in df.columns:
            df[col] = pd.NA

    # Filter to valid result rows (H/D/A or null for unplayed)
    if "result" in df.columns:
        df = df[df["result"].isin(["H", "D", "A"]) | df["result"].isna()]

    # Keep only needed columns
    keep_cols = [
        "league_code", "season", "match_date", "home_team", "away_team",
        "home_goals", "away_goals", "result",
        "ht_home_goals", "ht_away_goals", "ht_result",
    ] + OPTIONAL_STAT_COLUMNS + ["odds_home", "odds_draw", "odds_away"]
    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols]

    return df


def process_club_matches() -> pd.DataFrame:
    """Load all league CSVs, concatenate, and write to club_matches.parquet."""
    all_dfs = []
    for league_code, seasons in LEAGUE_SEASONS.items():
        league_dir = CLUB_LEAGUES[league_code][0]
        for season in seasons:
            fpath = RAW_DIR / league_dir / f"{season}.csv"
            if fpath.exists():
                df = load_single_league_csv(fpath, league_code, season)
                if len(df) > 0:
                    all_dfs.append(df)

    if not all_dfs:
        logger.error("No club match data found!")
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    rows_before = len(combined)

    # Drop rows missing essential columns
    combined = combined.dropna(subset=["match_date", "home_team", "away_team", "result"])
    rows_after_na = len(combined)
    if rows_before != rows_after_na:
        logger.info(
            "Dropped %d rows with missing essential fields (date/team/result)",
            rows_before - rows_after_na,
        )

    # Deduplicate (same match_date + home + away)
    combined = combined.drop_duplicates(
        subset=["match_date", "home_team", "away_team"],
        keep="first",
    )
    rows_after_dedup = len(combined)
    if rows_after_na != rows_after_dedup:
        logger.info("Dropped %d duplicate matches", rows_after_na - rows_after_dedup)

    # Add result encoded
    combined["result_encoded"] = combined["result"].map(RESULT_TO_INT)

    # Sort by date
    combined = combined.sort_values("match_date").reset_index(drop=True)

    # Validate team names
    all_teams = pd.concat([combined["home_team"], combined["away_team"]]).unique().tolist()
    unmapped = validate_mapping_coverage(all_teams, source="club_matches")
    if unmapped:
        unmapped_path = PROCESSED_DIR / "unmapped_team_names.txt"
        unmapped_path.write_text("\n".join(sorted(unmapped)))
        logger.warning("Wrote %d unmapped team names to %s", len(unmapped), unmapped_path)

    # Write parquet
    out_path = PROCESSED_DIR / "club_matches.parquet"
    combined.to_parquet(out_path, index=False, engine="pyarrow")
    logger.info(
        "Club matches: %d rows, %d leagues, date range %s to %s -> %s",
        len(combined), combined["league_code"].nunique(),
        combined["match_date"].min().date(), combined["match_date"].max().date(),
        out_path,
    )
    return combined


def process_international_matches() -> pd.DataFrame:
    """Load Kaggle international results CSV, standardize, write to intl_matches.parquet."""
    intl_path = RAW_DIR / "international" / "results.csv"
    if not intl_path.exists():
        logger.error("International results not found at %s", intl_path)
        return pd.DataFrame()

    df = pd.read_csv(intl_path)
    logger.info("Raw international matches: %d rows", len(df))

    # Standardize columns
    df = df.rename(columns={
        "date": "match_date",
        "home_team": "home_team",
        "away_team": "away_team",
        "home_score": "home_goals",
        "away_score": "away_goals",
    })

    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    rows_before = len(df)
    df = df.dropna(subset=["match_date", "home_goals", "away_goals"])
    if rows_before != len(df):
        logger.info(
            "Dropped %d international rows with missing date/goals",
            rows_before - len(df),
        )

    # Resolve team names
    df["home_team"] = df["home_team"].apply(
        lambda x: resolve_team_name(str(x), source="kaggle_intl") if pd.notna(x) else x
    )
    df["away_team"] = df["away_team"].apply(
        lambda x: resolve_team_name(str(x), source="kaggle_intl") if pd.notna(x) else x
    )

    # Derive result
    df["home_goals"] = df["home_goals"].astype(int)
    df["away_goals"] = df["away_goals"].astype(int)
    conditions = [
        df["home_goals"] > df["away_goals"],
        df["home_goals"] == df["away_goals"],
        df["home_goals"] < df["away_goals"],
    ]
    df["result"] = np.select(conditions, ["H", "D", "A"], default="D")
    df["result_encoded"] = df["result"].map(RESULT_TO_INT)

    # Tournament importance mapping
    tournament_map = {
        "FIFA World Cup": "world_cup",
        "FIFA World Cup qualification": "qualifier",
        "Friendly": "friendly",
        "UEFA Euro": "continental",
        "UEFA Euro qualification": "qualifier",
        "Copa America": "continental",
        "Copa Am\u00e9rica": "continental",
        "African Cup of Nations": "continental",
        "AFC Asian Cup": "continental",
        "AFC Asian Cup qualification": "qualifier",
        "CONCACAF Gold Cup": "continental",
        "UEFA Nations League": "competitive",
        "Confederations Cup": "competitive",
    }
    df["tournament_type"] = df["tournament"].map(tournament_map).fillna("competitive")

    # Neutral venue
    if "neutral" in df.columns:
        df["is_neutral_venue"] = df["neutral"].fillna(False).astype(bool).astype(int)
    else:
        df["is_neutral_venue"] = 0

    # Keep needed columns
    keep_cols = [
        "match_date", "home_team", "away_team", "home_goals", "away_goals",
        "result", "result_encoded", "tournament", "tournament_type",
        "city", "country", "is_neutral_venue",
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols].sort_values("match_date").reset_index(drop=True)

    out_path = PROCESSED_DIR / "intl_matches.parquet"
    df.to_parquet(out_path, index=False, engine="pyarrow")
    logger.info(
        "International matches: %d rows, date range %s to %s -> %s",
        len(df), df["match_date"].min().date(), df["match_date"].max().date(),
        out_path,
    )
    return df


def process_fifa_rankings() -> pd.DataFrame:
    """Load FIFA rankings CSV, resolve team names, write to fifa_rankings.parquet."""
    rk_path = RAW_DIR / "fifa_rankings" / "rankings.csv"
    if not rk_path.exists():
        logger.error("FIFA rankings not found at %s", rk_path)
        return pd.DataFrame()

    df = pd.read_csv(rk_path)
    logger.info("Raw FIFA rankings: %d rows", len(df))

    # Standardize columns
    df = df.rename(columns={
        "country_full": "team",
        "rank_date": "rank_date",
        "rank": "fifa_rank",
        "total_points": "total_points",
        "confederation": "confederation",
    })

    df["rank_date"] = pd.to_datetime(df["rank_date"], errors="coerce")
    rows_before = len(df)
    df = df.dropna(subset=["rank_date", "fifa_rank"])
    if rows_before != len(df):
        logger.info("Dropped %d FIFA ranking rows with missing date/rank", rows_before - len(df))
    df["fifa_rank"] = df["fifa_rank"].astype(int)

    # Resolve team names
    df["team"] = df["team"].apply(
        lambda x: resolve_team_name(str(x), source="fifa_rankings") if pd.notna(x) else x
    )

    # Keep needed columns
    keep_cols = ["team", "rank_date", "fifa_rank", "total_points", "confederation"]
    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols].sort_values(["rank_date", "fifa_rank"]).reset_index(drop=True)

    out_path = PROCESSED_DIR / "fifa_rankings.parquet"
    df.to_parquet(out_path, index=False, engine="pyarrow")
    logger.info(
        "FIFA rankings: %d rows, %d unique teams, date range %s to %s -> %s",
        len(df), df["team"].nunique(),
        df["rank_date"].min().date(), df["rank_date"].max().date(),
        out_path,
    )
    return df


def process_fixtures() -> pd.DataFrame:
    """Load fixtures.csv (upcoming scheduled matches), standardize, write to fixtures.parquet."""
    fx_path = RAW_DIR / "fixtures.csv"
    if not fx_path.exists():
        logger.warning("No fixtures.csv found")
        return pd.DataFrame()

    try:
        df = pd.read_csv(fx_path, encoding="latin-1")
    except Exception as e:
        logger.error("Failed to read fixtures CSV: %s", e)
        return pd.DataFrame()

    if df.empty:
        logger.warning("Empty fixtures CSV")
        return pd.DataFrame()

    # Strip BOM and whitespace from column names before mapping
    df.columns = [c.strip().lstrip("\ufeff").lstrip("ï»¿") for c in df.columns]

    # Rename columns (same mapping as league CSVs)
    df = df.rename(columns=FDUK_COLUMN_MAP, errors="ignore")

    # Parse date
    if "match_date" in df.columns:
        df["match_date"] = _parse_date_column(df["match_date"])

    # Resolve team names
    if "home_team" in df.columns:
        df["home_team"] = df["home_team"].apply(
            lambda x: resolve_team_name(str(x), source="fixtures") if pd.notna(x) else x
        )
    if "away_team" in df.columns:
        df["away_team"] = df["away_team"].apply(
            lambda x: resolve_team_name(str(x), source="fixtures") if pd.notna(x) else x
        )

    # Cast odds to float
    for col in ["odds_home", "odds_draw", "odds_away"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Preserve kickoff time if available
    if "Time" in df.columns:
        df["kickoff_time"] = df["Time"].astype(str).str.strip()
    elif "time" in df.columns:
        df["kickoff_time"] = df["time"].astype(str).str.strip()

    # Keep needed columns
    keep_cols = [
        "league_code", "match_date", "kickoff_time", "home_team", "away_team",
        "odds_home", "odds_draw", "odds_away",
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols].dropna(subset=["match_date", "home_team", "away_team"])
    df = df.sort_values("match_date").reset_index(drop=True)

    out_path = PROCESSED_DIR / "fixtures.parquet"
    df.to_parquet(out_path, index=False, engine="pyarrow")
    logger.info("Fixtures: %d upcoming matches -> %s", len(df), out_path)
    return df


def run_processing() -> None:
    """Top-level function: process all raw data sources."""
    logger.info("Starting data processing...")
    process_club_matches()
    process_international_matches()
    process_fifa_rankings()
    process_fixtures()
    logger.info("Data processing complete.")
