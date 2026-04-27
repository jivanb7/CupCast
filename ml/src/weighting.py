"""Recency weighting for training samples."""
import numpy as np
import pandas as pd


def recency_weights(
    match_dates,
    half_life_years: float = 3.0,
    reference_date=None,
) -> np.ndarray:
    """Exponential decay: match from `half_life_years` before reference gets weight 0.5.

    Pass `reference_date` (e.g., `CLUB_TRAIN_END`) to make training runs
    reproducible. The previous implementation used `Timestamp.utcnow()` so
    every rerun re-weighted the same training rows differently — fine for
    ad-hoc experimentation but it makes the promotion gate unstable
    (yesterday's val_log_loss isn't directly comparable to today's because
    the underlying weights drifted). Defaults to `utcnow()` for
    backward compatibility when callers don't pass a reference.
    """
    dates = pd.to_datetime(pd.Series(match_dates)).values.astype("datetime64[D]")
    if reference_date is None:
        ref = np.datetime64(pd.Timestamp.utcnow().date())
    else:
        ref = np.datetime64(pd.to_datetime(reference_date).date())
    age_days = (ref - dates).astype(int)
    # Future matches (e.g. accidental contamination) get capped at age 0 so
    # they don't receive weights > 1 that distort the loss surface.
    age_days = np.maximum(age_days, 0)
    age_years = age_days / 365.25
    return np.exp(-np.log(2.0) * age_years / half_life_years)
