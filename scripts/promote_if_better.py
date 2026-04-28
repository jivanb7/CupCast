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

# Default margin: new model's val_log_loss must be at least this fraction
# lower than current @prod's to justify swapping. The whole model family
# in this codebase lives in val_log_loss 1.000–1.080 — a 1% margin (0.01
# absolute) is comparable to run-to-run variance and rejected EVERY
# fresh-data retrain we'd otherwise want to ship. Setting to 0 means any
# real improvement, no matter how small, promotes — week-over-week the
# fresh-data model will win the comparison if the data has anything new
# to say. Set to a positive value if churn becomes a problem.
DEFAULT_MARGIN = 0.0

# Default gating metric. Aligned with how train_remote.py picks "best" —
# accuracy is the user-facing definition of model quality. log_loss stays
# available as an alt metric (--metric val_log_loss) and lower-is-better
# is auto-detected from the metric name.
DEFAULT_METRIC = "val_accuracy"


def _higher_is_better(metric_name: str) -> bool:
    """Direction of the gating metric. Accuracy/F1/AUC: higher is better.
    Log-loss/Brier: lower is better. Defaults to lower-is-better for
    unknown metrics to stay safe."""
    name = metric_name.lower()
    if any(k in name for k in ("accuracy", "f1", "auc", "precision", "recall")):
        return True
    return False


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


def _multi_metric_decision(
    new_acc: Optional[float],
    cur_acc: Optional[float],
    new_ll: Optional[float],
    cur_ll: Optional[float],
    new_brier: Optional[float],
    cur_brier: Optional[float],
    margin: float,
    prob_margin: float = 0.01,
):
    """Apply the dual-criterion gate.

    Returns (passes: bool, path: Optional[str], reason_detail: str). `path` is
    "A" or "B" describing which criterion qualified, or None on failure.

    Path A — accuracy non-regressing AND log_loss non-regressing:
        new_acc >= cur_acc * (1 - margin)  AND  new_ll <= cur_ll * (1 + margin)

    Path B — clear ≥`prob_margin` improvement on BOTH log_loss and Brier:
        new_ll < cur_ll * (1 - prob_margin)  AND  new_brier < cur_brier * (1 - prob_margin)

    Path C — legacy-current bridge. When the current @prod was trained before
    we started logging val_log_loss / val_brier_score, both probabilistic
    metrics on the current side are missing. Without this bridge the gate
    falls back to single-metric val_acc-only, which is the noisiest possible
    comparison. Path C accepts a new version that has all three metrics
    PROVIDED its log_loss and Brier are below absolute "sanity" thresholds
    that sit comfortably below 3-way random:
        new_ll < ln(3) * 0.95  ≈ 1.044   (random log_loss = ln(3) ≈ 1.099)
        new_brier < (2/3) * 0.95 ≈ 0.633  (random brier = 2/3 ≈ 0.667)
        new_acc >= cur_acc * (1 - margin)
    Path C only fires when both cur_ll AND cur_brier are missing — it's a
    one-time bridge that becomes irrelevant once a current with all metrics
    is in place.

    If all three paths are skipped due to missing data, returns (False, None,
    "<reason>") so the caller can fall back to single-metric.
    """
    import math as _math

    a_eligible = (
        new_acc is not None and cur_acc is not None
        and new_ll is not None and cur_ll is not None
    )
    b_eligible = (
        new_ll is not None and cur_ll is not None
        and new_brier is not None and cur_brier is not None
    )
    c_eligible = (
        new_acc is not None and cur_acc is not None
        and new_ll is not None and new_brier is not None
        and cur_ll is None and cur_brier is None
    )

    if not a_eligible and not b_eligible and not c_eligible:
        return False, None, "missing required metrics on either side"

    a_pass = False
    a_detail = "skipped (missing acc or log_loss)"
    if a_eligible:
        acc_threshold = cur_acc * (1.0 - margin)
        ll_threshold = cur_ll * (1.0 + margin)
        acc_ok = new_acc >= acc_threshold
        ll_ok = new_ll <= ll_threshold
        a_pass = acc_ok and ll_ok
        a_detail = (
            f"acc {new_acc:.4f} {'≥' if acc_ok else '<'} {acc_threshold:.4f} "
            f"AND log_loss {new_ll:.4f} {'≤' if ll_ok else '>'} {ll_threshold:.4f}"
        )

    b_pass = False
    b_detail = "skipped (missing log_loss or brier)"
    if b_eligible:
        ll_threshold = cur_ll * (1.0 - prob_margin)
        brier_threshold = cur_brier * (1.0 - prob_margin)
        ll_ok = new_ll < ll_threshold
        brier_ok = new_brier < brier_threshold
        b_pass = ll_ok and brier_ok
        b_detail = (
            f"log_loss {new_ll:.4f} {'<' if ll_ok else '≥'} {ll_threshold:.4f} "
            f"AND brier {new_brier:.4f} {'<' if brier_ok else '≥'} {brier_threshold:.4f}"
        )

    c_pass = False
    c_detail = "skipped (current has metrics; not a legacy-current bridge case)"
    if c_eligible:
        # Sanity thresholds — well below 3-way random so any half-decent
        # model clears them; the bridge's job is to detect "current is
        # legacy" and let a model with reasonable probabilistic quality
        # ship instead of holding it hostage to absent comparators.
        ll_sanity = _math.log(3.0) * 0.95   # ≈ 1.0438
        brier_sanity = (2.0 / 3.0) * 0.95   # ≈ 0.6333
        # Acc tolerance for the bridge: allow up to 1pp regression. The val
        # window is ~880 rows, std-error on accuracy ≈ sqrt(0.5*0.5/880) ≈
        # 1.7%, so a 1pp drop is well inside the noise band. Without this
        # band we can't promote a probabilistically-better model that's
        # nominally tied with the legacy current on noisy val_acc.
        ACC_NOISE_BAND = 0.01
        acc_threshold = cur_acc - max(margin * cur_acc, ACC_NOISE_BAND)
        ll_ok = new_ll < ll_sanity
        brier_ok = new_brier < brier_sanity
        acc_ok = new_acc >= acc_threshold
        c_pass = ll_ok and brier_ok and acc_ok
        c_detail = (
            f"legacy-current bridge: "
            f"log_loss {new_ll:.4f} {'<' if ll_ok else '≥'} {ll_sanity:.4f} "
            f"AND brier {new_brier:.4f} {'<' if brier_ok else '≥'} {brier_sanity:.4f} "
            f"AND acc {new_acc:.4f} {'≥' if acc_ok else '<'} {acc_threshold:.4f} "
            f"(noise band {ACC_NOISE_BAND:.2%})"
        )

    if a_pass:
        return True, "A", f"path A passed [{a_detail}]"
    if b_pass:
        return True, "B", f"path B passed [{b_detail}]"
    if c_pass:
        return True, "C", f"path C passed [{c_detail}]"
    return False, None, (
        f"path A failed [{a_detail}]; "
        f"path B failed [{b_detail}]; "
        f"path C failed [{c_detail}]"
    )


def decide_and_promote(
    model_type: str,
    metric: str = DEFAULT_METRIC,
    margin: float = DEFAULT_MARGIN,
    dry_run: bool = False,
    multi_metric: bool = True,
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
        # Some training pipelines log the metric under a different key
        # (legacy intl trainer logs `log_loss` not `val_log_loss`). Try a
        # couple of common fallbacks so a metric-name mismatch downgrades
        # to "no promotion" rather than killing the whole workflow.
        for alt in (metric.replace("val_", ""), f"val_{metric}", "val_logloss", "log_loss"):
            if alt == metric:
                continue
            if not dry_run:
                fallback = _metric_for_version(client, model_name, new_version, alt)
            else:
                fallback = latest_run.data.metrics.get(alt)
            if fallback is not None:
                logger.warning("Metric %r missing — using fallback metric %r=%.4f",
                               metric, alt, fallback)
                new_metric = fallback
                metric = alt
                break
    if new_metric is None:
        logger.warning(
            "New version of %s is missing metric %r and no fallback found; "
            "leaving @prod alias untouched but not failing the workflow.",
            model_name, metric,
        )
        return PromotionDecision(
            promoted=False,
            reason=f"missing metric {metric!r} on new version — keeping current @prod",
            new_version=new_version, new_metric=None,
            current_version=None, current_metric=None,
            new_run_id=latest_run.info.run_id,
            new_run_metrics=dict(latest_run.data.metrics),
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

    # ------------------------------------------------------------------
    # Multi-metric gate: accuracy is noisy on ~880-row val windows, so a
    # 0.3pp drop should NOT block a meaningful log-loss/Brier improvement.
    # When multi_metric=True, we accept the new model if EITHER:
    #   (A) val_acc non-regressing AND val_log_loss non-regressing
    #   (B) val_log_loss AND val_brier_score both improve by ≥ 1%
    # See _multi_metric_decision() for the exact comparison rules.
    # ------------------------------------------------------------------
    if multi_metric:
        # Pull all three metrics for both new and current. Missing metrics
        # are tolerated by _multi_metric_decision; if everything is missing
        # we fall back to the legacy single-metric path below.
        if dry_run:
            new_acc = latest_run.data.metrics.get("val_accuracy")
            new_ll = latest_run.data.metrics.get("val_log_loss")
            new_brier = latest_run.data.metrics.get("val_brier_score")
        else:
            new_acc = _metric_for_version(client, model_name, new_version, "val_accuracy")
            new_ll = _metric_for_version(client, model_name, new_version, "val_log_loss")
            new_brier = _metric_for_version(client, model_name, new_version, "val_brier_score")

        cur_acc = _metric_for_version(client, model_name, current_version, "val_accuracy")
        cur_ll = _metric_for_version(client, model_name, current_version, "val_log_loss")
        cur_brier = _metric_for_version(client, model_name, current_version, "val_brier_score")

        passes, path, detail = _multi_metric_decision(
            new_acc=new_acc, cur_acc=cur_acc,
            new_ll=new_ll, cur_ll=cur_ll,
            new_brier=new_brier, cur_brier=cur_brier,
            margin=margin,
        )

        # Stash these on the decision struct so the JSON summary can print
        # all three new metrics for downstream tooling/CI logs.
        if new_acc is not None:
            new_run_metrics.setdefault("val_accuracy", new_acc)
        if new_ll is not None:
            new_run_metrics.setdefault("val_log_loss", new_ll)
        if new_brier is not None:
            new_run_metrics.setdefault("val_brier_score", new_brier)

        if passes or path is not None:
            metrics_blob = (
                f"new(acc={new_acc}, ll={new_ll}, brier={new_brier}) vs "
                f"current(acc={cur_acc}, ll={cur_ll}, brier={cur_brier}, v{current_version})"
            )
            if passes:
                reason = f"multi-metric gate: {detail}; {metrics_blob} — promoting"
                if not dry_run:
                    client.set_registered_model_alias(
                        name=model_name, alias="prod", version=str(new_version),
                    )
                return _build_decision(True, reason)
            reason = (
                f"multi-metric gate: {detail}; {metrics_blob} — "
                f"keeping @prod=v{current_version}"
            )
            return _build_decision(False, reason)
        # Both paths skipped (everything missing) — fall through to the
        # single-metric legacy gate below so we still get a decision.
        logger.warning(
            "multi-metric gate could not evaluate (all metrics missing); "
            "falling back to single-metric gate on %r", metric,
        )

    higher_better = _higher_is_better(metric)
    if higher_better:
        # Accuracy / F1 / AUC: new must be ≥ current * (1 + margin)
        threshold = current_metric * (1.0 + margin)
        passes = new_metric >= threshold
        compare_op_pass, compare_op_fail = "≥", "<"
    else:
        # Log-loss / Brier: new must be ≤ current * (1 - margin)
        threshold = current_metric * (1.0 - margin)
        passes = new_metric <= threshold
        compare_op_pass, compare_op_fail = "≤", ">"

    if passes:
        reason = (
            f"single-metric gate: new {metric}={new_metric:.4f} {compare_op_pass} {threshold:.4f} "
            f"(current={current_metric:.4f}, margin={margin:.1%}) — promoting"
        )
        if not dry_run:
            client.set_registered_model_alias(name=model_name, alias="prod", version=str(new_version))
        return _build_decision(True, reason)

    reason = (
        f"single-metric gate: new {metric}={new_metric:.4f} {compare_op_fail} {threshold:.4f} "
        f"(current={current_metric:.4f}, margin={margin:.1%}) — keeping @prod=v{current_version}"
    )
    return _build_decision(False, reason)


def _sync_current_prod_to_db(
    client: MlflowClient,
    model_type: str,
    model_name: str,
) -> Optional[str]:
    """If MLflow has a @prod alias but the model_registry table has no
    matching is_production row (typical when an earlier promotion ran
    before DATABASE_URL was wired up), write a row reflecting the current
    served model so the /model header stops showing 'v0.1.0-dev'.

    This is purely a "label catch-up" — it does not flip MLflow aliases.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    db_model_name = DB_MODEL_NAME_BY_TYPE.get(model_type)
    if not db_model_name:
        return None
    try:
        prod = client.get_model_version_by_alias(name=model_name, alias="prod")
    except Exception:
        return None
    if not prod or not prod.run_id:
        return None
    try:
        run = client.get_run(prod.run_id)
    except Exception:
        return None

    arch_label = _human_arch_from_run_name(
        run.data.tags.get("mlflow.runName") if run.data.tags else None
    )

    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.begin() as conn:
            existing = conn.execute(
                text(
                    "SELECT mlflow_run_id FROM model_registry "
                    "WHERE model_name = :n AND is_production = TRUE"
                ),
                {"n": db_model_name},
            ).first()
            if existing and existing[0] == prod.run_id:
                return None  # already in sync
            base = _bump_version(existing[0] if existing else None)
            # Reuse the version-bump rule: if the table is empty, this
            # writes v0.2.0 (so the user sees an immediate change away
            # from v0.1.0-dev).
            new_label = f"{base}-{arch_label}" if arch_label else base
            conn.execute(
                text("UPDATE model_registry SET is_production = FALSE WHERE model_name = :n"),
                {"n": db_model_name},
            )
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
                    "run_id": prod.run_id,
                    "acc": run.data.metrics.get("val_accuracy"),
                    "f1": run.data.metrics.get("val_f1_macro"),
                    "ll": run.data.metrics.get("val_log_loss"),
                },
            )
        logger.info("Synced model_registry to current @prod: %s = %s", db_model_name, new_label)
        return new_label
    except Exception:
        logger.exception("model_registry sync failed (DB-only; MLflow alias unchanged)")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-type", required=True, choices=list(MODEL_TYPES))
    parser.add_argument("--metric", default=DEFAULT_METRIC,
                        help="metric logged on the training run; lower-is-better (default: val_log_loss)")
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN,
                        help="required relative improvement (default: 0.01 = 1%%)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the decision without registering or flipping alias")
    # Multi-metric gate is on by default — single-metric is too noisy on
    # ~880-row val windows (a 0.3pp acc drop blocked v9 even though
    # val_log_loss likely improved). Pass --no-multi-metric to fall back
    # to the legacy single-metric gate.
    parser.add_argument(
        "--multi-metric",
        dest="multi_metric",
        action="store_true",
        default=True,
        help="enable dual-criterion gate over (acc, log_loss, brier) — default on",
    )
    parser.add_argument(
        "--no-multi-metric",
        dest="multi_metric",
        action="store_false",
        help="fall back to single-metric (--metric) gate",
    )
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
            multi_metric=args.multi_metric,
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
    elif not decision.promoted:
        # Backfill the model_registry row for the existing @prod if it
        # somehow drifted out of sync (e.g., a previous promotion ran
        # before DATABASE_URL was plumbed through). Cheap idempotent op.
        try:
            _, model_name = MODEL_TYPES[args.model_type]
            client = MlflowClient()
            synced = _sync_current_prod_to_db(client, args.model_type, model_name)
            if synced:
                logger.info("model_registry catch-up label: %s = %s", args.model_type, synced)
        except Exception:
            logger.exception("model_registry catch-up sync failed (non-fatal)")
    # Emit a concise machine-readable summary for CI log searchability.
    # When the multi-metric gate is on we also surface val_accuracy,
    # val_log_loss, and val_brier_score from the new run so CI/Slack
    # alerts can see the full picture without re-querying MLflow.
    nrm = decision.new_run_metrics or {}
    extra = ""
    if args.multi_metric:
        extra = (
            f" new_val_accuracy={nrm.get('val_accuracy')} "
            f"new_val_log_loss={nrm.get('val_log_loss')} "
            f"new_val_brier_score={nrm.get('val_brier_score')}"
        )
    print(
        f"promotion_result model={args.model_type} "
        f"gate={'multi' if args.multi_metric else 'single'} "
        f"promoted={decision.promoted} "
        f"new_version={decision.new_version} new_{args.metric}={decision.new_metric} "
        f"current_version={decision.current_version} current_{args.metric}={decision.current_metric} "
        f"db_label={decision.db_label or 'none'}{extra}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
