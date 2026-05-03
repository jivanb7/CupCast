# Development & Setup Guide

This is the technical setup and development guide for CupCast. If you just want to know what the project is, head back to the [README](README.md).

## Table of contents

- [Prerequisites](#prerequisites)
- [Repository layout](#repository-layout)
- [Environment variables](#environment-variables)
- [Local development — backend](#local-development--backend)
- [Local development — frontend](#local-development--frontend)
- [Running the test suite](#running-the-test-suite)
- [Working with Docker](#working-with-docker)
- [Database migrations](#database-migrations)
- [ML training pipeline](#ml-training-pipeline)
- [Cloud infrastructure](#cloud-infrastructure)
- [Cron jobs](#cron-jobs)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

## Prerequisites

You'll need:

- **Python 3.11**
- **Node.js 20+** and **npm** (for the frontend)
- **Docker** (optional, only if you want to build container images locally)
- **gcloud CLI** (optional, only if you'll deploy to GCP)
- A **Postgres database** — either local for development, or a Supabase project for staging/production
- An **MLflow tracking server** (we run one on a GCP Compute Engine VM, but a local instance works fine for development)

The team also uses a `conda` environment named `ml` for Python work. If you prefer `venv` or `uv`, those work too.

## Repository layout

```
saas/
├── backend/              FastAPI app (eight routers, services layer, schemas)
├── frontend/             React + Vite app (Tailwind, served via Nginx)
├── ml/                   Training pipeline, feature engineering, evaluation
├── mlops/                MLflow utilities, validation scripts
├── infra/                GCP infrastructure scripts (Cloud Scheduler, Cloud Run)
├── scripts/              Operational scripts (promotion gate, data refresh)
├── tests/                Backend integration tests
├── docs/                 Architecture and runbook documentation
├── demo/                 Demo GIF used in the main README
├── .github/workflows/    CI, Deploy, and Data Refresh GitHub Actions
└── README.md
```

## Environment variables

CupCast reads configuration from environment variables. For local development, copy `.env.example` to `.env` and fill in the values.

| Variable | Description |
|---|---|
| `DATABASE_URL` | Postgres connection string. For Supabase, use the connection pooler URL |
| `MLFLOW_TRACKING_URI` | URL of your MLflow tracking server |
| `MLFLOW_TRACKING_USERNAME` | Basic auth username (if your MLflow is protected) |
| `MLFLOW_TRACKING_PASSWORD` | Basic auth password |
| `ADMIN_API_KEY` | Random token that protects `/api/v1/admin/*` endpoints |
| `API_FOOTBALL_KEYS` | API key for the live data provider |
| `FOOTBALL_DATA_ORG_API_KEY` | API key for fixture seeding |
| `GCP_PROJECT_ID` | Your GCP project ID (only needed in production) |
| `GCS_BUCKET` | Bucket holding model artifacts (only needed in production) |
| `ENABLE_SCHEDULER` | Set to `false` in production (Cloud Scheduler handles cron) |

For production, these are set as Cloud Run service environment variables by the Deploy workflow. For local development, export them in your shell or load them from `.env`.

## Local development — backend

```bash
# 1. Activate your Python env (we use conda named "ml")
conda activate ml

# 2. Install backend dependencies
cd backend
pip install -r requirements.txt

# 3. Configure your environment
cp ../.env.example ../.env
# Open .env and fill in DATABASE_URL, MLFLOW_TRACKING_URI, etc.

# 4. Run database migrations
alembic upgrade head

# 5. Start the API
uvicorn --env-file ../.env --app-dir . main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be live at `http://localhost:8000`. Interactive Swagger docs are at `http://localhost:8000/docs`.

### Backend health check

```bash
curl http://localhost:8000/health
# {"status":"ok","database":"connected"}
```

### Useful endpoints

The backend exposes eight routers under `/api/v1/`:

- `/predictions` — model probabilities for upcoming matches
- `/matches` — match listings, results, and detail pages
- `/value-picks` — flagged high-conviction calls
- `/model-perf` — live model performance, rolling accuracy, per-league breakdown
- `/world-cup` — group standings, bracket projections, simulation results
- `/teams` — team metadata and form
- `/leagues` — league listings and standings
- `/admin` — protected administrative endpoints (require `ADMIN_API_KEY`)

Full route listing is at `/openapi.json` once the server is running.

## Local development — frontend

```bash
cd frontend
npm install

# Point the frontend at your local backend
echo "VITE_API_URL=http://localhost:8000" > .env

npm run dev
```

The frontend will be live at `http://localhost:5173`. It hot-reloads on file changes.

To build the production bundle:

```bash
npm run build
npm run preview     # serves the production build locally for testing
```

## Running the test suite

Backend tests use pytest and run against an in-memory SQLite database, so they don't need your real `DATABASE_URL`:

```bash
# From the repo root
PYTHONPATH=. pytest tests/ -v

# ML pipeline tests
PYTHONPATH=. pytest ml/tests/ -v
```

CI runs both suites on every push.

## Working with Docker

The backend has a Dockerfile at `backend/Dockerfile`. The build context is the repo root so the Dockerfile can `COPY ml/` alongside `backend/`:

```bash
# Build
docker build -f backend/Dockerfile -t cupcast-backend .

# Run
docker run \
  -e DATABASE_URL="postgresql://..." \
  -e MLFLOW_TRACKING_URI="https://your-mlflow-server" \
  -e MLFLOW_TRACKING_USERNAME="..." \
  -e MLFLOW_TRACKING_PASSWORD="..." \
  -p 8000:8000 \
  cupcast-backend
```

The frontend has its own Dockerfile at `frontend/Dockerfile`:

```bash
cd frontend
docker build --build-arg VITE_API_URL=http://localhost:8000 -t cupcast-frontend .
docker run -p 8080:8080 cupcast-frontend
```

## Database migrations

We use Alembic for schema migrations. Migrations are additive-only by convention so they can run while the old code is still serving traffic.

```bash
# See current revision
cd backend
alembic current

# See pending migrations
alembic heads

# Apply migrations
alembic upgrade head

# Generate a new migration after editing models
alembic revision --autogenerate -m "describe your change"
```

In production, migrations run automatically before each Cloud Run deploy.

## ML training pipeline

The training entrypoint is `ml/train_remote.py`. It:

1. Loads features from a parquet file
2. Splits chronologically into train, validation, and test sets
3. Runs Optuna hyperparameter search across multiple model strategies (XGBoost, CatBoost, calibrated wrappers)
4. Logs every run to MLflow with parameters, metrics, feature importance, and the joblib artifact

To trigger a training run locally:

```bash
PYTHONPATH=. conda run -n ml python ml/train_remote.py --model-type club --n-trials 10
```

To register the trained model and run the promotion gate:

```bash
PYTHONPATH=. conda run -n ml python scripts/promote_if_better.py --model-name cupcast-club-model
```

The promotion gate compares the new model's `val_log_loss` against the current `@prod` alias. The new model only wins if it improves on the champion's loss by at least 1%.

In production, this entire flow runs automatically every Monday at 05:00 UTC via the `Data Refresh` GitHub Actions workflow.

## Cloud infrastructure

CupCast runs on Google Cloud Platform.

| Service | Purpose |
|---|---|
| Cloud Run (`cupcast-backend`) | FastAPI backend, autoscale to zero |
| Cloud Run (`cupcast-frontend`) | React + Nginx frontend |
| Compute Engine (`mlflow-server`) | MLflow tracking server |
| Cloud SQL | (Not used. Database is on Supabase) |
| Cloud Scheduler | Eleven cron jobs orchestrating data refresh, predictions, and validation |
| Cloud Storage | MLflow artifact bucket |
| Artifact Registry | Versioned Docker images |
| Workload Identity Federation | Keyless GitHub Actions → GCP authentication |

GCP project ID is `sport-analyst-492223`. Region is `us-west1` for Cloud Run and Artifact Registry.

## Cron jobs

All eleven cron jobs are defined in `infra/gcp/scheduler.sh`. The script is idempotent — running it creates missing jobs and updates existing ones.

```bash
# Dry run (prints what would happen)
./infra/gcp/scheduler.sh

# Apply for real
APPLY=1 ./infra/gcp/scheduler.sh
```

Cron job summary:

| Job | Cadence | What it does |
|---|---|---|
| `cupcast-live-sync` | Every minute | Live score sync during matches |
| `cupcast-update-scores-fast` | Every 5 minutes | Fast ESPN-only score sweep |
| `cupcast-match-stats-sync` | Every 5 minutes | Match statistics sync |
| `cupcast-update-scores` | Every 2 hours | Full score sweep |
| `cupcast-refresh-odds` | Every 4 hours | Bookmaker odds + value picks refresh |
| `cupcast-revalidate-scores` | Every 6 hours | Cross-check completed scores |
| `cupcast-refresh-players` | Daily 05:00 UTC | Top scorers and injuries |
| `cupcast-seed-fixtures` | Daily 10:00 UTC | Upcoming fixture seeding |
| `cupcast-generate-predictions` | Daily 10:30 UTC | Batch inference for upcoming matches |
| `cupcast-refresh-explanations` | Daily 11:00 UTC | Per-match explanation backfill |
| `cupcast-run-wc-simulation` | Sunday 03:00 UTC | World Cup Monte Carlo simulation |

## Deployment

Deployment is fully automated. Every push to `main` triggers the `Deploy` GitHub Actions workflow.

The workflow:

1. Checks out the code
2. Authenticates to Google Cloud using Workload Identity Federation
3. Runs Alembic migrations against the production database
4. Builds Docker images for backend and frontend
5. Pushes images to Artifact Registry
6. Deploys to Cloud Run
7. Runs a smoke test against the new revision
8. Automatically rolls back if smoke fails

You don't need to run any deploy commands manually — push to `main` and the pipeline handles it.

To trigger a model retrain manually (without waiting for Monday's cron):

```bash
gh workflow run "Data Refresh" --ref main
```

## Troubleshooting

**Backend can't connect to the database**
Check that your `DATABASE_URL` is correct. For Supabase, make sure you're using the connection pooler URL (port 6543), not the direct database URL.

**MLflow client can't load the model**
Verify `MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_USERNAME`, and `MLFLOW_TRACKING_PASSWORD` are set. The client reads from `os.environ`, so make sure your `.env` is being exported into the shell or you're using the `--env-file` flag with uvicorn.

**Frontend shows a CORS error**
Set `VITE_API_URL` in `frontend/.env` to point at your backend, then rebuild. CORS is controlled by FastAPI middleware in `backend/main.py`.

**Cloud Scheduler jobs are firing but failing**
Check the Cloud Run logs for the `cupcast-backend` service. Most cron failures are admin auth issues — verify `ADMIN_API_KEY` matches between the Cloud Scheduler job and the backend env.

**Cron schedules drifting**
GitHub Actions cron is UTC-only and not DST-aware. The Monday 05:00 UTC retrain is 21:00 PST in winter and 22:00 PDT in summer. This is expected.

**Data Refresh workflow timing out**
The full retrain takes 30-60 minutes. The workflow timeout is set to 90 minutes. If it's exceeding that, you likely have a feature engineering bug. Re-run with `workflow_dispatch` and the `train-only` mode parameter to isolate.

## Where to read more in the repo

- `infra/gcp/scheduler.sh` — single source of truth for cron job definitions, with inline comments explaining each job
- `.github/workflows/deploy.yml` — single source of truth for the deploy pipeline, including migrations, smoke tests, and auto-rollback
- `docs/MODEL_FEATURE_RESEARCH.md` — feature engineering research notes
