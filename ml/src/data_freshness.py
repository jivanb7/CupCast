"""Data freshness check — fails the pipeline if all CSV sources are stale.

The retrain cron runs weekly. If the freshest league is more than 9 days
stale (7-day cron interval + 2-day buffer), the underlying football-data.co.uk
CSV source has likely broken upstream and we should not silently retrain on
outdated data.

Logic: read the processed match parquets, compute lag per league, and fail
if the MIN lag across all leagues exceeds the threshold. Using min instead
of max correctly handles off-season leagues (a single in-season league at
lag <= threshold is enough to certify the source is alive).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_MAX_LAG_DAYS = 9
PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"


def check_freshness(max_lag_days: int = DEFAULT_MAX_LAG_DAYS) -> None:
    """Verify the freshest league in our processed data is within
    `max_lag_days` of today. Raises RuntimeError if every league is stale.
    """
    today = pd.Timestamp.utcnow().normalize().tz_localize(None)
    leagues_lag: dict[str, tuple[object, int]] = {}

    for parquet_name in ("club_matches.parquet", "intl_matches.parquet"):
        path = PROCESSED_DIR / parquet_name
        if not path.exists():
            logger.warning(f"  {parquet_name} not found, skipping")
            continue
        df = pd.read_parquet(path)
        if "match_date" not in df.columns:
            continue
        df["match_date"] = pd.to_datetime(df["match_date"])
        group_col = "league_code" if "league_code" in df.columns else None
        if group_col:
            for lg, grp in df.groupby(group_col):
                max_d = grp["match_date"].max()
                lag = (today - max_d).days
                leagues_lag[f"{parquet_name.split('_')[0]}/{lg}"] = (max_d.date(), lag)
        else:
            max_d = df["match_date"].max()
            lag = (today - max_d).days
            leagues_lag[parquet_name] = (max_d.date(), lag)

    if not leagues_lag:
        raise RuntimeError("No processed parquets found — cannot check freshness")

    logger.info("=== Data freshness check ===")
    for k, (max_d, lag) in sorted(leagues_lag.items(), key=lambda kv: kv[1][1]):
        marker = "FRESH" if lag <= max_lag_days else "STALE" if lag <= 30 else "OFFSEASON?"
        logger.info(f"  {k:20s}  max={max_d}  lag={lag:3d}d  [{marker}]")

    min_lag = min(lag for _, lag in leagues_lag.values())
    if min_lag > max_lag_days:
        raise RuntimeError(
            f"All data sources are stale: minimum lag is {min_lag} days "
            f"(threshold {max_lag_days}). football-data.co.uk source may be "
            f"broken or down. Investigate before retraining."
        )
    logger.info(
        f"Freshness OK: freshest league is {min_lag}d behind, "
        f"{sum(1 for _, l in leagues_lag.values() if l <= max_lag_days)} of "
        f"{len(leagues_lag)} leagues are within threshold"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    check_freshness()
