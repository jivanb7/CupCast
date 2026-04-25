---
date: 2026-04-24
type: runbook
status: live
tags: [cupcast, production, ops, runbook]
---

# Production Runbook

> [!info] Topology
> Frontend (Cloud Run) → Backend (Cloud Run) → Supabase Postgres + MLflow VM (sslip.io + Caddy basic auth) + GCS artifacts

## Service URLs

| Surface | URL |
|---|---|
| Frontend | https://cupcast-frontend-dlotj2g4dq-uw.a.run.app |
| Backend | https://cupcast-backend-dlotj2g4dq-uw.a.run.app |
| API root | `/api/v1/...` |
| FastAPI Swagger | `/docs` |
| Health (data quality) | `/api/v1/admin/health/scores` ← bookmark this |

## Project / region / DB

- **GCP project**: `sport-analyst-492223`
- **Region**: `us-west1`
- **DB**: Supabase Postgres (connection string in Cloud Run env `DATABASE_URL`)
- **MLflow**: `https://34-71-173-114.sslip.io` (sslip.io binds to the VM's external IP — survives IP changes if the URL pattern is updated)

## Deploy pipeline

`.github/workflows/deploy.yml` triggers on push to `main`:

```
1. Checkout + GCP auth
2. Configure Docker for Artifact Registry
3. Apply Alembic migrations to prod DB     ← ABORTS DEPLOY if fails
4. Build + push backend image
5. Build + push frontend image             ← ABORTS DEPLOY if fails
6. Capture previous backend revision
7. Deploy backend to Cloud Run
8. Deploy frontend to Cloud Run
9. Smoke test backend (real endpoints)     ← /matches/upcoming + /world-cup/overview + /world-cup/groups
10. Auto-rollback to previous revision     ← only fires if smoke fails
```

> [!warning] Migrations run BEFORE backend deploy
> By convention, migrations are additive-only — old code ignores new columns/tables, new code requires them present. Applying schema first is safe.

## Cloud Scheduler cron jobs (6 total)

```
cupcast-update-scores          0 */2 * * *   /api/v1/admin/scores/update
cupcast-refresh-odds           0 */4 * * *   /api/v1/admin/odds/refresh
cupcast-revalidate-scores      0 */6 * * *   /api/v1/admin/scores/revalidate?days=2  ← NEW (safety net)
cupcast-seed-fixtures          0 10 * * *    /api/v1/admin/fixtures/seed
cupcast-generate-predictions   30 10 * * *   /api/v1/admin/predictions/generate
cupcast-refresh-players        0 5 * * *     /api/v1/admin/players/refresh
```

To rebuild from scratch: `bash infra/gcp/scheduler.sh APPLY=1`

> [!important] Run order matters: predictions BEFORE odds
> Both endpoints upsert on `(match_id, model_version)`. If odds runs first, the next prediction generation wipes the value-pick flags. The cron schedule already has predictions earlier than odds.

## Score validation safety net

> [!success] Three independent failure modes must all happen for a wrong score to silently lock in now (~zero probability)

| Layer | What it catches |
|---|---|
| **Time guard** (`kickoff + 105min` normal, `+130min` cup) | Premature FINISHED from upstream |
| **6-hour re-check window** | Late corrections from upstream within window |
| **Daily cross-source revalidation** | Anything else, vs API-Football secondary source |
| **Manual one-shot script** | Catastrophic recovery — re-check arbitrary date ranges |

Run a manual revalidation:
```bash
cd /Users/jivanb/projects/ml-ops-project/saas/backend
DATABASE_URL='<prod url>' conda run -n ml python scripts/revalidate_recent_scores.py --days 7
```

Or via admin API:
```bash
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" \
  "https://cupcast-backend-dlotj2g4dq-uw.a.run.app/api/v1/admin/scores/revalidate?days=2"
```

## Health monitoring

### `/api/v1/admin/health/scores` — bookmark this

```json
{
  "status": "ok" | "warn" | "error",
  "last_revalidation": {...} | null,
  "corrections_last_24h": 0,
  "corrections_last_7d": 0,
  "stale_completed_matches": 0,
  "checked_at": "ISO"
}
```

| Status | What to do |
|---|---|
| `ok` (corrections 0–5/24h, last_revalidation < 12h) | Nothing |
| `warn` (5–15 corrections, OR last_revalidation > 12h) | Look at logs, probably fine |
| `error` (>15 corrections, OR no revalidation in 24h) | Upstream incident — investigate |

> [!note] Known false-positive on fresh deploys
> Health endpoint shows `error` until the first cron-driven revalidation runs (every 6h). Will resolve on its own.

## Manual ops cheat-sheet

```bash
# Health check production endpoints
curl https://cupcast-backend-dlotj2g4dq-uw.a.run.app/api/v1/world-cup/overview

# Trigger predictions manually (after fixture seed)
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" \
  https://cupcast-backend-dlotj2g4dq-uw.a.run.app/api/v1/admin/predictions/generate

# Trigger odds backfill (must run AFTER predictions)
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" \
  https://cupcast-backend-dlotj2g4dq-uw.a.run.app/api/v1/admin/odds/refresh

# Run Monte Carlo simulation (10k sims, ~4s)
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" \
  "https://cupcast-backend-dlotj2g4dq-uw.a.run.app/api/v1/admin/world-cup/run-simulation?n_sims=10000"

# Get tail of backend logs (errors only)
gcloud logging read "resource.type=cloud_run_revision AND \
  resource.labels.service_name=cupcast-backend AND severity>=ERROR" \
  --project=sport-analyst-492223 --limit=20

# Roll back to previous Cloud Run revision (manual emergency)
PREV=$(gcloud run revisions list --service=cupcast-backend \
  --region=us-west1 --limit=2 --format='value(name)' | tail -1)
gcloud run services update-traffic cupcast-backend --region=us-west1 \
  --to-revisions=$PREV=100
```

## Local dev startup (matches prod env loading)

```bash
cd /Users/jivanb/projects/ml-ops-project/saas
# Backend (loads MLFLOW_* + ADMIN_API_KEY from .env)
conda run -n ml uvicorn --env-file .env --app-dir backend main:app --reload

# Frontend (Vite hot-reload)
cd frontend && npm run dev   # → http://localhost:3000
```

## Production operations the user has access to

- **Cloud Run console**: services, revisions, traffic split, env vars, logs
- **Cloud Scheduler console**: 6 cron jobs (pause/run-now/edit)
- **Supabase dashboard**: connection strings, table editor, query editor
- **GCP Logging**: structured logs with severity filters
