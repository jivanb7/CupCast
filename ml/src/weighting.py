"""Recency weighting for training samples."""
import numpy as np
import pandas as pd


def recency_weights(match_dates, half_life_years: float = 3.0) -> np.ndarray:
    """Exponential decay: match from `half_life_years` ago gets weight 0.5.
    Returns ndarray aligned to input. Accepts Series or array-like of datetime64."""
    dates = pd.to_datetime(pd.Series(match_dates)).values.astype("datetime64[D]")
    today = np.datetime64(pd.Timestamp.utcnow().date())
    age_days = (today - dates).astype(int)
    age_years = age_days / 365.25
    return np.exp(-np.log(2.0) * age_years / half_life_years)
