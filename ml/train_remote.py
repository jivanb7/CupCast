import argparse
import logging
import os
import tempfile
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from pathlib import Path
from sklearn.calibration import calibration_curve
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict
from sklearn.neural_network import MLPClassifier
from catboost import CatBoostClassifier
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
import xgboost as xgb
import lightgbm as lgb
import optuna

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from weighting import recency_weights  # noqa: E402
from config import CLUB_FEATURES, INTL_FEATURES  # noqa: E402

optuna.logging.set_verbosity(optuna.logging.WARNING)
warnings.filterwarnings("ignore", category=UserWarning)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------------------------
SAAS_DIR = Path(__file__).resolve().parent.parent
load_dotenv(SAAS_DIR / ".env")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR / "data"
FEATURES_DIR = DATA_DIR / "features"
MODELS_DIR = ML_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Remote MLflow (from .env)
#   Local dev:  MLFLOW_TRACKING_URI=http://localhost:5000  (via docker-compose)
#   Production: MLFLOW_TRACKING_URI=http://<GCP_VM_IP>:5000 (or the new URL)
# We intentionally don't hardcode a prod IP fallback — if the env var is
# missing in a deploy, we want the run to fail loud rather than silently
# log to a stale / wrong tracking server.
# ---------------------------------------------------------------------------
TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI")
if not TRACKING_URI:
    raise RuntimeError(
        "MLFLOW_TRACKING_URI is not set. "
        "Configure it in .env (local) or Cloud Run env vars (prod)."
    )
mlflow.set_tracking_uri(TRACKING_URI)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RESULT_LABELS = ["H", "D", "A"]

RECENCY_HALF_LIFE_YEARS = 3.0

CLUB_TRAIN_END = "2022-06-01"
CLUB_VAL_END = "2023-06-01"
CLUB_TEST_END = "2024-06-01"

INTL_TRAIN_END = "2020-01-01"
INTL_VAL_END = "2022-01-01"
INTL_TEST_END = "2024-01-01"

# Feature lists are imported from ml/src/config.py — single source of truth.


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------
def compute_all_metrics(y_true, y_prob):
    y_pred = np.argmax(y_prob, axis=1)
    metrics = {
        "accuracy": accuracy_score(y_true, y_pred),
        "f1_macro": f1_score(y_true, y_pred, average="macro"),
        "log_loss": log_loss(y_true, y_prob, labels=[0, 1, 2]),
    }
    try:
        metrics["roc_auc_macro"] = roc_auc_score(y_true, y_prob, multi_class="ovr", average="macro")
    except ValueError:
        metrics["roc_auc_macro"] = 0.0
    brier_scores = []
    for cls in range(y_prob.shape[1]):
        y_binary = (y_true == cls).astype(int)
        brier_scores.append(brier_score_loss(y_binary, y_prob[:, cls]))
    metrics["brier_score"] = np.mean(brier_scores)
    return metrics


def _safe_log_artifact(fig):
    """Log a matplotlib figure as an MLflow artifact, handling remote artifact store gracefully."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            fig.savefig(f.name, dpi=100)
            mlflow.log_artifact(f.name, artifact_path="plots")
    except OSError:
        logger.warning("Artifact upload skipped (remote artifact store not writable from local)")


def log_confusion_matrix(y_true, y_pred):
    fig, ax = plt.subplots(figsize=(6, 5))
    cm = confusion_matrix(y_true, y_pred)
    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=RESULT_LABELS)
    disp.plot(ax=ax, cmap="Blues")
    ax.set_title("Confusion Matrix")
    plt.tight_layout()
    _safe_log_artifact(fig)
    plt.close(fig)


def log_calibration_curve(y_true, y_prob):
    fig, ax = plt.subplots(figsize=(7, 6))
    class_names = ["Home Win", "Draw", "Away Win"]
    for cls in range(y_prob.shape[1]):
        y_binary = (y_true == cls).astype(int)
        prob_true, prob_pred = calibration_curve(y_binary, y_prob[:, cls], n_bins=10, strategy="uniform")
        ax.plot(prob_pred, prob_true, marker="o", label=class_names[cls])
    ax.plot([0, 1], [0, 1], "k--", label="Perfectly calibrated")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Fraction of positives")
    ax.set_title("Calibration Curves")
    ax.legend()
    plt.tight_layout()
    _safe_log_artifact(fig)
    plt.close(fig)


def log_feature_importance(model, feature_names, model_type="xgboost", top_n=30):
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    elif hasattr(model, "coef_"):
        importances = np.abs(model.coef_).mean(axis=0)
    else:
        return
    indices = np.argsort(importances)[::-1][:top_n]
    top_features = [feature_names[i] for i in indices]
    top_importances = importances[indices]
    fig, ax = plt.subplots(figsize=(10, 8))
    y_pos = np.arange(len(top_features))
    ax.barh(y_pos, top_importances[::-1])
    ax.set_yticks(y_pos)
    ax.set_yticklabels(top_features[::-1], fontsize=8)
    ax.set_xlabel("Importance")
    ax.set_title(f"Top {top_n} Feature Importances ({model_type})")
    plt.tight_layout()
    _safe_log_artifact(fig)
    plt.close(fig)


def _log_metrics(metrics, prefix=""):
    for k, v in metrics.items():
        mlflow.log_metric(f"{prefix}{k}", v)


# ---------------------------------------------------------------------------
# Data splitting
# ---------------------------------------------------------------------------
def time_split(df, train_end, val_end, test_end, feature_cols, target_col="result_encoded"):
    train_mask = df["match_date"] < train_end
    val_mask = (df["match_date"] >= train_end) & (df["match_date"] < val_end)
    test_mask = (df["match_date"] >= val_end) & (df["match_date"] < test_end)

    train_dates = df.loc[train_mask, "match_date"]

    X_train = df.loc[train_mask, feature_cols].astype(float)
    X_val = df.loc[val_mask, feature_cols].astype(float)
    X_test = df.loc[test_mask, feature_cols].astype(float)
    y_train = df.loc[train_mask, target_col].astype(int)
    y_val = df.loc[val_mask, target_col].astype(int)
    y_test = df.loc[test_mask, target_col].astype(int)

    return X_train, X_val, X_test, y_train, y_val, y_test, train_dates


# ---------------------------------------------------------------------------
# Model training functions
# ---------------------------------------------------------------------------
def train_logistic_regression(X_train, y_train, X_val, y_val, sample_weight=None):
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    model = LogisticRegression(max_iter=1000, solver="lbfgs", random_state=42, C=1.0)
    model.fit(X_train_scaled, y_train, sample_weight=sample_weight)
    y_prob_val = model.predict_proba(X_val_scaled)
    y_pred_val = model.predict(X_val_scaled)
    metrics = compute_all_metrics(y_val.values, y_prob_val)
    mlflow.log_params({"model_type": "logistic_regression", "C": 1.0, "max_iter": 1000,
                       "recency_half_life_years": RECENCY_HALF_LIFE_YEARS})
    _log_metrics(metrics, prefix="val_")
    log_confusion_matrix(y_val.values, y_pred_val)
    logger.info("LR - val log_loss: %.4f, accuracy: %.4f", metrics["log_loss"], metrics["accuracy"])
    return {"model": model, "scaler": scaler, **metrics}


def train_random_forest(X_train, y_train, X_val, y_val, sample_weight=None):
    model = RandomForestClassifier(n_estimators=300, max_depth=12, min_samples_split=10, min_samples_leaf=5, random_state=42, n_jobs=2)
    model.fit(X_train, y_train, sample_weight=sample_weight)
    y_prob_val = model.predict_proba(X_val)
    y_pred_val = model.predict(X_val)
    metrics = compute_all_metrics(y_val.values, y_prob_val)
    mlflow.log_params({"model_type": "random_forest", "n_estimators": 300, "max_depth": 12,
                       "recency_half_life_years": RECENCY_HALF_LIFE_YEARS})
    _log_metrics(metrics, prefix="val_")
    log_confusion_matrix(y_val.values, y_pred_val)
    log_feature_importance(model, list(X_train.columns), model_type="random_forest")
    logger.info("RF - val log_loss: %.4f, accuracy: %.4f", metrics["log_loss"], metrics["accuracy"])
    return {"model": model, **metrics}


def train_xgboost_with_optuna(X_train, y_train, X_val, y_val, n_trials=10, sample_weight=None):
    def objective(trial):
        params = {
            "objective": "multi:softprob", "num_class": 3, "eval_metric": "mlogloss",
            "tree_method": "hist", "random_state": 42, "n_jobs": 2, "verbosity": 0,
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "gamma": trial.suggest_float("gamma", 0, 5),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
        }
        model = xgb.XGBClassifier(**params)
        model.fit(X_train, y_train, sample_weight=sample_weight, eval_set=[(X_val, y_val)], verbose=False)
        y_prob = model.predict_proba(X_val)
        return log_loss(y_val, y_prob, labels=[0, 1, 2])

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_params = study.best_params
    best_params.update({"objective": "multi:softprob", "num_class": 3, "eval_metric": "mlogloss",
                        "tree_method": "hist", "random_state": 42, "n_jobs": 2, "verbosity": 0})
    best_model = xgb.XGBClassifier(**best_params)
    best_model.fit(X_train, y_train, sample_weight=sample_weight, eval_set=[(X_val, y_val)], verbose=False)

    mlflow.log_params({f"xgb_{k}": v for k, v in study.best_params.items()})
    mlflow.log_param("recency_half_life_years", RECENCY_HALF_LIFE_YEARS)
    mlflow.log_metric("optuna_best_val_logloss", study.best_value)
    mlflow.log_metric("optuna_n_trials", n_trials)
    logger.info("XGBoost Optuna - best val log_loss: %.4f after %d trials", study.best_value, n_trials)
    return best_model, best_params, study.best_value


def train_hist_gb(X_train, y_train, X_val, y_val, sample_weight=None):
    """sklearn's HistGradientBoosting — fast, robust to missing values, no
    Optuna because the defaults are already good and we want a quick honest
    baseline alongside XGB / LGB / Cat."""
    model = HistGradientBoostingClassifier(
        loss="log_loss",
        max_iter=400,
        learning_rate=0.05,
        max_depth=8,
        l2_regularization=0.1,
        early_stopping=True,
        validation_fraction=0.15,
        random_state=42,
    )
    model.fit(X_train, y_train, sample_weight=sample_weight)
    y_prob_val = model.predict_proba(X_val)
    y_pred_val = model.predict(X_val)
    metrics = compute_all_metrics(y_val.values, y_prob_val)
    mlflow.log_params({"model_type": "hist_gradient_boosting", "max_iter": 400,
                       "learning_rate": 0.05, "max_depth": 8,
                       "recency_half_life_years": RECENCY_HALF_LIFE_YEARS})
    _log_metrics(metrics, prefix="val_")
    log_confusion_matrix(y_val.values, y_pred_val)
    logger.info("HGB - val log_loss: %.4f, accuracy: %.4f", metrics["log_loss"], metrics["accuracy"])
    return {"model": model, **metrics}


def train_catboost_with_optuna(X_train, y_train, X_val, y_val, n_trials=10, sample_weight=None):
    """CatBoost with Optuna — strong tabular model, native categorical
    handling. We pass numeric features only (no cat_features list) since
    upstream feature engineering already encoded categoricals."""

    def objective(trial):
        params = {
            "loss_function": "MultiClass",
            "iterations": trial.suggest_int("iterations", 200, 600),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "depth": trial.suggest_int("depth", 4, 10),
            "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 10.0, log=True),
            "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 1.0),
            "border_count": trial.suggest_int("border_count", 32, 254),
            "random_strength": trial.suggest_float("random_strength", 1e-3, 10.0, log=True),
            "thread_count": 2,
            "verbose": 0,
            "random_seed": 42,
        }
        model = CatBoostClassifier(**params)
        model.fit(X_train, y_train, sample_weight=sample_weight, eval_set=(X_val, y_val), verbose=False)
        y_prob = model.predict_proba(X_val)
        return log_loss(y_val, y_prob, labels=[0, 1, 2])

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_params = study.best_params
    best_params.update({"loss_function": "MultiClass", "thread_count": 2,
                        "verbose": 0, "random_seed": 42})
    best_model = CatBoostClassifier(**best_params)
    best_model.fit(X_train, y_train, sample_weight=sample_weight, eval_set=(X_val, y_val), verbose=False)

    mlflow.log_params({f"cat_{k}": v for k, v in study.best_params.items()})
    mlflow.log_param("recency_half_life_years", RECENCY_HALF_LIFE_YEARS)
    mlflow.log_metric("optuna_best_val_logloss", study.best_value)
    mlflow.log_metric("optuna_n_trials", n_trials)
    logger.info("CatBoost Optuna - best val log_loss: %.4f after %d trials", study.best_value, n_trials)
    return best_model, best_params, study.best_value


def train_calibrated_wrapper(base_factory, X_train, y_train, X_val, y_val,
                             sample_weight=None, base_label="model"):
    """Cross-validated calibration on the training set.

    Previous round used cv='prefit' on the small val set, which over-fit
    the calibrator and hurt log-loss. CV=3 across train re-fits the base
    inside each fold and trains the isotonic mapping on that fold's OOF
    predictions — much more stable. `base_factory` is a callable returning
    an unfitted classifier (CalibratedClassifierCV refits per fold).
    """
    calibrated = CalibratedClassifierCV(base_factory(), method="isotonic", cv=3)
    calibrated.fit(X_train, y_train, sample_weight=sample_weight)
    y_prob_val = calibrated.predict_proba(X_val)
    metrics = compute_all_metrics(y_val.values, y_prob_val)
    mlflow.log_params({"model_type": "calibrated_isotonic_cv3",
                       "base": base_label})
    _log_metrics(metrics, prefix="val_")
    logger.info("Calibrated(%s, cv=3) - val log_loss: %.4f, accuracy: %.4f",
                base_label, metrics["log_loss"], metrics["accuracy"])
    return {"model": calibrated, **metrics}


def apply_home_bias(model, bias_pp=2.0):
    """Wrap any classifier so predict_proba receives a fixed +Npp shift on
    the home column, with the offset taken proportionally from draw + away.

    This is a post-hoc prior — useful when the trained model regresses too
    aggressively toward 33/33/33 on extreme matchups. 2pp is empirically
    where the home-advantage prior tends to land on European league data.
    """
    return _HomeBiasedModel(model, bias_pp / 100.0)


class _HomeBiasedModel:
    """Adds a fixed home-edge to predict_proba and renormalises."""

    def __init__(self, base, bias):
        self._base = base
        self._bias = float(bias)
        self.classes_ = getattr(base, "classes_", None)

    def predict_proba(self, X):
        p = self._base.predict_proba(X).copy()
        # H = column 0, D = column 1, A = column 2 (per RESULT_LABELS)
        shift = min(self._bias, p[:, 1].min() * 0.5 + p[:, 2].min() * 0.5)
        p[:, 0] += self._bias
        # Take from D/A proportionally so neither goes negative.
        d_share = p[:, 1] / (p[:, 1] + p[:, 2] + 1e-12)
        p[:, 1] -= self._bias * d_share
        p[:, 2] -= self._bias * (1 - d_share)
        # Renormalise rows to sum to 1 in case of small numerical drift.
        p = np.clip(p, 1e-6, 1.0)
        p = p / p.sum(axis=1, keepdims=True)
        return p

    def predict(self, X):
        return np.argmax(self.predict_proba(X), axis=1)


def train_stacked_ensemble(base_specs, X_train, y_train, X_val, y_val, sample_weight=None):
    """Out-of-fold stacking: each base model produces 3-fold OOF probability
    predictions on the training set; a small logistic regression meta-learner
    is fit on the concatenated OOF probability matrix, then refit cleanly on
    the full train set's OOF outputs. At inference each base model produces
    fresh predict_proba and the meta concatenates those.

    `base_specs` is a list of (name, untrained_model_factory) tuples. The
    factory returns a fresh classifier each call so cross_val_predict can
    refit it per fold without state leakage.
    """
    from sklearn.base import clone
    from sklearn.model_selection import KFold

    # Build a 3-fold OOF probability matrix per base model.
    kf = KFold(n_splits=3, shuffle=True, random_state=42)
    oof_blocks = []
    base_models = []
    for name, factory in base_specs:
        est = factory()
        # cross_val_predict returns OOF predictions in the original order.
        oof = cross_val_predict(est, X_train, y_train, cv=kf, method="predict_proba", n_jobs=1)
        oof_blocks.append(oof)
        # Refit on full train so we can get val/test predictions later.
        est_full = factory()
        est_full.fit(X_train, y_train)
        base_models.append((name, est_full))
        logger.info("  stack base %s OOF shape=%s", name, oof.shape)

    train_meta = np.hstack(oof_blocks)
    meta = LogisticRegression(max_iter=2000, solver="lbfgs", C=1.0, random_state=42)
    meta.fit(train_meta, y_train)

    # Build val predictions: each base predicts on val, concat, meta predicts.
    val_blocks = [m.predict_proba(X_val) for _, m in base_models]
    val_meta = np.hstack(val_blocks)
    y_prob_val = meta.predict_proba(val_meta)
    metrics = compute_all_metrics(y_val.values, y_prob_val)

    bundle = _StackedBundle(base_models, meta)

    mlflow.log_params({
        "model_type": "stacked_ensemble",
        "stack_bases": ",".join(name for name, _ in base_specs),
        "meta": "logistic_regression",
        "cv_folds": 3,
    })
    _log_metrics(metrics, prefix="val_")
    logger.info("Stacked ensemble - val log_loss: %.4f, accuracy: %.4f",
                metrics["log_loss"], metrics["accuracy"])
    return {"model": bundle, **metrics}


class _StackedBundle:
    """Wraps base_models + meta so downstream evaluate_on_test() / joblib
    serialisation work transparently."""

    def __init__(self, base_models, meta):
        self._base_models = base_models
        self._meta = meta
        self.classes_ = meta.classes_

    def _stack(self, X):
        return np.hstack([m.predict_proba(X) for _, m in self._base_models])

    def predict_proba(self, X):
        return self._meta.predict_proba(self._stack(X))

    def predict(self, X):
        return self._meta.predict(self._stack(X))


def train_mlp_with_optuna(X_train, y_train, X_val, y_val, n_trials=10, sample_weight=None):
    """Multi-layer perceptron — same competition shape as the others.

    NNs need scaled inputs, so we fit a StandardScaler on the train split
    and reuse it for val/test. Optuna tunes architecture (depth, width),
    regularisation (alpha), learning-rate init, and activation. Returns
    (model, scaler, best_params, best_val_logloss). The wrapper class below
    glues the scaler into predict_proba so downstream evaluate_on_test()
    works unchanged.
    """
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_val_s = scaler.transform(X_val)

    def objective(trial):
        n_layers = trial.suggest_int("n_layers", 1, 3)
        widths = []
        for i in range(n_layers):
            widths.append(trial.suggest_int(f"layer_{i}_width", 16, 256, log=True))
        params = {
            "hidden_layer_sizes": tuple(widths),
            "activation": trial.suggest_categorical("activation", ["relu", "tanh"]),
            "alpha": trial.suggest_float("alpha", 1e-6, 1e-1, log=True),
            "learning_rate_init": trial.suggest_float("learning_rate_init", 1e-4, 1e-2, log=True),
            "batch_size": trial.suggest_categorical("batch_size", [64, 128, 256]),
            "solver": "adam",
            "max_iter": 200,
            "early_stopping": True,
            "validation_fraction": 0.1,
            "n_iter_no_change": 12,
            "random_state": 42,
        }
        model = MLPClassifier(**params)
        # MLPClassifier doesn't accept sample_weight in fit(); skip it for the NN.
        model.fit(X_train_s, y_train)
        y_prob = model.predict_proba(X_val_s)
        return log_loss(y_val, y_prob, labels=[0, 1, 2])

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_params = study.best_params
    n_layers = best_params.pop("n_layers")
    hidden = tuple(best_params.pop(f"layer_{i}_width") for i in range(n_layers))
    final_params = {
        "hidden_layer_sizes": hidden,
        "activation": best_params["activation"],
        "alpha": best_params["alpha"],
        "learning_rate_init": best_params["learning_rate_init"],
        "batch_size": best_params["batch_size"],
        "solver": "adam",
        "max_iter": 400,
        "early_stopping": True,
        "validation_fraction": 0.1,
        "n_iter_no_change": 16,
        "random_state": 42,
    }
    base_model = MLPClassifier(**final_params)
    base_model.fit(X_train_s, y_train)

    # Wrap so .predict_proba accepts raw (unscaled) features and downstream
    # evaluate_on_test / log_feature_importance / log_calibration_curve all
    # keep working without special-casing the NN.
    wrapped = _ScaledMLP(base_model, scaler, list(X_train.columns))

    mlflow.log_params({f"mlp_{k}": v for k, v in study.best_params.items()})
    mlflow.log_param("recency_half_life_years", RECENCY_HALF_LIFE_YEARS)
    mlflow.log_metric("optuna_best_val_logloss", study.best_value)
    mlflow.log_metric("optuna_n_trials", n_trials)
    logger.info("MLP Optuna - best val log_loss: %.4f after %d trials", study.best_value, n_trials)
    return wrapped, final_params, study.best_value


class _ScaledMLP:
    """Thin wrapper: applies the train-time StandardScaler to inputs before
    delegating to the underlying MLPClassifier. Exposes the same surface
    (predict_proba, predict, classes_) the rest of the trainer expects."""

    def __init__(self, model, scaler, feature_names):
        self._model = model
        self._scaler = scaler
        self._feature_names = list(feature_names)
        self.classes_ = model.classes_

    def predict_proba(self, X):
        return self._model.predict_proba(self._scaler.transform(X))

    def predict(self, X):
        return self._model.predict(self._scaler.transform(X))

    # Feature importance via permutation isn't free — skip; log_feature_importance
    # already short-circuits when neither feature_importances_ nor coef_ exists.


def train_lightgbm_with_optuna(X_train, y_train, X_val, y_val, n_trials=10, sample_weight=None):
    def objective(trial):
        params = {
            "objective": "multiclass", "num_class": 3, "metric": "multi_logloss",
            "verbosity": -1, "random_state": 42, "n_jobs": 2,
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "min_child_weight": trial.suggest_float("min_child_weight", 0.001, 10.0, log=True),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 15, 127),
        }
        model = lgb.LGBMClassifier(**params)
        model.fit(X_train, y_train, sample_weight=sample_weight, eval_set=[(X_val, y_val)])
        y_prob = model.predict_proba(X_val)
        return log_loss(y_val, y_prob, labels=[0, 1, 2])

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_params = study.best_params
    best_params.update({"objective": "multiclass", "num_class": 3, "metric": "multi_logloss",
                        "verbosity": -1, "random_state": 42, "n_jobs": 2})
    best_model = lgb.LGBMClassifier(**best_params)
    best_model.fit(X_train, y_train, sample_weight=sample_weight, eval_set=[(X_val, y_val)])

    mlflow.log_params({f"lgb_{k}": v for k, v in study.best_params.items()})
    mlflow.log_param("recency_half_life_years", RECENCY_HALF_LIFE_YEARS)
    mlflow.log_metric("optuna_best_val_logloss", study.best_value)
    logger.info("LightGBM Optuna - best val log_loss: %.4f after %d trials", study.best_value, n_trials)
    return best_model, best_params, study.best_value


# ---------------------------------------------------------------------------
# Test evaluation
# ---------------------------------------------------------------------------
def evaluate_on_test(model, X_test, y_test, model_name):
    y_prob = model.predict_proba(X_test)
    y_pred = np.argmax(y_prob, axis=1)
    metrics = compute_all_metrics(y_test.values, y_prob)
    _log_metrics(metrics, prefix="test_")
    log_confusion_matrix(y_test.values, y_pred)
    log_calibration_curve(y_test.values, y_prob)
    log_feature_importance(model, list(X_test.columns), model_type=model_name)
    logger.info("%s TEST - acc: %.4f, f1: %.4f, log_loss: %.4f, roc_auc: %.4f",
                model_name, metrics["accuracy"], metrics["f1_macro"], metrics["log_loss"], metrics["roc_auc_macro"])
    return metrics


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def run_training(model_type="club", n_trials=10):
    if model_type == "club":
        train_end, val_end, test_end = CLUB_TRAIN_END, CLUB_VAL_END, CLUB_TEST_END
        feature_cols = CLUB_FEATURES
        features_path = FEATURES_DIR / "club_features.parquet"
        experiment_name = "cupcast-club"
    else:
        train_end, val_end, test_end = INTL_TRAIN_END, INTL_VAL_END, INTL_TEST_END
        feature_cols = INTL_FEATURES
        features_path = FEATURES_DIR / "intl_features.parquet"
        experiment_name = "cupcast-international"

    if not features_path.exists():
        raise FileNotFoundError(f"Features file not found: {features_path}")

    df = pd.read_parquet(features_path)
    logger.info("Loaded %d rows from %s", len(df), features_path)

    # Filter to only features that exist in the dataframe
    available_features = [f for f in feature_cols if f in df.columns]
    missing = set(feature_cols) - set(available_features)
    if missing:
        logger.warning("Missing %d features (will use available): %s", len(missing), missing)
    feature_cols = available_features

    X_train, X_val, X_test, y_train, y_val, y_test, train_dates = time_split(
        df, train_end, val_end, test_end, feature_cols
    )
    logger.info("Data split: train=%d, val=%d, test=%d", len(X_train), len(X_val), len(X_test))

    if len(X_train) == 0:
        raise ValueError("Empty training set. Check date splits.")

    sample_weight_train = recency_weights(train_dates, RECENCY_HALF_LIFE_YEARS)
    logger.info("Recency weights (half-life=%.1fy): min=%.3f median=%.3f max=%.3f",
                RECENCY_HALF_LIFE_YEARS, float(sample_weight_train.min()),
                float(np.median(sample_weight_train)), float(sample_weight_train.max()))

    mlflow.set_experiment(experiment_name)
    results = {}
    has_test = len(X_test) > 0

    # 1. Logistic Regression
    with mlflow.start_run(run_name="logistic_regression") as run:
        lr_result = train_logistic_regression(X_train, y_train, X_val, y_val, sample_weight=sample_weight_train)
        if has_test:
            lr_test = evaluate_on_test(lr_result["model"], X_test, y_test, "logistic_regression")
        else:
            lr_test = {k: v for k, v in lr_result.items() if k not in ("model", "scaler")}
        results["logistic_regression"] = {"model": lr_result["model"], "run_id": run.info.run_id, **lr_test}

    # 2. Random Forest
    with mlflow.start_run(run_name="random_forest") as run:
        rf_result = train_random_forest(X_train, y_train, X_val, y_val, sample_weight=sample_weight_train)
        if has_test:
            rf_test = evaluate_on_test(rf_result["model"], X_test, y_test, "random_forest")
        else:
            rf_test = {k: v for k, v in rf_result.items() if k != "model"}
        results["random_forest"] = {"model": rf_result["model"], "run_id": run.info.run_id, **rf_test}

    # 3. XGBoost with Optuna
    with mlflow.start_run(run_name="xgboost_optuna") as run:
        xgb_model, xgb_params, _ = train_xgboost_with_optuna(
            X_train, y_train, X_val, y_val, n_trials=n_trials, sample_weight=sample_weight_train
        )
        if has_test:
            xgb_test = evaluate_on_test(xgb_model, X_test, y_test, "xgboost")
        else:
            y_prob = xgb_model.predict_proba(X_val)
            xgb_test = compute_all_metrics(y_val.values, y_prob)
        results["xgboost"] = {"model": xgb_model, "run_id": run.info.run_id, **xgb_test}

    # 4. LightGBM with Optuna
    with mlflow.start_run(run_name="lightgbm_optuna") as run:
        lgb_model, lgb_params, _ = train_lightgbm_with_optuna(
            X_train, y_train, X_val, y_val, n_trials=n_trials, sample_weight=sample_weight_train
        )
        if has_test:
            lgb_test = evaluate_on_test(lgb_model, X_test, y_test, "lightgbm")
        else:
            y_prob = lgb_model.predict_proba(X_val)
            lgb_test = compute_all_metrics(y_val.values, y_prob)
        results["lightgbm"] = {"model": lgb_model, "run_id": run.info.run_id, **lgb_test}

    # 5. Neural network (MLP) with Optuna
    with mlflow.start_run(run_name="mlp_optuna") as run:
        mlp_model, mlp_params, _ = train_mlp_with_optuna(
            X_train, y_train, X_val, y_val, n_trials=n_trials, sample_weight=sample_weight_train
        )
        if has_test:
            mlp_test = evaluate_on_test(mlp_model, X_test, y_test, "mlp")
        else:
            y_prob = mlp_model.predict_proba(X_val)
            mlp_test = compute_all_metrics(y_val.values, y_prob)
        results["mlp"] = {"model": mlp_model, "run_id": run.info.run_id, **mlp_test}

    # 6. Histogram gradient boosting (sklearn, no Optuna)
    with mlflow.start_run(run_name="hist_gradient_boosting") as run:
        hgb_result = train_hist_gb(X_train, y_train, X_val, y_val, sample_weight=sample_weight_train)
        if has_test:
            hgb_test = evaluate_on_test(hgb_result["model"], X_test, y_test, "hist_gradient_boosting")
        else:
            hgb_test = {k: v for k, v in hgb_result.items() if k != "model"}
        results["hist_gradient_boosting"] = {"model": hgb_result["model"], "run_id": run.info.run_id, **hgb_test}

    # 7. CatBoost with Optuna
    with mlflow.start_run(run_name="catboost_optuna") as run:
        cat_model, cat_params, _ = train_catboost_with_optuna(
            X_train, y_train, X_val, y_val, n_trials=n_trials, sample_weight=sample_weight_train
        )
        if has_test:
            cat_test = evaluate_on_test(cat_model, X_test, y_test, "catboost")
        else:
            y_prob = cat_model.predict_proba(X_val)
            cat_test = compute_all_metrics(y_val.values, y_prob)
        results["catboost"] = {"model": cat_model, "run_id": run.info.run_id, **cat_test}

    # 8. Calibrated wrapper on the current leader (by val log_loss).
    #    cv=3 over the training set — much more stable than prefit-on-val.
    interim_best = min(results.keys(), key=lambda k: results[k]["log_loss"])
    cal_factories = {
        "random_forest": lambda: RandomForestClassifier(
            n_estimators=300, max_depth=12, min_samples_split=10,
            min_samples_leaf=5, random_state=42, n_jobs=2),
        "xgboost": lambda: xgb.XGBClassifier(
            objective="multi:softprob", num_class=3, eval_metric="mlogloss",
            tree_method="hist", n_estimators=300, max_depth=6,
            learning_rate=0.05, random_state=42, n_jobs=2, verbosity=0),
        "lightgbm": lambda: lgb.LGBMClassifier(
            objective="multiclass", num_class=3, metric="multi_logloss",
            n_estimators=300, max_depth=6, learning_rate=0.05,
            random_state=42, n_jobs=2, verbosity=-1),
        "hist_gradient_boosting": lambda: HistGradientBoostingClassifier(
            loss="log_loss", max_iter=300, learning_rate=0.05,
            max_depth=8, l2_regularization=0.1, random_state=42),
        "catboost": lambda: CatBoostClassifier(
            loss_function="MultiClass", iterations=400, depth=6,
            learning_rate=0.05, thread_count=2, verbose=0, random_seed=42),
    }
    cal_factory = cal_factories.get(interim_best)
    if cal_factory is not None:
        with mlflow.start_run(run_name=f"calibrated_isotonic_cv3_on_{interim_best}") as run:
            cal_result = train_calibrated_wrapper(
                cal_factory, X_train, y_train, X_val, y_val,
                sample_weight=sample_weight_train, base_label=interim_best,
            )
            if has_test:
                cal_test = evaluate_on_test(cal_result["model"], X_test, y_test, f"calibrated_{interim_best}")
            else:
                cal_test = {k: v for k, v in cal_result.items() if k != "model"}
            results[f"calibrated_{interim_best}"] = {
                "model": cal_result["model"], "run_id": run.info.run_id, **cal_test
            }

    # 9. Stacked ensemble — meta-LR over the strong tabular bases.
    #    Skip MLP from the stack (its scaler-wrapper makes cross_val_predict
    #    awkward) and skip the calibrated wrapper (already a meta layer).
    with mlflow.start_run(run_name="stacked_ensemble") as run:
        stack_specs = [
            ("rf", lambda: RandomForestClassifier(
                n_estimators=300, max_depth=12, min_samples_split=10,
                min_samples_leaf=5, random_state=42, n_jobs=2,
            )),
            ("xgb", lambda: xgb.XGBClassifier(
                objective="multi:softprob", num_class=3, eval_metric="mlogloss",
                tree_method="hist", n_estimators=300, max_depth=6,
                learning_rate=0.05, random_state=42, n_jobs=2, verbosity=0,
            )),
            ("lgb", lambda: lgb.LGBMClassifier(
                objective="multiclass", num_class=3, metric="multi_logloss",
                n_estimators=300, max_depth=6, learning_rate=0.05,
                random_state=42, n_jobs=2, verbosity=-1,
            )),
            ("hgb", lambda: HistGradientBoostingClassifier(
                loss="log_loss", max_iter=300, learning_rate=0.05,
                max_depth=8, l2_regularization=0.1, random_state=42,
            )),
        ]
        stack_result = train_stacked_ensemble(stack_specs, X_train, y_train, X_val, y_val,
                                              sample_weight=sample_weight_train)
        if has_test:
            stack_test = evaluate_on_test(stack_result["model"], X_test, y_test, "stacked_ensemble")
        else:
            stack_test = {k: v for k, v in stack_result.items() if k != "model"}
        results["stacked_ensemble"] = {
            "model": stack_result["model"], "run_id": run.info.run_id, **stack_test
        }

    # 10. Home-bias wrapper on the current leader.
    #     +2 pp shifted to the home column, renormalised. Tests the prior
    #     that the trained model regresses toward 33/33/33 on extreme
    #     matchups and could use a fixed home-advantage nudge.
    interim_best2 = min(results.keys(), key=lambda k: results[k]["log_loss"])
    biased_base = results[interim_best2]["model"]
    with mlflow.start_run(run_name=f"home_bias_2pp_on_{interim_best2}") as run:
        biased = apply_home_bias(biased_base, bias_pp=2.0)
        y_prob_val = biased.predict_proba(X_val)
        bias_metrics = compute_all_metrics(y_val.values, y_prob_val)
        mlflow.log_params({"model_type": "home_bias_wrapper",
                           "base": interim_best2, "bias_pp": 2.0})
        _log_metrics(bias_metrics, prefix="val_")
        if has_test:
            bias_test = evaluate_on_test(biased, X_test, y_test, f"home_bias_{interim_best2}")
        else:
            bias_test = bias_metrics
        results[f"home_bias_{interim_best2}"] = {
            "model": biased, "run_id": run.info.run_id, **bias_test
        }

    # Select best by log-loss
    best_name = min(results.keys(), key=lambda k: results[k]["log_loss"])
    best = results[best_name]
    logger.info("BEST MODEL: %s (log_loss=%.4f, accuracy=%.4f, f1=%.4f)",
                best_name, best["log_loss"], best["accuracy"], best["f1_macro"])

    # Register best model
    with mlflow.start_run(run_id=best["run_id"]):
        try:
            if isinstance(best["model"], xgb.XGBClassifier):
                mlflow.xgboost.log_model(best["model"], artifact_path="model")
            elif isinstance(best["model"], lgb.LGBMClassifier):
                mlflow.lightgbm.log_model(best["model"], artifact_path="model")
            else:
                mlflow.sklearn.log_model(best["model"], artifact_path="model")
        except OSError:
            logger.warning("Model artifact upload skipped (remote artifact store not writable from local)")

    # Save locally too
    import joblib
    model_path = MODELS_DIR / f"{experiment_name}_best.joblib"
    joblib.dump(best["model"], model_path)
    logger.info("Saved best %s model to %s", best_name, model_path)

    # Summary
    print(f"\n{'='*60}")
    print(f"  Training complete — {experiment_name}")
    print(f"  MLflow UI: {TRACKING_URI}")
    print(f"{'='*60}")
    for name, res in results.items():
        marker = " <-- BEST" if name == best_name else ""
        print(f"  {name:25s}  log_loss={res['log_loss']:.4f}  acc={res['accuracy']:.4f}  f1={res['f1_macro']:.4f}{marker}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-type", choices=["club", "intl"], default="club")
    parser.add_argument("--n-trials", type=int, default=10, help="Optuna trials (keep low for speed)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_training(model_type=args.model_type, n_trials=args.n_trials)
