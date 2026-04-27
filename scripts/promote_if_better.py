"""
scripts/promote_if_better.py
==============================
Metrics-gated promotion of a freshly-trained MLflow run to the `@prod` alias.

Why this exists
---------------
`ml/train_remote.py` logs each training run's best model as an artifact on
its run, but it does NOT register to the MLflow Model Registry and it does
NOT flip the `@prod` alias. That's intentional — training is cheap to run,
promotion is what changes what the backend serves.

This script closes the loop safely:
  1. Find the most-recent training run in the target experiment that actually
     logged a "model" artifact.
  2. Register it as a new version of the registered model (creating v2, v3, …).
  3. Look up `val_log_loss` on the new version's source run and on the
     currently-aliased `@prod` version's source run.
  4. If new val_log_loss is lower than current * (1 - MARGIN), flip `@prod`
     to the new version. Otherwise leave `@prod` alone.

`val_log_loss` is the primary gating metric because log-loss penalises
mis-calibrated confidence, which is what actually hurts our value-pick output.

Run locally:
  MLFLOW_TRACKING_URI=... MLFLOW_TRACKING_USERNAME=... MLFLOW_TRACKING_PASSWORD=... \
    python scripts/promote_if_better.py --model-type club

Run in CI: the weekly retrain workflow sets the env vars from repo secrets.

Exit codes
  0 — promoted, OR not promoted but the decision was safe (new model worse
      or tied). CI treats both as success.
  2 — no training runs found in the experiment, or no model artifact on
      the latest run. Worth a failing CI to investigate.
  3 — tracking / registry API call failed unexpectedly.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

import mlflow
from mlflow.tracking import MlflowClient

logger = logging.getLogger(__name__)

# Map --model-type → (experiment name, registered model name). Mirrors the
# triples in ml/register_models.py so retraining plugs into the same registry
# entries the backend already loads via `models:/<name>@prod`.
MODEL_TYPES = {
    "club": ("cupcast-club", "cupcast-club-model"),
    "intl": ("cupcast-international", "cupcast-international-model"),
}

# Default margin: new model's val_log_loss must be at least 1 % lower than
# current @prod's to justify swapping. Tight enough to prevent churn from
# stochastic training noise, loose enough that genuine improvements promote.
DEFAULT_MARGIN = 0.01

# Default gating metric. The training pipeline logs `val_log_loss` for every
# model flavor; picking this metric means we gate on the same quantity used
# to select the best flavor in training.
DEFAULT_METRIC = "val_log_loss"


@dataclass
class PromotionDecision:
    promoted: bool
    reason: str
    new_version: Optional[int]
    new_metric: Optional[float]
    current_version: Optional[int]
    current_metric: Optional[float]
    new_run_id: Optional[str] = None
    new_run_metrics: Optional[dict] = None
    db_label: Optional[str] = None  # set after _record_promotion_in_db


# Map MLflow model-type → backend model_registry.model_name. Keep these
# string keys in sync with backend/api/model_perf.py which queries by
# model_name = "club_model".
DB_MODEL_NAME_BY_TYPE = {
    "club": "club_model",
    "intl": "intl_model",
}


def _bump_version(current: Optional[str]) -> str:
    """v0.1.0-dev → v0.2.0;  v0.2.0 → v0.3.0;  None or unparseable → v0.2.0.

    Bumps minor, resets patch. Major stays at 0 until somebody intentionally
    cuts a v1.0.0 (e.g. when the model architecture changes meaningfully).
    """
    import re
    if not current or current == "v0.1.0-dev":
        return "v0.2.0"
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", current)
    if not m:
        return "v0.2.0"
    major, minor, _patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"v{major}.{minor + 1}.0"


def _human_arch_from_run_name(run_name: Optional[str]) -> str:
    """Map MLflow run name → short display label for the /model header.

    Lets the frontend show 'v0.2.0 · CatBoost' instead of 'v0.2.0'."""
    if not run_name:
        return ""
    rn = run_name.lower()
    if "catboost_team_id" in rn:
        return "CatBoost+Teams"
    if "stacked_ensemble" in rn or "stacked_poisson" in rn:
        return "Stacked"
    if "home_bias" in rn:
        return "XGB+HomeBias"
    if "calibrated" in rn:
        return "XGB+Calib"
    if "catboost" in rn:
        return "CatBoost"
    if "xgboost" in rn:
        return "XGBoost"
    if "lightgbm" in rn:
        return "LightGBM"
    if "random_forest" in rn:
        return "Random Forest"
    if "logistic" in rn:
        return "Logistic"
    if "mlp" in rn or "neural" in rn:
        return "Neural Net"
    if "hist_gradient" in rn or "hgb" in rn:
        return "HistGBT"
    return run_name  # unmapped — show raw


def _record_promotion_in_db(
    db_model_name: str,
    new_run_id: str,
    metrics: dict,
    arch_label: Optional[str] = None,
) -> Optional[str]:
    """Best-effort write to the model_registry DB table when the alias
    flips. Returns the bumped version label if the write succeeded, None
    otherwise. Failures here do NOT roll back the MLflow alias flip — the
    served model is the source of truth, the DB row is just metadata for
    the /model performance page header.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.warning("DATABASE_URL not set; skipping model_registry write")
        return None
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.begin() as conn:
            current = conn.execute(
                text(
                    "SELECT model_version FROM model_registry "
                    "WHERE model_name = :n AND is_production = TRUE "
                    "ORDER BY trained_at DESC NULLS LAST, id DESC LIMIT 1"
                ),
                {"n": db_model_name},
            ).first()
            # Strip any architecture suffix from the existing version before
            # bumping (e.g., 'v0.2.0-CatBoost' → 'v0.2.0').
            base_current = None
            if current and current[0]:
                base_current = current[0].split("-", 1)[0] if current[0] != "v0.1.0-dev" else "v0.1.0-dev"
            base_new = _bump_version(base_current)
            # Append the architecture so the /model header can render it.
            new_label = f"{base_new}-{arch_label}" if arch_label else base_new

            # Demote any prior production rows for this model_name.
            conn.execute(
                text("UPDATE model_registry SET is_production = FALSE WHERE model_name = :n"),
                {"n": db_model_name},
            )
            # Insert the new row.
            conn.execute(
                text(
                    """
                    INSERT INTO model_registry
                        (model_name, model_version, mlflow_run_id,
                         accuracy, f1_macro, log_loss,
                         is_production, trained_at)
                    VALUES
                        (:name, :ver, :run_id, :acc, :f1, :ll, TRUE, NOW())
                    """
                ),
                {
                    "name": db_model_name,
                    "ver": new_label,
                    "run_id": new_run_id,
                    "acc": metrics.get("val_accuracy"),
                    "f1": metrics.get("val_f1_macro"),
                    "ll": metrics.get("val_log_loss"),
                },
            )
        logger.info("Wrote model_registry row: %s = %s (run_id=%s)",
                    db_model_name, new_label, new_run_id[:8] if new_run_id else "?")
        return new_label
    except Exception:
        logger.exception("model_registry write failed (alias still flipped, served model is correct)")
        return None


def _find_latest_training_logged_model(client: MlflowClient, experiment_name: str):
    """Return the most-recent `logged model` entity attached to a FINISHED run
    in the experiment.

    MLflow 3.x separates a run's `logged model` artifact from its top-level
    run artifacts — `list_artifacts(run_id)` does not surface them, so the
    reliable way to find a recent training artifact is to search the logged-
    models index directly. Each `log_model()` call creates one; retraining
    is a fresh log_model, so the newest entry is our candidate.
    """
    exp = client.get_experiment_by_name(experiment_name)
    if exp is None:
        raise RuntimeError(f"Experiment '{experiment_name}' not found on tracking server")

    # search_logged_models is available on MlflowClient in mlflow>=3.0.
    try:
        logged = client.search_logged_models(
            experiment_ids=[exp.experiment_id],
            max_results=25,
        )
    except AttributeError as e:
        raise RuntimeError(
            "MlflowClient.search_logged_models is unavailable — upgrade mlflow>=3.0 "
            f"or switch the gate to runs:/<run_id>/model (root cause: {e})"
        ) from e

    # Sort newest-first ourselves so we don't depend on server-side ordering.
    logged_sorted = sorted(
        logged,
        key=lambda lm: getattr(lm, "creation_timestamp", 0) or 0,
        reverse=True,
    )
    for lm in logged_sorted:
        run_id = getattr(lm, "source_run_id", None) or getattr(lm, "run_id", None)
        if not run_id:
            continue
        try:
            run = client.get_run(run_id)
        except Exception:
            continue
        if run.info.status != "FINISHED":
            continue
        return lm, run
    return None, None


def _register_logged_model_as_new_version(
    client: MlflowClient, logged_model, run_id: str, model_name: str
) -> int:
    """Register a logged-model entity as a new registry version.

    MLflow 3.x logged-model URIs look like `models:/m-<hex>` — use the
    entity's own `model_uri` when available, else synthesize one. We pass
    run_id so the registry keeps the back-reference for audit.
    """
    source = getattr(logged_model, "model_uri", None)
    if not source:
        model_id = getattr(logged_model, "model_id", None) or getattr(logged_model, "id", None)
        if not model_id:
            raise RuntimeError(
                f"Cannot derive model_uri for logged model {logged_model!r}; "
                "cannot register a new version."
            )
        source = f"models:/{model_id}"
    mv = client.create_model_version(name=model_name, source=source, run_id=run_id)
    return int(mv.version)


def _metric_for_version(client: MlflowClient, model_name: str, version: int, metric: str) -> Optional[float]:
    """Fetch `metric` from the source run of a given model version. Returns
    None if the version, its source run, or the metric is missing — callers
    decide how to handle that.
    """
    try:
        mv = client.get_model_version(name=model_name, version=str(version))
    except Exception:
        return None
    run_id = mv.run_id
    if not run_id:
        return None
    try:
        run = client.get_run(run_id)
    except Exception:
        return None
    return run.data.metrics.get(metric)


def decide_and_promote(
    model_type: str,
    metric: str = DEFAULT_METRIC,
    margin: float = DEFAULT_MARGIN,
    dry_run: bool = False,
) -> PromotionDecision:
    if model_type not in MODEL_TYPES:
        raise ValueError(f"model_type must be one of {list(MODEL_TYPES)}")
    experiment_name, model_name = MODEL_TYPES[model_type]

    client = MlflowClient()

    # 1. Find latest training run's logged model.
    logged_model, latest_run = _find_latest_training_logged_model(client, experiment_name)
    if logged_model is None or latest_run is None:
        raise RuntimeError(
            f"No finished training runs with a logged model found in experiment {experiment_name!r}."
        )

    # 2. Register it as a new version — even if it's a regression. Having
    # every training run in the registry as an explicit version makes audit
    # and rollback cheap (`mlflow models set-alias prod <N-1>`).
    if dry_run:
        new_version = -1
        logger.info(
            "[dry-run] would register logged model from run %s as new version of %s",
            latest_run.info.run_id, model_name,
        )
    else:
        new_version = _register_logged_model_as_new_version(
            client, logged_model, latest_run.info.run_id, model_name
        )
        logger.info("Registered run %s as %s v%d", latest_run.info.run_id, model_name, new_version)

    # 3. Look up metrics on new version + current @prod.
    if dry_run:
        new_metric = latest_run.data.metrics.get(metric)
    else:
        new_metric = _metric_for_version(client, model_name, new_version, metric)
    if new_metric is None:
        raise RuntimeError(
            f"New version of {model_name} is missing metric {metric!r}; cannot gate safely."
        )

    try:
        prod = client.get_model_version_by_alias(name=model_name, alias="prod")
        current_version = int(prod.version)
        current_metric = _metric_for_version(client, model_name, current_version, metric)
    except Exception:
        # No @prod alias yet. First version to register gets promoted
        # unconditionally — there's nothing to compare against.
        current_version = None
        current_metric = None

    # 4. Decide.
    new_run_id = latest_run.info.run_id
    new_run_metrics = dict(latest_run.data.metrics)
    new_run_name = latest_run.data.tags.get("mlflow.runName") if latest_run.data.tags else None
    arch_label = _human_arch_from_run_name(new_run_name)
    db_model_name = DB_MODEL_NAME_BY_TYPE.get(model_type)

    def _build_decision(promoted: bool, reason: str) -> PromotionDecision:
        db_label = None
        if promoted and not dry_run and db_model_name:
            db_label = _record_promotion_in_db(
                db_model_name, new_run_id, new_run_metrics, arch_label=arch_label,
            )
        return PromotionDecision(
            promoted, reason, new_version, new_metric,
            current_version, current_metric,
            new_run_id=new_run_id, new_run_metrics=new_run_metrics, db_label=db_label,
        )

    if current_metric is None:
        reason = f"no existing @prod alias — promoting v{new_version} as first prod"
        if not dry_run:
            client.set_registered_model_alias(name=model_name, alias="prod", version=str(new_version))
        return _build_decision(True, reason)

    # Lower log-loss is better. Require new <= current * (1 - margin).
    threshold = current_metric * (1.0 - margin)
    if new_metric <= threshold:
        reason = (
            f"new {metric}={new_metric:.4f} ≤ {threshold:.4f} "
            f"(current={current_metric:.4f}, margin={margin:.1%}) — promoting"
        )
        if not dry_run:
            client.set_registered_model_alias(name=model_name, alias="prod", version=str(new_version))
        return _build_decision(True, reason)

    reason = (
        f"new {metric}={new_metric:.4f} > {threshold:.4f} "
        f"(current={current_metric:.4f}, margin={margin:.1%}) — keeping @prod=v{current_version}"
    )
    return _build_decision(False, reason)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-type", required=True, choices=list(MODEL_TYPES))
    parser.add_argument("--metric", default=DEFAULT_METRIC,
                        help="metric logged on the training run; lower-is-better (default: val_log_loss)")
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN,
                        help="required relative improvement (default: 0.01 = 1%%)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the decision without registering or flipping alias")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")

    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        logger.error("MLFLOW_TRACKING_URI is not set")
        return 3
    mlflow.set_tracking_uri(uri)

    try:
        decision = decide_and_promote(
            model_type=args.model_type,
            metric=args.metric,
            margin=args.margin,
            dry_run=args.dry_run,
        )
    except RuntimeError as e:
        logger.error("promotion gate failed: %s", e)
        return 2
    except Exception as e:
        logger.exception("unexpected error in promotion gate: %s", e)
        return 3

    tag = "PROMOTED" if decision.promoted else "KEPT"
    logger.info("[%s] %s", tag, decision.reason)
    if decision.promoted and decision.db_label:
        logger.info("model_registry now serves %s as %s", args.model_type, decision.db_label)
    # Emit a concise machine-readable summary for CI log searchability.
    print(
        f"promotion_result model={args.model_type} "
        f"promoted={decision.promoted} "
        f"new_version={decision.new_version} new_{args.metric}={decision.new_metric} "
        f"current_version={decision.current_version} current_{args.metric}={decision.current_metric} "
        f"db_label={decision.db_label or 'none'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
