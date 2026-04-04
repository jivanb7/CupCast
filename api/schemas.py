"""
Pydantic models for request/response validation.
"""

from pydantic import BaseModel, Field

# The 72 features expected by the club match prediction model.
# Grouped by category for clarity.
REQUIRED_FEATURES: list[str] = [
    # Home team rolling form (5-match window)
    "home_win_rate_5", "home_draw_rate_5", "home_loss_rate_5",
    "home_goals_scored_avg_5", "home_goals_conceded_avg_5",
    "home_goal_diff_avg_5", "home_points_per_game_5",
    # Home team rolling form (10-match window)
    "home_win_rate_10", "home_draw_rate_10", "home_loss_rate_10",
    "home_goals_scored_avg_10", "home_goals_conceded_avg_10",
    "home_goal_diff_avg_10", "home_points_per_game_10",
    "home_clean_sheets_pct_10", "home_failed_to_score_pct_10",
    # Home team home-specific form
    "home_home_win_rate_5", "home_home_goals_scored_avg_5", "home_home_goals_conceded_avg_5",
    # Home team shot stats
    "home_shots_avg_5", "home_shots_on_target_avg_5", "home_shot_accuracy_5",
    "home_corners_avg_5", "home_yellow_cards_avg_5",
    # Away team rolling form (5-match window)
    "away_win_rate_5", "away_draw_rate_5", "away_loss_rate_5",
    "away_goals_scored_avg_5", "away_goals_conceded_avg_5",
    "away_goal_diff_avg_5", "away_points_per_game_5",
    # Away team rolling form (10-match window)
    "away_win_rate_10", "away_draw_rate_10", "away_loss_rate_10",
    "away_goals_scored_avg_10", "away_goals_conceded_avg_10",
    "away_goal_diff_avg_10", "away_points_per_game_10",
    "away_clean_sheets_pct_10", "away_failed_to_score_pct_10",
    # Away team away-specific form
    "away_away_win_rate_5", "away_away_goals_scored_avg_5", "away_away_goals_conceded_avg_5",
    # Away team shot stats
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
    # Bookmaker odds
    "odds_home", "odds_draw", "odds_away",
    "implied_prob_home", "implied_prob_draw", "implied_prob_away",
]


class PredictRequest(BaseModel):
    """Input: a dictionary mapping feature names to numeric values."""
    features: dict[str, float] = Field(
        ...,
        description="Dictionary of feature name -> numeric value. All 72 features are required.",
        json_schema_extra={
            "example": {f: 0.0 for f in REQUIRED_FEATURES[:5]},
        },
    )


class Probability(BaseModel):
    home_win: float = Field(..., description="Probability of home win")
    draw: float = Field(..., description="Probability of draw")
    away_win: float = Field(..., description="Probability of away win")


class PredictResponse(BaseModel):
    prediction: str = Field(..., description="Predicted result: H (home win), D (draw), or A (away win)")
    probabilities: Probability
    model_name: str = Field(..., description="Name of the model used")
    model_version: str = Field(..., description="Model version from MLflow registry")


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model_name: str
    model_version: str
