"""
ml/src/feature_engineering.py
==============================
Compute all ML features for each match row.

CRITICAL: NO DATA LEAKAGE.
All rolling features for a match at date T must be computed using ONLY matches
where match_date < T.

Strategy: For each team, sort their match appearances chronologically, compute
rolling stats using shift(1) within each team group (safe because we've isolated
one team's matches in chronological order and sorted by date), then merge back.
"""

import logging

import numpy as np
import pandas as pd

from ml.src.config import (
    CLUB_FEATURES,
    COVID_ERA_END,
    COVID_ERA_START,
    FEATURES_DIR,
    INTL_FEATURES,
    PROCESSED_DIR,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: build team-match history from home/away perspectives
# ---------------------------------------------------------------------------

def _build_team_history(matches_df: pd.DataFrame) -> pd.DataFrame:
    """
    Stack home and away perspectives into one row per team-match occurrence.

    For each match, we create two rows:
      - Home team perspective: team=home_team, is_home=1, goals_for=home_goals, etc.
      - Away team perspective: team=away_team, is_home=0, goals_for=away_goals, etc.

    Sorted by (team, match_date) for chronological rolling computations.
    """
    df = matches_df.copy()
    # Ensure unique match identifier
    df["match_idx"] = np.arange(len(df))

    # Home perspective
    home = pd.DataFrame({
        "match_idx": df["match_idx"],
        "match_date": df["match_date"],
        "team": df["home_team"],
        "opponent": df["away_team"],
        "is_home": 1,
        "goals_for": df["home_goals"],
        "goals_against": df["away_goals"],
        "result": df["result"],
        "won": (df["result"] == "H").astype(int),
        "drawn": (df["result"] == "D").astype(int),
        "lost": (df["result"] == "A").astype(int),
        "points": df["result"].map({"H": 3, "D": 1, "A": 0}).fillna(0).astype(int),
        "clean_sheet": (df["away_goals"] == 0).astype(int),
        "failed_to_score": (df["home_goals"] == 0).astype(int),
    })
    # Shot stats (may be NA)
    for col_home, col_away, name in [
        ("home_shots", "away_shots", "shots"),
        ("home_shots_on_target", "away_shots_on_target", "shots_on_target"),
        ("home_corners", "away_corners", "corners"),
        ("home_fouls", "away_fouls", "fouls"),
        ("home_yellow_cards", "away_yellow_cards", "yellow_cards"),
    ]:
        if col_home in df.columns:
            home[name] = pd.to_numeric(df[col_home], errors="coerce")
        else:
            home[name] = np.nan

    if "league_code" in df.columns:
        home["league_code"] = df["league_code"]
    if "season" in df.columns:
        home["season"] = df["season"]

    # Away perspective
    away = pd.DataFrame({
        "match_idx": df["match_idx"],
        "match_date": df["match_date"],
        "team": df["away_team"],
        "opponent": df["home_team"],
        "is_home": 0,
        "goals_for": df["away_goals"],
        "goals_against": df["home_goals"],
        "result": df["result"],
        "won": (df["result"] == "A").astype(int),
        "drawn": (df["result"] == "D").astype(int),
        "lost": (df["result"] == "H").astype(int),
        "points": df["result"].map({"H": 0, "D": 1, "A": 3}).fillna(0).astype(int),
        "clean_sheet": (df["home_goals"] == 0).astype(int),
        "failed_to_score": (df["away_goals"] == 0).astype(int),
    })
    for col_away, col_home, name in [
        ("away_shots", "home_shots", "shots"),
        ("away_shots_on_target", "home_shots_on_target", "shots_on_target"),
        ("away_corners", "home_corners", "corners"),
        ("away_fouls", "home_fouls", "fouls"),
        ("away_yellow_cards", "home_yellow_cards", "yellow_cards"),
    ]:
        if col_away in df.columns:
            away[name] = pd.to_numeric(df[col_away], errors="coerce")
        else:
            away[name] = np.nan

    if "league_code" in df.columns:
        away["league_code"] = df["league_code"]
    if "season" in df.columns:
        away["season"] = df["season"]

    history = pd.concat([home, away], ignore_index=True)
    history = history.sort_values(["team", "match_date", "match_idx"]).reset_index(drop=True)
    return history


def _rolling_shifted(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling mean with shift(1) to exclude current row (no leakage)."""
    return series.shift(1).rolling(window=window, min_periods=1).mean()


# ---------------------------------------------------------------------------
# Core feature computation
# ---------------------------------------------------------------------------

def compute_team_form(
    matches_df: pd.DataFrame,
    windows: list[int] = [5, 10],
) -> pd.DataFrame:
    """
    Compute rolling form statistics for each team in each match.
    Returns DataFrame indexed on match_idx with home_ and away_ prefixed columns.
    """
    history = _build_team_history(matches_df)

    # Compute rolling stats per team for each window using transform-friendly approach
    stats = history[["match_idx", "team", "is_home"]].copy()

    for w in windows:
        base_cols = ["won", "drawn", "lost", "goals_for", "goals_against", "points"]
        if w == 10:
            base_cols += ["clean_sheet", "failed_to_score"]

        for col in base_cols:
            shifted = history.groupby("team")[col].transform(
                lambda s: s.shift(1).rolling(window=w, min_periods=1).mean()
            )
            # Map column names to feature names
            name_map = {
                "won": f"win_rate_{w}", "drawn": f"draw_rate_{w}", "lost": f"loss_rate_{w}",
                "goals_for": f"goals_scored_avg_{w}", "goals_against": f"goals_conceded_avg_{w}",
                "points": f"points_per_game_{w}",
                "clean_sheet": f"clean_sheets_pct_{w}", "failed_to_score": f"failed_to_score_pct_{w}",
            }
            stats[name_map[col]] = shifted

        stats[f"goal_diff_avg_{w}"] = stats[f"goals_scored_avg_{w}"] - stats[f"goals_conceded_avg_{w}"]

    # Pivot from team-match to match (home vs away)
    home_stats = stats[stats["is_home"] == 1].copy()
    away_stats = stats[stats["is_home"] == 0].copy()

    stat_cols = [c for c in home_stats.columns if c not in ["match_idx", "team", "is_home"]]
    home_renamed = home_stats[["match_idx"] + stat_cols].rename(
        columns={c: f"home_{c}" for c in stat_cols}
    )
    away_renamed = away_stats[["match_idx"] + stat_cols].rename(
        columns={c: f"away_{c}" for c in stat_cols}
    )

    result = home_renamed.merge(away_renamed, on="match_idx", how="outer")
    return result


def compute_home_away_splits(
    matches_df: pd.DataFrame,
    window: int = 5,
) -> pd.DataFrame:
    """
    Compute rolling stats using ONLY home matches for the home team,
    and ONLY away matches for the away team.
    """
    history = _build_team_history(matches_df)

    # Home-only stats for home team
    home_only = history[history["is_home"] == 1].copy()

    home_only["home_win_rate_5"] = home_only.groupby("team")["won"].transform(
        lambda s: s.shift(1).rolling(window=window, min_periods=1).mean()
    )
    home_only["home_goals_scored_avg_5"] = home_only.groupby("team")["goals_for"].transform(
        lambda s: s.shift(1).rolling(window=window, min_periods=1).mean()
    )
    home_only["home_goals_conceded_avg_5"] = home_only.groupby("team")["goals_against"].transform(
        lambda s: s.shift(1).rolling(window=window, min_periods=1).mean()
    )

    home_result = home_only[["match_idx", "home_win_rate_5",
                             "home_goals_scored_avg_5", "home_goals_conceded_avg_5"]].rename(
        columns={
            "home_win_rate_5": "home_home_win_rate_5",
            "home_goals_scored_avg_5": "home_home_goals_scored_avg_5",
            "home_goals_conceded_avg_5": "home_home_goals_conceded_avg_5",
        }
    )

    # Away-only stats for away team
    away_only = history[history["is_home"] == 0].copy()

    away_only["away_win_rate_5"] = away_only.groupby("team")["won"].transform(
        lambda s: s.shift(1).rolling(window=window, min_periods=1).mean()
    )
    away_only["away_goals_scored_avg_5"] = away_only.groupby("team")["goals_for"].transform(
        lambda s: s.shift(1).rolling(window=window, min_periods=1).mean()
    )
    away_only["away_goals_conceded_avg_5"] = away_only.groupby("team")["goals_against"].transform(
        lambda s: s.shift(1).rolling(window=window, min_periods=1).mean()
    )

    away_result = away_only[["match_idx", "away_win_rate_5",
                             "away_goals_scored_avg_5", "away_goals_conceded_avg_5"]].rename(
        columns={
            "away_win_rate_5": "away_away_win_rate_5",
            "away_goals_scored_avg_5": "away_away_goals_scored_avg_5",
            "away_goals_conceded_avg_5": "away_away_goals_conceded_avg_5",
        }
    )

    return home_result.merge(away_result, on="match_idx", how="outer")


def compute_shot_stats(
    matches_df: pd.DataFrame,
    window: int = 5,
) -> pd.DataFrame:
    """Compute rolling shot statistics."""
    history = _build_team_history(matches_df)

    for col, name in [("shots", "shots_avg"), ("shots_on_target", "shots_on_target_avg"),
                      ("corners", "corners_avg"), ("yellow_cards", "yellow_cards_avg")]:
        history[name] = history.groupby("team")[col].transform(
            lambda s: s.shift(1).rolling(window=window, min_periods=1).mean()
        )

    # Shot accuracy: shots_on_target / shots (handle division by zero)
    history["shot_accuracy"] = np.where(
        history["shots_avg"] > 0,
        history["shots_on_target_avg"] / history["shots_avg"],
        np.nan,
    )

    stat_cols = ["shots_avg", "shots_on_target_avg", "shot_accuracy", "corners_avg", "yellow_cards_avg"]

    home_stats = history[history["is_home"] == 1][["match_idx"] + stat_cols].rename(
        columns={c: f"home_{c}_5" for c in stat_cols}
    )
    away_stats = history[history["is_home"] == 0][["match_idx"] + stat_cols].rename(
        columns={c: f"away_{c}_5" for c in stat_cols}
    )

    return home_stats.merge(away_stats, on="match_idx", how="outer")


def compute_h2h_features(
    matches_df: pd.DataFrame,
    n_meetings: int = 5,
) -> pd.DataFrame:
    """
    Compute head-to-head statistics between the specific home/away team pair.
    For each match, looks at the last n_meetings between the two teams (any venue).
    """
    df = matches_df.copy()
    df["match_idx"] = np.arange(len(df))
    df = df.sort_values("match_date").reset_index(drop=True)

    # Create a pair key (alphabetically sorted for consistency)
    df["pair"] = df.apply(
        lambda r: tuple(sorted([r["home_team"], r["away_team"]])), axis=1
    )

    results = []
    for pair, group in df.groupby("pair"):
        group = group.sort_values("match_date").reset_index(drop=True)
        for i in range(len(group)):
            row = group.iloc[i]
            # Prior meetings (strict date < current)
            prior = group.iloc[:i]
            if len(prior) == 0:
                results.append({
                    "match_idx": row["match_idx"],
                    "h2h_home_wins": 0, "h2h_draws": 0, "h2h_away_wins": 0,
                    "h2h_home_goals_avg": 0.0, "h2h_away_goals_avg": 0.0,
                })
                continue

            last_n = prior.tail(n_meetings)
            current_home = row["home_team"]
            current_away = row["away_team"]

            # Count wins from perspective of current home team
            home_wins = 0
            away_wins = 0
            draws = 0
            home_goals = []
            away_goals = []

            for _, prev in last_n.iterrows():
                if prev["home_team"] == current_home:
                    # Same home/away arrangement
                    home_goals.append(prev["home_goals"])
                    away_goals.append(prev["away_goals"])
                    if prev["result"] == "H":
                        home_wins += 1
                    elif prev["result"] == "A":
                        away_wins += 1
                    else:
                        draws += 1
                else:
                    # Reversed: current home team was away
                    home_goals.append(prev["away_goals"])
                    away_goals.append(prev["home_goals"])
                    if prev["result"] == "A":
                        home_wins += 1
                    elif prev["result"] == "H":
                        away_wins += 1
                    else:
                        draws += 1

            results.append({
                "match_idx": row["match_idx"],
                "h2h_home_wins": home_wins,
                "h2h_draws": draws,
                "h2h_away_wins": away_wins,
                "h2h_home_goals_avg": np.mean(home_goals) if home_goals else 0.0,
                "h2h_away_goals_avg": np.mean(away_goals) if away_goals else 0.0,
            })

    return pd.DataFrame(results)


def compute_context_features(
    matches_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute match context features: rest days, season stage, derby, covid era, new team."""
    df = matches_df.copy()
    df["match_idx"] = np.arange(len(df))
    history = _build_team_history(df)

    # Days since last match per team
    history = history.sort_values(["team", "match_date", "match_idx"])
    history["prev_match_date"] = history.groupby("team")["match_date"].shift(1)
    history["days_since_last"] = (history["match_date"] - history["prev_match_date"]).dt.days

    # Count historical matches per team (for is_new_team)
    history["match_count"] = history.groupby("team").cumcount()

    # Home team rest
    home_ctx = history[history["is_home"] == 1][["match_idx", "days_since_last", "match_count"]].rename(
        columns={"days_since_last": "days_since_last_match_home", "match_count": "_home_match_count"}
    )
    # Away team rest
    away_ctx = history[history["is_home"] == 0][["match_idx", "days_since_last", "match_count"]].rename(
        columns={"days_since_last": "days_since_last_match_away", "match_count": "_away_match_count"}
    )

    ctx = home_ctx.merge(away_ctx, on="match_idx", how="outer")

    # Cap rest days at 90 (off-season should not dominate)
    ctx["days_since_last_match_home"] = ctx["days_since_last_match_home"].clip(upper=90).fillna(30)
    ctx["days_since_last_match_away"] = ctx["days_since_last_match_away"].clip(upper=90).fillna(30)
    ctx["rest_advantage"] = ctx["days_since_last_match_home"] - ctx["days_since_last_match_away"]

    # Season stage: approximate as match order within season for each league
    if "season" in df.columns and "league_code" in df.columns:
        df["_season_rank"] = df.groupby(["league_code", "season"]).cumcount()
        df["_season_total"] = df.groupby(["league_code", "season"])["_season_rank"].transform("max") + 1
        df["season_stage"] = df["_season_rank"] / df["_season_total"]
    else:
        # International: use match date within the year
        df["season_stage"] = df["match_date"].dt.dayofyear / 365.0

    ctx = ctx.merge(df[["match_idx", "season_stage"]], on="match_idx", how="left")

    # Derby detection
    derby_set = set()
    for pair in KNOWN_DERBIES:
        derby_set.add(pair)
    ctx = ctx.merge(
        df[["match_idx", "home_team", "away_team", "match_date"]],
        on="match_idx", how="left",
    )
    ctx["is_derby"] = ctx.apply(
        lambda r: int(frozenset({r["home_team"], r["away_team"]}) in derby_set), axis=1
    )

    # COVID era
    covid_start = pd.Timestamp(COVID_ERA_START)
    covid_end = pd.Timestamp(COVID_ERA_END)
    ctx["is_covid_era"] = ((ctx["match_date"] >= covid_start) & (ctx["match_date"] <= covid_end)).astype(int)

    # New team flags (fewer than 5 historical matches)
    ctx["is_new_team_home"] = (ctx["_home_match_count"] < 5).astype(int)
    ctx["is_new_team_away"] = (ctx["_away_match_count"] < 5).astype(int)

    keep_cols = [
        "match_idx", "days_since_last_match_home", "days_since_last_match_away",
        "rest_advantage", "season_stage", "is_derby", "is_covid_era",
        "is_new_team_home", "is_new_team_away",
    ]
    return ctx[keep_cols]


def compute_intl_features(
    matches_df: pd.DataFrame,
    rankings_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute international-specific features (FIFA rankings, confederation, etc.)."""
    df = matches_df.copy()
    df["match_idx"] = np.arange(len(df))

    # Prepare rankings: for each team, sorted by rank_date
    rk = rankings_df.sort_values(["team", "rank_date"]).copy()

    def _get_ranking_at_date(team: str, match_date: pd.Timestamp) -> dict:
        """Get the most recent ranking for a team on or before match_date."""
        team_rk = rk[rk["team"] == team]
        if len(team_rk) == 0:
            return {"fifa_rank": 200, "total_points": 0, "confederation": "UNK", "is_stale": True}
        prior = team_rk[team_rk["rank_date"] <= match_date]
        if len(prior) == 0:
            # Use earliest available
            row = team_rk.iloc[0]
            return {
                "fifa_rank": int(row["fifa_rank"]),
                "total_points": float(row.get("total_points", 0)),
                "confederation": str(row.get("confederation", "UNK")),
                "is_stale": True,
            }
        row = prior.iloc[-1]
        days_diff = (match_date - row["rank_date"]).days
        return {
            "fifa_rank": int(row["fifa_rank"]),
            "total_points": float(row.get("total_points", 0)),
            "confederation": str(row.get("confederation", "UNK")),
            "is_stale": days_diff > 365,
        }

    # Build a lookup cache for efficiency
    # Group rankings by team for faster lookup
    rk_groups = {team: grp.reset_index(drop=True) for team, grp in rk.groupby("team")}

    def _fast_ranking(team: str, match_date: pd.Timestamp) -> dict:
        """Optimized ranking lookup using pre-grouped data."""
        grp = rk_groups.get(team)
        if grp is None:
            return {"fifa_rank": 200, "total_points": 0, "confederation": "UNK", "is_stale": True}
        mask = grp["rank_date"] <= match_date
        if not mask.any():
            row = grp.iloc[0]
            return {
                "fifa_rank": int(row["fifa_rank"]),
                "total_points": float(row.get("total_points", 0)),
                "confederation": str(row.get("confederation", "UNK")),
                "is_stale": True,
            }
        idx = mask[::-1].idxmax()  # Last True index
        row = grp.loc[idx]
        days_diff = (match_date - row["rank_date"]).days
        return {
            "fifa_rank": int(row["fifa_rank"]),
            "total_points": float(row.get("total_points", 0)),
            "confederation": str(row.get("confederation", "UNK")),
            "is_stale": days_diff > 365,
        }

    # Compute rankings for each match (this is O(n*log(m)) with cached groups)
    logger.info("Computing FIFA ranking features for %d international matches...", len(df))
    home_rankings = df.apply(
        lambda r: _fast_ranking(r["home_team"], r["match_date"]), axis=1, result_type="expand"
    )
    away_rankings = df.apply(
        lambda r: _fast_ranking(r["away_team"], r["match_date"]), axis=1, result_type="expand"
    )

    result = pd.DataFrame({
        "match_idx": df["match_idx"],
        "fifa_rank_home": home_rankings["fifa_rank"],
        "fifa_rank_away": away_rankings["fifa_rank"],
        "rank_difference": away_rankings["fifa_rank"] - home_rankings["fifa_rank"],
        "rank_points_diff": home_rankings["total_points"] - away_rankings["total_points"],
        "ranking_is_stale": (home_rankings["is_stale"] | away_rankings["is_stale"]).astype(int),
        "confederation_home": home_rankings["confederation"],
        "confederation_away": away_rankings["confederation"],
        "same_confederation": (home_rankings["confederation"] == away_rankings["confederation"]).astype(int),
    })

    # Neutral venue (from the processed data)
    if "is_neutral_venue" in df.columns:
        result["is_neutral_venue"] = df["is_neutral_venue"].values
    else:
        result["is_neutral_venue"] = 0

    # Tournament type (encode as ordinal)
    if "tournament_type" in df.columns:
        tournament_encoding = {
            "friendly": 0, "competitive": 1, "qualifier": 2,
            "continental": 3, "world_cup": 4,
        }
        result["tournament_type"] = df["tournament_type"].map(tournament_encoding).fillna(1).astype(int)
    else:
        result["tournament_type"] = 1

    # World Cup appearances (hardcoded for top nations)
    WC_APPEARANCES = {
        "Brazil": 22, "Germany": 20, "Italy": 18, "Argentina": 18, "Mexico": 17,
        "France": 16, "England": 16, "Spain": 16, "United States": 11, "South Korea": 11,
        "Belgium": 14, "Uruguay": 14, "Netherlands": 11, "Sweden": 12, "Switzerland": 12,
        "Japan": 7, "Portugal": 8, "Australia": 6, "Colombia": 6, "Iran": 6,
        "Saudi Arabia": 7, "Tunisia": 6, "Morocco": 6, "Senegal": 3, "Ghana": 4,
        "Croatia": 6, "Ecuador": 4, "Turkey": 2, "South Africa": 3, "Panama": 2,
        "Canada": 2, "Qatar": 1, "Czech Republic": 2, "Scotland": 8, "Norway": 3,
        "Austria": 7, "Denmark": 5, "Poland": 8, "Cameroon": 8, "Nigeria": 6,
        "Egypt": 3, "Algeria": 4, "Côte d'Ivoire": 3, "Iraq": 1, "Jordan": 0,
        "New Zealand": 2, "Democratic Republic of Congo": 1, "Uzbekistan": 0,
        "Haiti": 1, "Cape Verde Islands": 0, "Curaçao": 0,
        "Bosnia and Herzegovina": 1, "Paraguay": 8, "Chile": 9, "Peru": 5,
        "Costa Rica": 6, "Honduras": 3, "El Salvador": 2, "Cuba": 1,
    }
    result["world_cup_appearances_home"] = df["home_team"].map(WC_APPEARANCES).fillna(0).astype(int)
    result["world_cup_appearances_away"] = df["away_team"].map(WC_APPEARANCES).fillna(0).astype(int)

    # Encode confederation as ordinal for the model
    confed_encoding = {"UEFA": 0, "CONMEBOL": 1, "CONCACAF": 2, "CAF": 3, "AFC": 4, "OFC": 5, "UNK": 6}
    result["confederation_home"] = result["confederation_home"].map(confed_encoding).fillna(6).astype(int)
    result["confederation_away"] = result["confederation_away"].map(confed_encoding).fillna(6).astype(int)

    return result


def add_availability_features(
    df: pd.DataFrame,
    avail_path: str | None = None,
) -> pd.DataFrame:
    """Merge per-team key-player availability score onto the feature frame.

    `key_player_avail` is a [0.0, 1.0] score — 1.0 = top scorers all available,
    lower = key attackers injured/suspended. Computed by
    backend.services.player_availability_service.compute_key_player_availability
    and exported to ml/data/processed/team_availability.parquet by
    scripts/refresh_and_export_player_features.py.

    Falls back to 1.0 (fully available) when the parquet is missing or when
    a team has no row — same default the backend service uses.
    """
    from pathlib import Path as _Path

    out_cols = ["home_key_player_avail", "away_key_player_avail"]

    path = _Path(avail_path) if avail_path else (
        PROCESSED_DIR / "team_availability.parquet"
    )

    if not path.exists():
        logger.warning("Availability parquet not found at %s — defaulting to 1.0", path)
        for c in out_cols:
            df[c] = 1.0
        return df

    if "home_team_id" not in df.columns or "away_team_id" not in df.columns:
        logger.warning("home_team_id/away_team_id not in feature frame — defaulting availability to 1.0")
        for c in out_cols:
            df[c] = 1.0
        return df

    avail = pd.read_parquet(path)[["team_id", "key_player_avail"]]

    home = avail.rename(columns={
        "team_id": "home_team_id",
        "key_player_avail": "home_key_player_avail",
    })
    away = avail.rename(columns={
        "team_id": "away_team_id",
        "key_player_avail": "away_key_player_avail",
    })

    df = df.merge(home, on="home_team_id", how="left")
    df = df.merge(away, on="away_team_id", how="left")

    for c in out_cols:
        df[c] = df[c].fillna(1.0).astype(float)

    return df


def add_injury_features(
    df: pd.DataFrame,
    injuries_path: str | None = None,
) -> pd.DataFrame:
    """Merge per-team active/key-active injury counts onto the feature frame.

    Expects `df` to contain `home_team_id` and `away_team_id`. If either the
    injuries parquet or the team-id columns are missing, falls back to zero
    columns so the downstream feature list stays aligned.
    """
    from pathlib import Path as _Path

    out_cols = ["home_active_injuries", "away_active_injuries",
                "home_key_injuries", "away_key_injuries"]

    path = _Path(injuries_path) if injuries_path else (
        PROCESSED_DIR / "team_injuries.parquet"
    )

    if not path.exists():
        logger.warning("Injuries parquet not found at %s — filling zero columns", path)
        for c in out_cols:
            df[c] = 0
        return df

    if "home_team_id" not in df.columns or "away_team_id" not in df.columns:
        logger.warning("home_team_id/away_team_id not in feature frame — filling zero injury columns")
        for c in out_cols:
            df[c] = 0
        return df

    inj = pd.read_parquet(path)[
        ["team_id", "active_injuries", "key_active_injuries"]
    ]

    home = inj.rename(columns={
        "team_id": "home_team_id",
        "active_injuries": "home_active_injuries",
        "key_active_injuries": "home_key_injuries",
    })
    away = inj.rename(columns={
        "team_id": "away_team_id",
        "active_injuries": "away_active_injuries",
        "key_active_injuries": "away_key_injuries",
    })

    df = df.merge(home, on="home_team_id", how="left")
    df = df.merge(away, on="away_team_id", how="left")

    for c in out_cols:
        df[c] = df[c].fillna(0).astype(int)

    return df


def compute_team_strength_features(matches_df: pd.DataFrame) -> pd.DataFrame:
    """Compute Elo + per-season league rank for every match.

    These two feature sets give the model explicit awareness of structural
    team strength — the thing that separates a "Bayern is in 1st place"
    intuition from a "76 rolling-form numbers" reality. Both features
    are computed sequentially over the match log, no external data
    required, and emit values that are pre-match (no leakage).

    Returns a DataFrame keyed by match_idx with these columns:
      home_elo, away_elo, elo_diff
      home_league_rank_norm, away_league_rank_norm, rank_diff
      home_season_ppg, away_season_ppg, season_ppg_diff

    `*_norm` is the rank scaled to [0.0, 1.0] where 1.0 = top of league.
    A match between rank 1 and rank 18 in a 18-team league produces
    rank_diff = +0.94 — a strong directional signal the model can pick up.
    """
    matches = matches_df.sort_values("match_date").reset_index(drop=True).copy()
    if "match_idx" not in matches.columns:
        matches["match_idx"] = np.arange(len(matches))

    # ── Elo ──────────────────────────────────────────────────────────
    K = 20.0          # standard chess Elo k-factor
    HOME_BOOST = 60.0  # ~60 Elo home-field advantage; well-cited in football literature
    BASE = 1500.0
    elo: dict[str, float] = {}
    home_elos = []
    away_elos = []

    # ── League standings ─────────────────────────────────────────────
    # For each (league, season) compute rank-at-each-match. To keep this
    # O(n_matches) we maintain a per-(league, season) running tally of
    # points and games-played for every team encountered, then rank teams
    # at each match's pre-match snapshot.
    season_state: dict[tuple[str, str], dict[str, dict[str, int]]] = {}
    home_rank_norms = []
    away_rank_norms = []
    home_ppgs = []
    away_ppgs = []
    n_teams_per_match = []

    for _, r in matches.iterrows():
        h = r["home_team"]
        a = r["away_team"]
        league = r.get("league_code", "?")
        season = r.get("season", "?")
        key = (league, season)

        # Elo: emit pre-match ratings
        rh = elo.get(h, BASE)
        ra = elo.get(a, BASE)
        home_elos.append(rh)
        away_elos.append(ra)

        # League standings: emit pre-match rank
        state = season_state.setdefault(key, {})
        ppg_by_team = {
            t: (s["pts"] / s["games"]) if s["games"] > 0 else 0.0
            for t, s in state.items()
        }
        n_teams = max(len(state), 2)
        sorted_teams = sorted(ppg_by_team.items(), key=lambda kv: -kv[1])
        rank = {t: i + 1 for i, (t, _) in enumerate(sorted_teams)}

        h_rank = rank.get(h, n_teams)
        a_rank = rank.get(a, n_teams)
        # Normalize: top of table = 1.0, bottom = 0.0
        h_norm = 1.0 - (h_rank - 1) / max(n_teams - 1, 1)
        a_norm = 1.0 - (a_rank - 1) / max(n_teams - 1, 1)
        home_rank_norms.append(h_norm)
        away_rank_norms.append(a_norm)

        h_state = state.get(h, {"pts": 0, "games": 0})
        a_state = state.get(a, {"pts": 0, "games": 0})
        home_ppgs.append(h_state["pts"] / max(h_state["games"], 1))
        away_ppgs.append(a_state["pts"] / max(a_state["games"], 1))
        n_teams_per_match.append(n_teams)

        # Post-match updates (skip if unplayed). The prediction service
        # appends upcoming rows with home_goals=0/away_goals=0 as dummies
        # plus an `is_upcoming` flag — without this guard the Elo + season
        # standings ran an UPDATE for every upcoming match as if it were
        # a real 0-0 draw, which corrupted ratings across batched
        # predictions (Bayern's emitted Elo for one fixture would shift
        # depending on how many other Bayern fixtures were batched ahead
        # of it). NaN goals would be a cleaner sentinel but break Int64
        # casts in data_processing, so we accept an explicit marker.
        if r.get("is_upcoming") is True:
            continue
        hg = r.get("home_goals")
        ag = r.get("away_goals")
        if pd.isna(hg) or pd.isna(ag):
            continue

        # Elo update with home-field boost on the *home* side's expected score
        rh_adj = rh + HOME_BOOST
        expected_h = 1.0 / (1.0 + 10 ** ((ra - rh_adj) / 400))
        if hg > ag:
            actual_h = 1.0
        elif hg < ag:
            actual_h = 0.0
        else:
            actual_h = 0.5
        delta = K * (actual_h - expected_h)
        elo[h] = rh + delta
        elo[a] = ra - delta

        # Standings update
        if hg > ag:
            h_pts, a_pts = 3, 0
        elif hg < ag:
            h_pts, a_pts = 0, 3
        else:
            h_pts, a_pts = 1, 1
        state[h] = {"pts": h_state["pts"] + h_pts, "games": h_state["games"] + 1}
        state[a] = {"pts": a_state["pts"] + a_pts, "games": a_state["games"] + 1}

    out = pd.DataFrame({
        "match_idx": matches["match_idx"].values,
        "home_elo": home_elos,
        "away_elo": away_elos,
        "elo_diff": np.array(home_elos) - np.array(away_elos),
        "home_league_rank_norm": home_rank_norms,
        "away_league_rank_norm": away_rank_norms,
        "rank_diff": np.array(home_rank_norms) - np.array(away_rank_norms),
        "home_season_ppg": home_ppgs,
        "away_season_ppg": away_ppgs,
        "season_ppg_diff": np.array(home_ppgs) - np.array(away_ppgs),
    })
    return out


def _compute_derived_features(features_df: pd.DataFrame) -> pd.DataFrame:
    """Compute interaction / derived features from existing columns."""
    df = features_df.copy()

    # Form differences (using 5-match window)
    if "home_goals_scored_avg_5" in df.columns and "away_goals_scored_avg_5" in df.columns:
        df["form_diff_goals_scored"] = df["home_goals_scored_avg_5"] - df["away_goals_scored_avg_5"]
        df["form_diff_goals_conceded"] = df["home_goals_conceded_avg_5"] - df["away_goals_conceded_avg_5"]
    else:
        df["form_diff_goals_scored"] = 0.0
        df["form_diff_goals_conceded"] = 0.0

    if "home_points_per_game_5" in df.columns and "away_points_per_game_5" in df.columns:
        df["form_diff_points"] = df["home_points_per_game_5"] - df["away_points_per_game_5"]
    else:
        df["form_diff_points"] = 0.0

    # Attack vs defense interaction
    if "home_goals_scored_avg_5" in df.columns and "away_goals_conceded_avg_5" in df.columns:
        df["attack_vs_defense"] = df["home_goals_scored_avg_5"] - df["away_goals_conceded_avg_5"]
        df["defense_vs_attack"] = df["away_goals_scored_avg_5"] - df["home_goals_conceded_avg_5"]
    else:
        df["attack_vs_defense"] = 0.0
        df["defense_vs_attack"] = 0.0

    return df


def impute_missing_features(
    features_df: pd.DataFrame,
    league_code: str | None = None,
) -> pd.DataFrame:
    """Fill any remaining NaN values after feature computation."""
    df = features_df.copy()

    # Odds features: use neutral 1/3 probability, not median (avoids look-ahead bias)
    ODDS_NEUTRAL = {
        "odds_home": 0.0, "odds_draw": 0.0, "odds_away": 0.0,
        "implied_prob_home": 1.0/3.0, "implied_prob_draw": 1.0/3.0, "implied_prob_away": 1.0/3.0,
    }
    for col, neutral_val in ODDS_NEUTRAL.items():
        if col in df.columns and df[col].isna().any():
            df[col] = df[col].fillna(neutral_val)

    # Numeric columns: fill with column median (more robust than mean)
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        if df[col].isna().any():
            fill_val = df[col].median()
            if pd.isna(fill_val):
                fill_val = 0.0
            df[col] = df[col].fillna(fill_val)

    # Boolean-like columns: fill with 0
    bool_cols = [c for c in df.columns if c.startswith("is_")]
    for col in bool_cols:
        df[col] = df[col].fillna(0).astype(int)

    return df


def build_feature_matrix(
    matches_df: pd.DataFrame,
    model_type: str = "club",
    rankings_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Assemble the full feature matrix for a given model type.
    """
    from ml.src.config import RESULT_TO_INT

    df = matches_df.copy()
    df = df.sort_values("match_date").reset_index(drop=True)
    df["match_idx"] = np.arange(len(df))

    # Ensure result_encoded exists
    if "result_encoded" not in df.columns:
        df["result_encoded"] = df["result"].map(RESULT_TO_INT)

    logger.info("Building %s feature matrix for %d matches...", model_type, len(df))

    # 1. Team form
    logger.info("  Computing team form...")
    form = compute_team_form(df, windows=[5, 10])

    # 2. Context features
    logger.info("  Computing context features...")
    context = compute_context_features(df)

    # 3. H2H features
    logger.info("  Computing H2H features...")
    h2h = compute_h2h_features(df, n_meetings=5)

    # Start merging
    features = df[["match_idx", "match_date", "home_team", "away_team", "result_encoded"]].copy()
    if "league_code" in df.columns:
        features["league_code"] = df["league_code"]
    # Carry team ids through so injury features can merge on them
    for _idcol in ("home_team_id", "away_team_id"):
        if _idcol in df.columns:
            features[_idcol] = df[_idcol].values

    features = features.merge(form, on="match_idx", how="left")
    features = features.merge(context, on="match_idx", how="left")
    features = features.merge(h2h, on="match_idx", how="left")

    if model_type == "club":
        # 4. Home/away splits
        logger.info("  Computing home/away splits...")
        ha_splits = compute_home_away_splits(df, window=5)
        features = features.merge(ha_splits, on="match_idx", how="left")

        # 5. Shot stats
        logger.info("  Computing shot stats...")
        shots = compute_shot_stats(df, window=5)
        features = features.merge(shots, on="match_idx", how="left")

        # 5b. Team strength: Elo + per-season league rank. Gives the
        # model explicit awareness of "Bayern is in 1st place" instead of
        # just rolling-form numbers.
        logger.info("  Computing team strength (Elo + league rank)...")
        strength = compute_team_strength_features(df)
        features = features.merge(strength, on="match_idx", how="left")

        # Derived features
        features = _compute_derived_features(features)

        # 6. Bookmaker odds (market signal)
        if "odds_home" in df.columns:
            odds_data = df[["match_idx", "odds_home", "odds_draw", "odds_away"]].copy()
            # Compute implied probabilities (normalized, vig-removed)
            raw_h = 1.0 / odds_data["odds_home"].replace(0, np.nan)
            raw_d = 1.0 / odds_data["odds_draw"].replace(0, np.nan)
            raw_a = 1.0 / odds_data["odds_away"].replace(0, np.nan)
            total = raw_h + raw_d + raw_a
            odds_data["implied_prob_home"] = raw_h / total
            odds_data["implied_prob_draw"] = raw_d / total
            odds_data["implied_prob_away"] = raw_a / total
            features = features.merge(odds_data, on="match_idx", how="left")

        # 7. Injury features (team-level snapshot)
        features = add_injury_features(features)

        # 7b. Key-player availability features (top scorer active/injured)
        features = add_availability_features(features)

        # Impute and select final columns
        features = impute_missing_features(features)

        # Ensure all expected columns exist
        expected = CLUB_FEATURES
        for col in expected:
            if col not in features.columns:
                logger.warning("Missing feature column '%s', filling with 0", col)
                features[col] = 0.0

        # Final selection
        meta_cols = ["match_idx", "match_date", "home_team", "away_team", "league_code", "result_encoded"]
        meta_cols = [c for c in meta_cols if c in features.columns]
        final = features[meta_cols + expected].copy()

    elif model_type == "intl":
        if rankings_df is None:
            raise ValueError("rankings_df required for international model")

        # 4. International features
        logger.info("  Computing international features...")
        intl_feats = compute_intl_features(df, rankings_df)
        features = features.merge(intl_feats, on="match_idx", how="left")

        # Derived features
        features = _compute_derived_features(features)

        # Injury features (team-level snapshot)
        features = add_injury_features(features)

        # Impute
        features = impute_missing_features(features)

        # Ensure all expected columns exist
        expected = INTL_FEATURES
        for col in expected:
            if col not in features.columns:
                logger.warning("Missing feature column '%s', filling with 0", col)
                features[col] = 0.0

        meta_cols = ["match_idx", "match_date", "home_team", "away_team", "result_encoded"]
        meta_cols = [c for c in meta_cols if c in features.columns]
        final = features[meta_cols + expected].copy()
    else:
        raise ValueError(f"Unknown model_type: {model_type}")

    # Drop rows where result_encoded is NaN (unplayed matches)
    final = final.dropna(subset=["result_encoded"])
    final["result_encoded"] = final["result_encoded"].astype(int)

    logger.info("Feature matrix: %d rows, %d feature columns", len(final), len(expected))
    return final


def run_feature_engineering() -> None:
    """Top-level function: compute features for all match types."""
    logger.info("Starting feature engineering...")

    club_df = pd.read_parquet(PROCESSED_DIR / "club_matches.parquet")
    intl_df = pd.read_parquet(PROCESSED_DIR / "intl_matches.parquet")
    rankings_df = pd.read_parquet(PROCESSED_DIR / "fifa_rankings.parquet")

    # Club features
    club_features = build_feature_matrix(club_df, model_type="club")
    club_features.to_parquet(FEATURES_DIR / "club_features.parquet", index=False)
    logger.info("Club features saved: %d rows", len(club_features))

    # International features -- filter to post-2000 for efficiency
    intl_recent = intl_df[intl_df["match_date"] >= "2000-01-01"].reset_index(drop=True)
    intl_features = build_feature_matrix(intl_recent, model_type="intl", rankings_df=rankings_df)
    intl_features.to_parquet(FEATURES_DIR / "intl_features.parquet", index=False)
    logger.info("International features saved: %d rows", len(intl_features))

    logger.info("Feature engineering complete.")


# ---------------------------------------------------------------------------
# Known derby pairs
# ---------------------------------------------------------------------------
KNOWN_DERBIES: set[frozenset[str]] = {
    frozenset({"Manchester United", "Manchester City"}),
    frozenset({"Arsenal FC", "Tottenham Hotspur"}),
    frozenset({"Chelsea FC", "Arsenal FC"}),
    frozenset({"Liverpool FC", "Everton FC"}),
    frozenset({"Leeds United", "Manchester United"}),
    frozenset({"Newcastle United", "Sunderland AFC"}),
    frozenset({"Aston Villa FC", "Birmingham City"}),
    frozenset({"Real Madrid CF", "FC Barcelona"}),
    frozenset({"Real Madrid CF", "Atlético de Madrid"}),
    frozenset({"FC Barcelona", "Atlético de Madrid"}),
    frozenset({"Sevilla FC", "Real Betis"}),
    frozenset({"FC Bayern München", "Borussia Dortmund"}),
    frozenset({"AC Milan", "FC Internazionale Milano"}),
    frozenset({"AS Roma", "SS Lazio"}),
    frozenset({"Juventus FC", "Torino FC"}),
    frozenset({"Olympique de Marseille", "Paris Saint-Germain"}),
    frozenset({"Argentina", "Brazil"}),
    frozenset({"England", "Germany"}),
    frozenset({"Spain", "Portugal"}),
    frozenset({"United States", "Mexico"}),
}
