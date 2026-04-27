"""
ml/src/config.py
================
Central configuration for the ML pipeline.

Contains:
  - League codes and download URL patterns for football-data.co.uk
  - Seasons to download per league
  - Feature lists (club model vs international model)
  - Default XGBoost / LightGBM hyperparameter search spaces
  - Train/validation/test split dates
  - Data file paths
  - MLFlow experiment names and model registry names
  - Value-pick edge threshold

All builder agents that need to reference feature names, league codes, or
model names should import from this file rather than hardcoding strings.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# Resolved relative to the ml/ directory
ML_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ML_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
FEATURES_DIR = DATA_DIR / "features"
MODELS_DIR = ML_DIR / "models"

# Ensure dirs exist at import time (no-op if already present)
for _d in [RAW_DIR, PROCESSED_DIR, FEATURES_DIR, MODELS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Football-Data.co.uk Download Config
# ---------------------------------------------------------------------------
FOOTBALL_DATA_UK_BASE = "https://www.football-data.co.uk/mmz4281"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"

# League codes → (raw subdirectory name, human-readable name)
CLUB_LEAGUES = {
    "E0": ("epl", "English Premier League"),
    "E1": ("championship", "English Championship"),
    "SP1": ("laliga", "La Liga"),
    "I1": ("seriea", "Serie A"),
    "D1": ("bundesliga", "Bundesliga"),
    "F1": ("ligue1", "Ligue 1"),
    "E2": ("league_one", "English League One"),
    "E3": ("league_two", "English League Two"),
    "EC": ("national_league", "English National League"),
}

# Seasons to download per league.
# EPL: full history back to 2005/06 for maximum training data.
# Other EU leagues: 2010/11 onwards (good balance of data vs processing time).
# Season code format: "2526" = 2025/26
EPL_SEASONS = [str(y)[2:] + str(y + 1)[2:] for y in range(2005, 2026)]  # 0506..2526
EU_LEAGUE_SEASONS = [str(y)[2:] + str(y + 1)[2:] for y in range(2010, 2026)]  # 1011..2526

LEAGUE_SEASONS = {
    "E0": EPL_SEASONS,
    "E1": EU_LEAGUE_SEASONS,
    "SP1": EU_LEAGUE_SEASONS,
    "I1": EU_LEAGUE_SEASONS,
    "D1": EU_LEAGUE_SEASONS,
    "F1": EU_LEAGUE_SEASONS,
    "E2": EU_LEAGUE_SEASONS,
    "E3": EU_LEAGUE_SEASONS,
    "EC": EU_LEAGUE_SEASONS,
}

# ---------------------------------------------------------------------------
# MLFlow Config
# ---------------------------------------------------------------------------
MLFLOW_EXPERIMENT_CLUB = "cupcast-club"
MLFLOW_EXPERIMENT_INTL = "cupcast-international"
MLFLOW_MODEL_NAME_CLUB = "cupcast-club-model"
MLFLOW_MODEL_NAME_INTL = "cupcast-international-model"

# ---------------------------------------------------------------------------
# Train / Validation / Test Split Dates
# ---------------------------------------------------------------------------
CLUB_TRAIN_END = "2022-06-01"       # Inclusive upper bound for training
CLUB_VAL_END = "2023-06-01"         # Inclusive upper bound for validation
CLUB_TEST_END = "2024-06-01"        # Inclusive upper bound for test set
# Data after CLUB_TEST_END is the live hold-out (2024/25 + 2025/26 current season)

INTL_TRAIN_END = "2020-01-01"
INTL_VAL_END = "2022-01-01"
INTL_TEST_END = "2024-01-01"

# ---------------------------------------------------------------------------
# Target Encoding
# ---------------------------------------------------------------------------
RESULT_TO_INT = {"H": 0, "D": 1, "A": 2}
INT_TO_RESULT = {0: "H", 1: "D", 2: "A"}
RESULT_LABELS = ["H", "D", "A"]

# ---------------------------------------------------------------------------
# Club Model Feature List
# ---------------------------------------------------------------------------
# These are the columns expected in the features DataFrame for the club model.
# Feature engineering must produce exactly these columns (no extras, no missing).
CLUB_FEATURES = [
    # Home team rolling form (5-match window)
    "home_win_rate_5", "home_draw_rate_5", "home_loss_rate_5",
    "home_goals_scored_avg_5", "home_goals_conceded_avg_5",
    "home_goal_diff_avg_5", "home_points_per_game_5",
    # Home team rolling form (10-match window)
    "home_win_rate_10", "home_draw_rate_10", "home_loss_rate_10",
    "home_goals_scored_avg_10", "home_goals_conceded_avg_10",
    "home_goal_diff_avg_10", "home_points_per_game_10",
    "home_clean_sheets_pct_10", "home_failed_to_score_pct_10",
    # Home team home-specific form (5-match)
    "home_home_win_rate_5", "home_home_goals_scored_avg_5", "home_home_goals_conceded_avg_5",
    # Home team shot stats (5-match)
    "home_shots_avg_5", "home_shots_on_target_avg_5", "home_shot_accuracy_5",
    "home_corners_avg_5", "home_yellow_cards_avg_5",
    # Away team rolling form (5-match)
    "away_win_rate_5", "away_draw_rate_5", "away_loss_rate_5",
    "away_goals_scored_avg_5", "away_goals_conceded_avg_5",
    "away_goal_diff_avg_5", "away_points_per_game_5",
    # Away team rolling form (10-match)
    "away_win_rate_10", "away_draw_rate_10", "away_loss_rate_10",
    "away_goals_scored_avg_10", "away_goals_conceded_avg_10",
    "away_goal_diff_avg_10", "away_points_per_game_10",
    "away_clean_sheets_pct_10", "away_failed_to_score_pct_10",
    # Away team away-specific form (5-match)
    "away_away_win_rate_5", "away_away_goals_scored_avg_5", "away_away_goals_conceded_avg_5",
    # Away team shot stats (5-match)
    "away_shots_avg_5", "away_shots_on_target_avg_5", "away_shot_accuracy_5",
    "away_corners_avg_5", "away_yellow_cards_avg_5",
    # Head-to-head (last 5 meetings)
    "h2h_home_wins", "h2h_draws", "h2h_away_wins",
    "h2h_home_goals_avg", "h2h_away_goals_avg",
    # Context
    "days_since_last_match_home", "days_since_last_match_away", "rest_advantage",
    "season_stage", "is_derby", "is_covid_era", "is_new_team_home", "is_new_team_away",
    # Derived interaction features
    "form_diff_goals_scored", "form_diff_goals_conceded", "form_diff_points",
    "attack_vs_defense", "defense_vs_attack",
    # Bookmaker odds (market signal — strongest single predictor)
    "odds_home", "odds_draw", "odds_away",
    "implied_prob_home", "implied_prob_draw", "implied_prob_away",
    # Missingness indicator for the odds block — 1 = real bookmaker odds
    # were captured, 0 = imputed with the historical median. Lets the model
    # learn to discount the odds row when the indicator is off, instead of
    # treating the imputed median as a real "we have no idea" signal.
    "has_odds",
    # Team-level injury snapshot (from backend DB via scripts/export_injuries.py)
    "home_active_injuries", "away_active_injuries",
    "home_key_injuries", "away_key_injuries",
    # 1 when injury parquet covered both teams, 0 when silent fill kicked
    # in. Without this, the historical training data (which has zero injury
    # parquet coverage) looks identical to "every team has 0 injuries" and
    # the model learns to ignore the column.
    "has_injury_data",
    # Team strength signals — added 2026-04-27 to give the model explicit
    # awareness of "1st place vs last place" instead of relying only on
    # rolling form. Computed sequentially over match history so no leakage:
    # each row sees only what was known BEFORE that match.
    "home_elo", "away_elo", "elo_diff",
    "home_league_rank_norm", "away_league_rank_norm", "rank_diff",
    "home_season_ppg", "away_season_ppg", "season_ppg_diff",
    # Key-player availability — score in [0.0, 1.0], lower = top scorers
    # injured/suspended. Populated by scripts/refresh_and_export_player_features.py
    # which calls API-Football top-scorers + injuries endpoints. Defaults
    # to 1.0 (fully available) for matches outside the current season.
    "home_key_player_avail", "away_key_player_avail",
    # 1 when availability parquet covered both teams. Same role as
    # has_injury_data — lets the model distinguish "all key players fit"
    # from "we don't track this team".
    "has_availability_data",
]

# ---------------------------------------------------------------------------
# International Model Feature List
# ---------------------------------------------------------------------------
INTL_FEATURES = [
    # Home team recent form (5-match international only)
    "home_win_rate_5", "home_draw_rate_5", "home_loss_rate_5",
    "home_goals_scored_avg_5", "home_goals_conceded_avg_5",
    "home_goal_diff_avg_5", "home_points_per_game_5",
    # Away team recent form (5-match international only)
    "away_win_rate_5", "away_draw_rate_5", "away_loss_rate_5",
    "away_goals_scored_avg_5", "away_goals_conceded_avg_5",
    "away_goal_diff_avg_5", "away_points_per_game_5",
    # FIFA Rankings
    "fifa_rank_home", "fifa_rank_away", "rank_difference", "rank_points_diff",
    "ranking_is_stale",
    # Tournament context
    "is_neutral_venue", "tournament_type",
    "confederation_home", "confederation_away", "same_confederation",
    "world_cup_appearances_home", "world_cup_appearances_away",
    # Head-to-head (last 5 meetings, international only)
    "h2h_home_wins", "h2h_draws", "h2h_away_wins",
    "h2h_home_goals_avg", "h2h_away_goals_avg",
    # Context
    "days_since_last_match_home", "days_since_last_match_away", "rest_advantage",
    # Derived
    "form_diff_goals_scored", "form_diff_goals_conceded", "form_diff_points",
    # Team-level injury snapshot
    "home_active_injuries", "away_active_injuries",
    "home_key_injuries", "away_key_injuries",
]

# ---------------------------------------------------------------------------
# Value Pick Config
# ---------------------------------------------------------------------------
VALUE_PICK_EDGE_THRESHOLD = 0.08  # Model prob minus bookmaker implied prob > 8% = value pick

# ---------------------------------------------------------------------------
# COVID Era Flag
# ---------------------------------------------------------------------------
COVID_ERA_START = "2020-03-01"
COVID_ERA_END = "2021-07-31"

# ---------------------------------------------------------------------------
# XGBoost Default Hyperparameter Search Space (for Optuna)
# ---------------------------------------------------------------------------
XGBOOST_SEARCH_SPACE = {
    "max_depth": {"type": "int", "low": 3, "high": 10},
    "learning_rate": {"type": "float", "low": 0.01, "high": 0.3, "log": True},
    "n_estimators": {"type": "int", "low": 100, "high": 1000},
    "subsample": {"type": "float", "low": 0.6, "high": 1.0},
    "colsample_bytree": {"type": "float", "low": 0.6, "high": 1.0},
    "min_child_weight": {"type": "int", "low": 1, "high": 10},
    "gamma": {"type": "float", "low": 0, "high": 5},
    "reg_alpha": {"type": "float", "low": 1e-8, "high": 10.0, "log": True},
    "reg_lambda": {"type": "float", "low": 1e-8, "high": 10.0, "log": True},
}
# ---------------------------------------------------------------------------
# World Cup 2026 Groups
# ---------------------------------------------------------------------------
WORLD_CUP_2026_GROUPS = {
    "A": ["Mexico", "South Africa", "South Korea", "Czech Republic"],
    "B": ["Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland"],
    "C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D": ["United States", "Paraguay", "Australia", "Turkey"],
    "E": ["Germany", "Curaçao", "Côte d'Ivoire", "Ecuador"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "H": ["Spain", "Cape Verde Islands", "Saudi Arabia", "Uruguay"],
    "I": ["France", "Senegal", "Iraq", "Norway"],
    "J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "K": ["Portugal", "Democratic Republic of Congo", "Uzbekistan", "Colombia"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}

