"""
ml/register_models.py
=====================
One-shot script: loads locally-trained joblib models and registers them to
the MLflow Model Registry on the cupcast MLflow VM.

Run locally (from your laptop, with firewalled MLflow access):
    conda run -n ml python ml/register_models.py

What it does:
  1. Connects to MLflow tracking server via MLFLOW_TRACKING_URI env var
  2. For each of the 3 local joblib models:
       a. Starts a run in the matching experiment (must already exist)
       b. Logs the model as the appropriate flavor (sklearn / xgboost)
       c. Registers as a versioned model in the registry
       d. Tags v1 with an 'prod' alias (MLflow 3.x replacement for stages)
  3. Prints the resolved GCS artifact URI for each prod version
     (informational — backend loads via `models:/<name>@prod`, so the URIs
     don't need to be copied anywhere; they're shown for debugging).

Retraining workflow (once v2+ exist):
  - Register new version from the training run
  - Flip alias: `mlflow models set-alias -n <name> -a prod -v <new_version>`
  - Call `POST /admin/models/reload` on the backend to invalidate its cache
  No redeploy, no secret edits.

This script is idempotent-ish: re-running will create new runs and new
model versions (v2, v3, ...) but won't duplicate experiments. Use the
MLflow UI to prune old versions if needed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import joblib
import mlflow
from mlflow.tracking import MlflowClient
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://34.71.173.114:5000")
REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "ml" / "models"

# (joblib filename, experiment name, registered model name)
MODELS = [
    ("cupcast-club-model_best.joblib", "cupcast-club", "cupcast-club-model"),
    ("cupcast-club-top5_best.joblib", "cupcast-club-top5", "cupcast-club-top5-model"),
    ("cupcast-international-model_best.joblib", "cupcast-international", "cupcast-international-model"),
]


def log_and_register(joblib_path: Path, experiment_name: str, model_name: str) -> str:
    """Log a local joblib as an MLflow model, register it, and alias 'prod'.

    Returns the GCS artifact URI of the new version — used to configure
    Cloud Run's direct-from-GCS loader.
    """
    model = joblib.load(joblib_path)
    print(f"\n=== {model_name} ===")
    print(f"  source: {joblib_path}")
    print(f"  class:  {type(model).__name__}")

    mlflow.set_experiment(experiment_name)

    with mlflow.start_run(run_name=f"bootstrap-{model_name}") as run:
        # Tag this run as the seed/bootstrap import so future retraining
        # scripts can tell these apart from real training runs.
        mlflow.set_tag("source", "bootstrap_import")
        mlflow.set_tag("origin_file", joblib_path.name)

        # Pick flavor based on actual model class. Avoids losing native
        # XGBoost booster serialization by round-tripping through sklearn.
        if isinstance(model, XGBClassifier):
            mlflow.xgboost.log_model(model, artifact_path="model", registered_model_name=model_name)
        elif isinstance(model, RandomForestClassifier):
            mlflow.sklearn.log_model(model, artifact_path="model", registered_model_name=model_name)
        else:
            raise TypeError(f"Unsupported model class {type(model).__name__}")

        run_id = run.info.run_id
        print(f"  run_id: {run_id}")

    # Find the version just created (always the highest number for this model)
    client = MlflowClient()
    versions = client.search_model_versions(f"name='{model_name}'")
    latest = max(versions, key=lambda v: int(v.version))
    print(f"  version: v{latest.version}")

    # MLflow 3.x: stages are deprecated in favor of aliases. 'prod' plays the
    # same role as the old 'Production' stage but is explicit and lower-cased.
    client.set_registered_model_alias(name=model_name, alias="prod", version=latest.version)
    print(f"  alias:   prod -> v{latest.version}")

    # Resolve the concrete gs:// URI via the logged_models API. We can't use
    # `latest.source` directly because in MLflow 3.x it returns an internal
    # 'models:/m-<id>' handle; Cloud Run needs a real gs:// path because it
    # can't reach the tracking server (VM firewalled to admin IP).
    source_handle = latest.source  # e.g. 'models:/m-ecf84d5c55d7...'
    if source_handle.startswith("models:/m-"):
        model_id = source_handle.removeprefix("models:/")
        logged_model = client.get_logged_model(model_id)
        gcs_uri = logged_model.artifact_location
    else:
        gcs_uri = source_handle
    print(f"  gcs uri: {gcs_uri}")
    return gcs_uri


def main() -> int:
    print(f"Tracking URI: {TRACKING_URI}")
    mlflow.set_tracking_uri(TRACKING_URI)

    # Sanity check — each model file must exist before we touch MLflow
    missing = [f for f, _, _ in MODELS if not (MODELS_DIR / f).exists()]
    if missing:
        print(f"ERROR: missing joblib files: {missing}", file=sys.stderr)
        return 1

    results: list[tuple[str, str]] = []
    for joblib_name, exp_name, model_name in MODELS:
        uri = log_and_register(MODELS_DIR / joblib_name, exp_name, model_name)
        results.append((model_name, uri))

    # Print resolved artifact URIs for debugging. Backend loads via
    # models:/<name>@prod, so these don't need to be copied anywhere.
    print("\n" + "=" * 60)
    print("Registered models (backend loads via models:/<name>@prod):")
    print("=" * 60)
    for name, uri in results:
        print(f"  {name} → {uri}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
