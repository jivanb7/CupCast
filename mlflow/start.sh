#!/bin/sh
# Start the MLFlow tracking server.
# Env vars expected:
#   MLFLOW_BACKEND_STORE_URI  — PostgreSQL connection string
#   MLFLOW_DEFAULT_ARTIFACT_ROOT — artifact storage path (local volume or GCS)

exec mlflow server \
  --host 0.0.0.0 \
  --port 5000 \
  --backend-store-uri "${MLFLOW_BACKEND_STORE_URI}" \
  --default-artifact-root "${MLFLOW_DEFAULT_ARTIFACT_ROOT}" \
  --serve-artifacts
