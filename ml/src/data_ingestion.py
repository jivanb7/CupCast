"""
ml/src/data_ingestion.py
=========================
Download raw data from all sources and save to data/raw/.

Data sources:
  1. football-data.co.uk CSVs -- club league historical results
  2. football-data.co.uk fixtures.csv -- upcoming scheduled matches
  3. Kaggle (patateriedata) -- international results (daily-updated)
  4. Kaggle -- FIFA World Rankings (through ~June 2024, supplemented manually)

Design notes:
  - Downloads are idempotent: if a file already exists and is recent enough,
    skip the download. Override with force=True.
  - All downloads are rate-limited with a small delay between requests to be
    polite to data providers.
  - If any download fails (network error, 404), log the error and continue.
  - Raw files are saved as-is -- no processing in this module.
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from ml.src.config import (
    CLUB_LEAGUES,
    FIXTURES_URL,
    FOOTBALL_DATA_UK_BASE,
    LEAGUE_SEASONS,
    RAW_DIR,
)

logger = logging.getLogger(__name__)

# Seconds to wait between HTTP requests (be polite to free data providers)
REQUEST_DELAY_SECONDS = 0.5
# HTTP request timeout in seconds (connect, read)
HTTP_TIMEOUT = (10, 30)
HTTP_TIMEOUT_LARGE = (10, 120)  # For larger downloads (international results, rankings)


def download_league_csv(
    league_code: str,
    season: str,
    force: bool = False,
) -> Path | None:
    """
    Download a single league-season CSV from football-data.co.uk.

    Returns Path to the downloaded file, or None if the download failed.
    """
    league_dir, league_name = CLUB_LEAGUES[league_code]
    out_dir = RAW_DIR / league_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{season}.csv"

    if out_path.exists() and not force:
        logger.debug("Already exists, skipping: %s", out_path)
        return out_path

    url = f"{FOOTBALL_DATA_UK_BASE}/{season}/{league_code}.csv"
    try:
        time.sleep(REQUEST_DELAY_SECONDS)
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        if resp.status_code == 404:
            logger.warning("404 for %s (season %s may not exist yet)", url, season)
            return None
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        logger.info("Downloaded %s -> %s (%d bytes)", url, out_path, len(resp.content))
        return out_path
    except requests.RequestException as e:
        logger.error("Failed to download %s: %s", url, e)
        return None


def download_all_league_csvs(force: bool = False) -> dict[str, list[Path]]:
    """
    Download all configured league CSVs for all configured seasons.
    Returns a dict mapping league_code -> list of downloaded file paths.
    """
    results: dict[str, list[Path]] = {}
    for league_code, seasons in LEAGUE_SEASONS.items():
        league_name = CLUB_LEAGUES[league_code][1]
        logger.info("Downloading %s (%s): %d seasons", league_name, league_code, len(seasons))
        paths = []
        for season in seasons:
            path = download_league_csv(league_code, season, force=force)
            if path is not None:
                paths.append(path)
        results[league_code] = paths
        logger.info("  %s: %d/%d seasons downloaded", league_code, len(paths), len(seasons))
    return results


def download_fixtures_csv(force: bool = False) -> Path | None:
    """
    Download the fixtures.csv file from football-data.co.uk.
    Contains all upcoming scheduled matches with pre-match betting odds.
    """
    out_path = RAW_DIR / "fixtures.csv"
    if out_path.exists() and not force:
        # Re-download if older than 1 day (fixtures change frequently)
        age = datetime.now() - datetime.fromtimestamp(out_path.stat().st_mtime)
        if age < timedelta(days=1):
            logger.debug("Fixtures file recent enough, skipping")
            return out_path

    try:
        time.sleep(REQUEST_DELAY_SECONDS)
        resp = requests.get(FIXTURES_URL, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        logger.info("Downloaded fixtures.csv (%d bytes)", len(resp.content))
        return out_path
    except requests.RequestException as e:
        logger.error("Failed to download fixtures.csv: %s", e)
        return None


def download_international_results(force: bool = False) -> Path | None:
    """
    Download the daily-updated international football results dataset.

    Tries two sources in order:
      1. Direct GitHub raw URL (no auth needed, works on any VM)
      2. Kaggle via kagglehub (requires ~/.kaggle/kaggle.json credentials)

    If neither works but the file already exists locally, keeps the existing copy.
    """
    out_dir = RAW_DIR / "international"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.csv"

    if out_path.exists() and not force:
        logger.debug("International results already exist, skipping")
        return out_path

    # Source 1: Direct GitHub raw URL (martj42's repo, same data as Kaggle)
    github_url = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
    try:
        time.sleep(REQUEST_DELAY_SECONDS)
        resp = requests.get(github_url, timeout=HTTP_TIMEOUT_LARGE)
        if resp.status_code == 200 and len(resp.content) > 10000:
            out_path.write_bytes(resp.content)
            logger.info("Downloaded international results from GitHub (%d bytes)", len(resp.content))
            return out_path
        else:
            logger.warning("GitHub download returned %d, trying Kaggle", resp.status_code)
    except Exception as e:
        logger.warning("GitHub download failed: %s, trying Kaggle", e)

    # Source 2: Kaggle via kagglehub
    try:
        import kagglehub
        path = kagglehub.dataset_download("martj42/international-football-results-from-1872-to-2017")
        logger.info("Kaggle dataset downloaded to: %s", path)
        downloaded = Path(path)
        src_file = None
        for candidate in [downloaded / "results.csv", downloaded]:
            if candidate.is_file() and candidate.suffix == ".csv":
                src_file = candidate
                break
            elif candidate.is_dir():
                csvs = list(candidate.glob("*.csv"))
                if csvs:
                    for c in csvs:
                        if "result" in c.name.lower():
                            src_file = c
                            break
                    if src_file is None:
                        src_file = csvs[0]
                    break

        if src_file is None:
            logger.error("Could not find results CSV in Kaggle download at %s", path)
            return out_path if out_path.exists() else None

        import shutil
        shutil.copy2(src_file, out_path)
        logger.info("International results saved to %s", out_path)

        for extra in ["shootouts.csv", "goalscorers.csv"]:
            extra_src = downloaded / extra
            if extra_src.exists():
                shutil.copy2(extra_src, out_dir / extra)

        return out_path
    except Exception as e:
        logger.error("Failed to download international results: %s", e)
        # If we already have data locally, keep using it
        if out_path.exists():
            logger.info("Using existing local copy of international results")
            return out_path
        return None


def download_fifa_rankings(force: bool = False) -> Path | None:
    """
    Download FIFA world rankings CSV.

    Tries Kaggle via kagglehub first. If credentials aren't available,
    keeps the existing local copy (FIFA rankings don't change often).
    """
    out_dir = RAW_DIR / "fifa_rankings"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "rankings.csv"

    if out_path.exists() and not force:
        logger.debug("FIFA rankings already exist, skipping")
        return out_path

    try:
        import kagglehub
        path = kagglehub.dataset_download("cashncarry/fifaworldranking")
        logger.info("FIFA rankings downloaded to: %s", path)
        downloaded = Path(path)

        src_file = None
        if downloaded.is_file():
            src_file = downloaded
        else:
            csvs = list(downloaded.glob("*.csv"))
            if csvs:
                src_file = max(csvs, key=lambda p: p.stat().st_size)

        if src_file is None:
            logger.error("Could not find rankings CSV in Kaggle download at %s", path)
            return out_path if out_path.exists() else None

        import shutil
        shutil.copy2(src_file, out_path)
        logger.info("FIFA rankings saved to %s (%d bytes)", out_path, out_path.stat().st_size)
        return out_path
    except Exception as e:
        logger.warning("Kaggle download failed: %s", e)
        # FIFA rankings update infrequently — using existing copy is fine
        if out_path.exists():
            logger.info("Using existing local copy of FIFA rankings")
            return out_path
        logger.error("No FIFA rankings available (no local copy and Kaggle failed)")
        return None


def check_data_freshness(df: pd.DataFrame, date_column: str = "date", max_days_stale: int = 30) -> bool:
    """
    Check if the most recent match in the dataset is within max_days_stale days.
    Returns True if data is fresh enough, False if stale.
    """
    try:
        dates = pd.to_datetime(df[date_column], errors="coerce")
        latest = dates.max()
        if pd.isna(latest):
            logger.warning("No valid dates found in column '%s'", date_column)
            return False

        age_days = (pd.Timestamp.now() - latest).days
        if age_days > max_days_stale:
            logger.warning(
                "Data is %d days stale (latest: %s, threshold: %d days)",
                age_days, latest.date(), max_days_stale,
            )
            return False

        logger.info("Data freshness OK: latest date %s (%d days old)", latest.date(), age_days)
        return True
    except Exception as e:
        logger.error("Error checking data freshness: %s", e)
        return False


def run_ingestion(force: bool = False) -> None:
    """
    Top-level function: download all data sources.
    Called by run_pipeline.py.
    """
    logger.info("Starting data ingestion...")
    download_all_league_csvs(force=force)
    download_fixtures_csv(force=force)
    download_international_results(force=force)
    download_fifa_rankings(force=force)
    logger.info("Data ingestion complete.")
