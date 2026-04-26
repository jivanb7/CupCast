#!/usr/bin/env bash
# =============================================================================
# infra/gcp/scheduler.sh
# =============================================================================
# Cloud Scheduler job definitions for the CupCast backend.
#
# This file is the single source of truth for what cron jobs hit the prod
# Cloud Run service. Seven jobs in total:
#
#   1. cupcast-update-scores-fast  — every 5 min   — ESPN-only pass; closes the
#                                                    gap between a match ending
#                                                    and the final score showing
#                                                    on the site (was up to 2 h
#                                                    before this job existed —
#                                                    Real-Oviedo class of bug)
#   2. cupcast-update-scores       — every 2 h     — full pass: ESPN + CSV + live API
#   3. cupcast-refresh-odds        — every 4 h     — refreshes bookmaker odds + value picks
#   4. cupcast-seed-fixtures       — daily 10:00 UTC — seeds upcoming fixtures
#   5. cupcast-generate-predictions— daily 10:30 UTC — runs batch inference
#   6. cupcast-refresh-players     — daily 05:00 UTC — top-scorers + injuries
#   7. cupcast-revalidate-scores   — every 6 h     — cross-checks completed scores
#                                                    against API-Football and
#                                                    rewrites any silently-wrong
#                                                    final scores (Real-Betis bug)
#
# Usage:
#
#   # 1. Set required env vars
#   export ADMIN_API_KEY="..."     # value from .env / Secret Manager
#   export PROJECT_ID="sport-analyst-492223"
#   export REGION="us-west1"
#   export BACKEND_URL="https://cupcast-backend-dlotj2g4dq-uw.a.run.app"
#
#   # 2. Dry-run: print everything that WOULD happen
#   ./infra/gcp/scheduler.sh
#
#   # 3. Apply for real (creates missing jobs, updates existing ones)
#   APPLY=1 ./infra/gcp/scheduler.sh
#
# Idempotency:
#   Each job is checked with `gcloud scheduler jobs describe`. If it already
#   exists the script issues `gcloud scheduler jobs update http ...`; otherwise
#   it issues `gcloud scheduler jobs create http ...`. Re-running this script
#   is therefore safe and is the recommended way to roll out cron changes.
#
# Auditability:
#   When APPLY is unset (default), the script prints every gcloud command it
#   would run without executing anything. Useful for code review before a
#   schedule change goes live.
# =============================================================================

set -euo pipefail

: "${ADMIN_API_KEY:?ADMIN_API_KEY env var is required}"
PROJECT_ID="${PROJECT_ID:-sport-analyst-492223}"
REGION="${REGION:-us-west1}"
BACKEND_URL="${BACKEND_URL:-https://cupcast-backend-dlotj2g4dq-uw.a.run.app}"
APPLY="${APPLY:-}"

# Print + (optionally) execute. We print every command regardless so the
# operator has a reproducible log.
run() {
    echo "+ $*"
    if [[ -n "${APPLY}" ]]; then
        eval "$@"
    fi
}

# Create-or-update a Cloud Scheduler HTTP job. Idempotent.
#
# Args:
#   $1 = job name (e.g. cupcast-revalidate-scores)
#   $2 = cron schedule (e.g. "0 */6 * * *")
#   $3 = full URI (https://.../endpoint)
#   $4 = HTTP method (POST, GET, ...)
#   $5 = description
upsert_job() {
    local name="$1"
    local schedule="$2"
    local uri="$3"
    local method="$4"
    local description="$5"

    local exists=0
    if gcloud scheduler jobs describe "${name}" \
        --project="${PROJECT_ID}" \
        --location="${REGION}" \
        >/dev/null 2>&1; then
        exists=1
    fi

    local verb="create"
    if [[ "${exists}" -eq 1 ]]; then
        verb="update"
    fi

    # Always send the admin key header. GET/no-auth endpoints (the health
    # check) are not driven from cron, so every scheduled job here is admin.
    run gcloud scheduler jobs "${verb}" http "${name}" \
        --project="${PROJECT_ID}" \
        --location="${REGION}" \
        --schedule="'${schedule}'" \
        --uri="'${uri}'" \
        --http-method="${method}" \
        --headers="'X-Admin-Key=${ADMIN_API_KEY}'" \
        --time-zone='Etc/UTC' \
        --description="'${description}'"
}

echo "==============================================================="
echo "CupCast Cloud Scheduler — ${APPLY:+APPLY MODE}${APPLY:-DRY-RUN}"
echo "  project : ${PROJECT_ID}"
echo "  region  : ${REGION}"
echo "  backend : ${BACKEND_URL}"
echo "==============================================================="

# 1a. Fast ESPN-only score updates — every 5 min.
#     Closes the user-visible gap: a match that ends at 16:15 UTC used to
#     wait until the next 2-hourly tick (18:00 UTC) before the final score
#     replaced the pre-match prediction card. ESPN is keyless and has no
#     quota, so 5-min cadence is safe. The endpoint is idempotent — repeated
#     calls with unchanged scores are no-ops via an equality short-circuit.
upsert_job \
    "cupcast-update-scores-fast" \
    "*/5 * * * *" \
    "${BACKEND_URL}/api/v1/admin/scores/update?espn_only=true" \
    "POST" \
    "ESPN-only same-day score sweep — closes the post-match update gap."

# 1b. Full score sweep — every 2 h, covers football-data CSV + Football-Data.org
#     live API in addition to ESPN. Slower (~90 s) so kept on a longer cadence;
#     the 5-min ESPN job above handles same-day finals.
upsert_job \
    "cupcast-update-scores" \
    "0 */2 * * *" \
    "${BACKEND_URL}/api/v1/admin/scores/update" \
    "POST" \
    "Full score sweep (ESPN + football-data CSV + Football-Data.org)."

# 2. Odds refresh — every 4 h, recomputes value-pick edges
upsert_job \
    "cupcast-refresh-odds" \
    "0 */4 * * *" \
    "${BACKEND_URL}/api/v1/admin/odds/refresh" \
    "POST" \
    "Refresh bookmaker odds + value-pick flags across all leagues."

# 3. Fixture seed — once daily at 10:00 UTC, before predictions
upsert_job \
    "cupcast-seed-fixtures" \
    "0 10 * * *" \
    "${BACKEND_URL}/api/v1/admin/fixtures/seed" \
    "POST" \
    "Seed upcoming fixtures from Football-Data.org + fixtures.csv."

# 4. Prediction generation — 30 min after fixture seed
upsert_job \
    "cupcast-generate-predictions" \
    "30 10 * * *" \
    "${BACKEND_URL}/api/v1/admin/predictions/generate" \
    "POST" \
    "Run batch inference on upcoming matches and store predictions."

# 5. Player refresh — daily at 05:00 UTC (well before fixtures/predictions)
upsert_job \
    "cupcast-refresh-players" \
    "0 5 * * *" \
    "${BACKEND_URL}/api/v1/admin/players/refresh" \
    "POST" \
    "Refresh top scorers and injuries for all tracked leagues."

# 6. NEW — revalidate completed scores — every 6 h, looks back 2 days
#    Catches the Real-Betis-style bug where score_updater locked in an
#    intermediate score and never picked up the late equaliser. Each run
#    writes a row to score_corrections for every fix made. The /admin/
#    health/scores endpoint surfaces correction counts so we can spot
#    upstream regressions early.
upsert_job \
    "cupcast-revalidate-scores" \
    "0 */6 * * *" \
    "${BACKEND_URL}/api/v1/admin/scores/revalidate?days=2" \
    "POST" \
    "Cross-check the last 2 days of completed scores against API-Football."

echo
echo "Done."
echo
if [[ -z "${APPLY}" ]]; then
    echo "(dry-run — no jobs were created or modified)"
    echo "Re-run with APPLY=1 to execute the gcloud commands above."
fi
