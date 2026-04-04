# CupCast — ML Football Prediction Service

Predicts football match outcomes (Home Win / Draw / Away Win) using an XGBoost model trained on 15+ years of club league data across 9 European leagues.

## Architecture

- **Model**: XGBoost classifier trained on 72 features (rolling form, head-to-head, bookmaker odds)
- **Registry**: Model registered in MLflow Model Registry (`cupcast-club-model` v1) on GCP Compute Engine
- **API**: FastAPI service with Pydantic validation
- **Container**: Docker image published to Docker Hub

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Welcome message and endpoint listing |
| GET | `/health` | Health check — confirms model is loaded |
| POST | `/predict` | Accepts match features, returns prediction |
| GET | `/docs` | Interactive Swagger UI documentation |

## Run Locally (without Docker)

```bash
# Install uv (https://docs.astral.sh/uv/getting-started/installation/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv pip install -r requirements.txt

# Set MLflow tracking URI (optional — falls back to local model file)
export MLFLOW_TRACKING_URI=http://34.58.128.38:5000

# Start the API
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

## Build and Run with Docker

```bash
# Build the image
docker build -t cupcast-api .

# Run the container
docker run -p 8000:8000 cupcast-api
```

The API will be available at `http://localhost:8000`.

## Example `/predict` Request

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "features": {
      "home_win_rate_5": 0.6,
      "home_draw_rate_5": 0.2,
      "home_loss_rate_5": 0.2,
      "home_goals_scored_avg_5": 1.8,
      "home_goals_conceded_avg_5": 0.8,
      "home_goal_diff_avg_5": 1.0,
      "home_points_per_game_5": 2.0,
      "home_win_rate_10": 0.5,
      "home_draw_rate_10": 0.3,
      "home_loss_rate_10": 0.2,
      "home_goals_scored_avg_10": 1.5,
      "home_goals_conceded_avg_10": 0.9,
      "home_goal_diff_avg_10": 0.6,
      "home_points_per_game_10": 1.8,
      "home_clean_sheets_pct_10": 0.3,
      "home_failed_to_score_pct_10": 0.1,
      "home_home_win_rate_5": 0.8,
      "home_home_goals_scored_avg_5": 2.2,
      "home_home_goals_conceded_avg_5": 0.6,
      "home_shots_avg_5": 14.0,
      "home_shots_on_target_avg_5": 5.5,
      "home_shot_accuracy_5": 0.39,
      "home_corners_avg_5": 6.0,
      "home_yellow_cards_avg_5": 1.5,
      "away_win_rate_5": 0.4,
      "away_draw_rate_5": 0.2,
      "away_loss_rate_5": 0.4,
      "away_goals_scored_avg_5": 1.2,
      "away_goals_conceded_avg_5": 1.4,
      "away_goal_diff_avg_5": -0.2,
      "away_points_per_game_5": 1.4,
      "away_win_rate_10": 0.4,
      "away_draw_rate_10": 0.2,
      "away_loss_rate_10": 0.4,
      "away_goals_scored_avg_10": 1.1,
      "away_goals_conceded_avg_10": 1.3,
      "away_goal_diff_avg_10": -0.2,
      "away_points_per_game_10": 1.4,
      "away_clean_sheets_pct_10": 0.2,
      "away_failed_to_score_pct_10": 0.2,
      "away_away_win_rate_5": 0.2,
      "away_away_goals_scored_avg_5": 0.8,
      "away_away_goals_conceded_avg_5": 1.6,
      "away_shots_avg_5": 11.0,
      "away_shots_on_target_avg_5": 4.0,
      "away_shot_accuracy_5": 0.36,
      "away_corners_avg_5": 4.5,
      "away_yellow_cards_avg_5": 2.0,
      "h2h_home_wins": 3,
      "h2h_draws": 1,
      "h2h_away_wins": 1,
      "h2h_home_goals_avg": 1.8,
      "h2h_away_goals_avg": 0.8,
      "days_since_last_match_home": 7,
      "days_since_last_match_away": 4,
      "rest_advantage": 3,
      "season_stage": 0.7,
      "is_derby": 0,
      "is_covid_era": 0,
      "is_new_team_home": 0,
      "is_new_team_away": 0,
      "form_diff_goals_scored": 0.6,
      "form_diff_goals_conceded": -0.6,
      "form_diff_points": 0.6,
      "attack_vs_defense": 1.38,
      "defense_vs_attack": 0.67,
      "odds_home": 1.85,
      "odds_draw": 3.4,
      "odds_away": 4.5,
      "implied_prob_home": 0.54,
      "implied_prob_draw": 0.29,
      "implied_prob_away": 0.22
    }
  }'
```

**Expected output format:**

```json
{
  "prediction": "H",
  "probabilities": {
    "home_win": 0.5523,
    "draw": 0.2641,
    "away_win": 0.1836
  },
  "model_name": "cupcast-club-model",
  "model_version": "1"
}
```

## MLflow Tracking

- **Server**: `http://34.58.128.38:5000` (GCP Compute Engine VM)
- **Experiment**: `cupcast-club`
- **Registered Model**: `cupcast-club-model` (version 1, XGBoost with Optuna tuning)

## Project Structure

```
saas/
├── api/
│   ├── main.py          # FastAPI endpoints (/, /health, /predict)
│   ├── model.py         # Model loading from MLflow / local fallback
│   └── schemas.py       # Pydantic request/response models
├── ml/
│   ├── train_remote.py  # Training script (logs to remote MLflow)
│   ├── run_pipeline.py  # Data pipeline orchestrator
│   ├── src/             # ML pipeline (ingestion, processing, features)
│   ├── data/            # Training data (gitignored)
│   └── models/          # Saved models (gitignored)
├── Dockerfile
├── requirements.txt
└── README.md
```
