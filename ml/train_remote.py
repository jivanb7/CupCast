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
from sklearn.linear_model import LogisticRegression
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
# ---------------------------------------------------------------------------
TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://34.58.128.38:5000")
mlflow.set_tracking_uri(TRACKING_URI)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RESULT_LABELS = ["H", "D", "A"]

CLUB_TRAIN_END = "2022-06-01"
CLUB_VAL_END = "2023-06-01"
CLUB_TEST_END = "2024-06-01"

INTL_TRAIN_END = "2020-01-01"
INTL_VAL_END = "2022-01-01"
INTL_TEST_END = "2024-01-01"

CLUB_FEATURES = [
    "home_win_rate_5", "home_draw_rate_5", "home_loss_rate_5",
    "home_goals_scored_avg_5", "home_goals_conceded_avg_5",
    "home_goal_diff_avg_5", "home_points_per_game_5",
    "home_win_rate_10", "home_draw_rate_10", "home_loss_rate_10",
    "home_goals_scored_avg_10", "home_goals_conceded_avg_10",
    "home_goal_diff_avg_10", "home_points_per_game_10",
    "home_clean_sheets_pct_10", "home_failed_to_score_pct_10",
    "home_home_win_rate_5", "home_home_goals_scored_avg_5", "home_home_goals_conceded_avg_5",
    "home_shots_avg_5", "home_shots_on_target_avg_5", "home_shot_accuracy_5",
    "home_corners_avg_5", "home_yellow_cards_avg_5",
    "away_win_rate_5", "away_draw_rate_5", "away_loss_rate_5",
    "away_goals_scored_avg_5", "away_goals_conceded_avg_5",
    "away_goal_diff_avg_5", "away_points_per_game_5",
    "away_win_rate_10", "away_draw_rate_10", "away_loss_rate_10",
    "away_goals_scored_avg_10", "away_goals_conceded_avg_10",
    "away_goal_diff_avg_10", "away_points_per_game_10",
    "away_clean_sheets_pct_10", "away_failed_to_score_pct_10",
    "away_away_win_rate_5", "away_away_goals_scored_avg_5", "away_away_goals_conceded_avg_5",
    "away_shots_avg_5", "away_shots_on_target_avg_5", "away_shot_accuracy_5",
    "away_corners_avg_5", "away_yellow_cards_avg_5",
    "h2h_home_wins", "h2h_draws", "h2h_away_wins",
    "h2h_home_goals_avg", "h2h_away_goals_avg",
    "days_since_last_match_home", "days_since_last_match_away", "rest_advantage",
    "season_stage", "is_derby", "is_covid_era", "is_new_team_home", "is_new_team_away",
    "form_diff_goals_scored", "form_diff_goals_conceded", "form_diff_points",
    "attack_vs_defense", "defense_vs_attack",
    "odds_home", "odds_draw", "odds_away",
    "implied_prob_home", "implied_prob_draw", "implied_prob_away",
]

INTL_FEATURES = [
    "home_win_rate_5", "home_draw_rate_5", "home_loss_rate_5",
    "home_goals_scored_avg_5", "home_goals_conceded_avg_5",
    "home_goal_diff_avg_5", "home_points_per_game_5",
    "away_win_rate_5", "away_draw_rate_5", "away_loss_rate_5",
    "away_goals_scored_avg_5", "away_goals_conceded_avg_5",
    "away_goal_diff_avg_5", "away_points_per_game_5",
    "fifa_rank_home", "fifa_rank_away", "rank_difference", "rank_points_diff",
    "ranking_is_stale",
    "is_neutral_venue", "tournament_type",
    "confederation_home", "confederation_away", "same_confederation",
    "world_cup_appearances_home", "world_cup_appearances_away",
    "h2h_home_wins", "h2h_draws", "h2h_away_wins",
    "h2h_home_goals_avg", "h2h_away_goals_avg",
    "days_since_last_match_home", "days_since_last_match_away", "rest_advantage",
    "form_diff_goals_scored", "form_diff_goals_conceded", "form_diff_points",
]


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

    X_train = df.loc[train_mask, feature_cols].astype(float)
    X_val = df.loc[val_mask, feature_cols].astype(float)
    X_test = df.loc[test_mask, feature_cols].astype(float)
    y_train = df.loc[train_mask, target_col].astype(int)
    y_val = df.loc[val_mask, target_col].astype(int)
    y_test = df.loc[test_mask, target_col].astype(int)

    return X_train, X_val, X_test, y_train, y_val, y_test


# ---------------------------------------------------------------------------
# Model training functions
# ---------------------------------------------------------------------------
def train_logistic_regression(X_train, y_train, X_val, y_val):
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    model = LogisticRegression(max_iter=1000, multi_class="multinomial", solver="lbfgs", random_state=42, C=1.0)
    model.fit(X_train_scaled, y_train)
    y_prob_val = model.predict_proba(X_val_scaled)
    y_pred_val = model.predict(X_val_scaled)
    metrics = compute_all_metrics(y_val.values, y_prob_val)
    mlflow.log_params({"model_type": "logistic_regression", "C": 1.0, "max_iter": 1000})
    _log_metrics(metrics, prefix="val_")
    log_confusion_matrix(y_val.values, y_pred_val)
    logger.info("LR - val log_loss: %.4f, accuracy: %.4f", metrics["log_loss"], metrics["accuracy"])
    return {"model": model, "scaler": scaler, **metrics}


def train_random_forest(X_train, y_train, X_val, y_val):
    model = RandomForestClassifier(n_estimators=300, max_depth=12, min_samples_split=10, min_samples_leaf=5, random_state=42, n_jobs=2)
    model.fit(X_train, y_train)
    y_prob_val = model.predict_proba(X_val)
    y_pred_val = model.predict(X_val)
    metrics = compute_all_metrics(y_val.values, y_prob_val)
    mlflow.log_params({"model_type": "random_forest", "n_estimators": 300, "max_depth": 12})
    _log_metrics(metrics, prefix="val_")
    log_confusion_matrix(y_val.values, y_pred_val)
    log_feature_importance(model, list(X_train.columns), model_type="random_forest")
    logger.info("RF - val log_loss: %.4f, accuracy: %.4f", metrics["log_loss"], metrics["accuracy"])
    return {"model": model, **metrics}


def train_xgboost_with_optuna(X_train, y_train, X_val, y_val, n_trials=10):
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
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        y_prob = model.predict_proba(X_val)
        return log_loss(y_val, y_prob, labels=[0, 1, 2])

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_params = study.best_params
    best_params.update({"objective": "multi:softprob", "num_class": 3, "eval_metric": "mlogloss",
                        "tree_method": "hist", "random_state": 42, "n_jobs": 2, "verbosity": 0})
    best_model = xgb.XGBClassifier(**best_params)
    best_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    mlflow.log_params({f"xgb_{k}": v for k, v in study.best_params.items()})
    mlflow.log_metric("optuna_best_val_logloss", study.best_value)
    mlflow.log_metric("optuna_n_trials", n_trials)
    logger.info("XGBoost Optuna - best val log_loss: %.4f after %d trials", study.best_value, n_trials)
    return best_model, best_params, study.best_value


def train_lightgbm_with_optuna(X_train, y_train, X_val, y_val, n_trials=10):
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
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)])
        y_prob = model.predict_proba(X_val)
        return log_loss(y_val, y_prob, labels=[0, 1, 2])

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_params = study.best_params
    best_params.update({"objective": "multiclass", "num_class": 3, "metric": "multi_logloss",
                        "verbosity": -1, "random_state": 42, "n_jobs": 2})
    best_model = lgb.LGBMClassifier(**best_params)
    best_model.fit(X_train, y_train, eval_set=[(X_val, y_val)])

    mlflow.log_params({f"lgb_{k}": v for k, v in study.best_params.items()})
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

    X_train, X_val, X_test, y_train, y_val, y_test = time_split(df, train_end, val_end, test_end, feature_cols)
    logger.info("Data split: train=%d, val=%d, test=%d", len(X_train), len(X_val), len(X_test))

    if len(X_train) == 0:
        raise ValueError("Empty training set. Check date splits.")

    mlflow.set_experiment(experiment_name)
    results = {}
    has_test = len(X_test) > 0

    # 1. Logistic Regression
    with mlflow.start_run(run_name="logistic_regression") as run:
        lr_result = train_logistic_regression(X_train, y_train, X_val, y_val)
        if has_test:
            lr_test = evaluate_on_test(lr_result["model"], X_test, y_test, "logistic_regression")
        else:
            lr_test = {k: v for k, v in lr_result.items() if k not in ("model", "scaler")}
        results["logistic_regression"] = {"model": lr_result["model"], "run_id": run.info.run_id, **lr_test}

    # 2. Random Forest
    with mlflow.start_run(run_name="random_forest") as run:
        rf_result = train_random_forest(X_train, y_train, X_val, y_val)
        if has_test:
            rf_test = evaluate_on_test(rf_result["model"], X_test, y_test, "random_forest")
        else:
            rf_test = {k: v for k, v in rf_result.items() if k != "model"}
        results["random_forest"] = {"model": rf_result["model"], "run_id": run.info.run_id, **rf_test}

    # 3. XGBoost with Optuna
    with mlflow.start_run(run_name="xgboost_optuna") as run:
        xgb_model, xgb_params, _ = train_xgboost_with_optuna(X_train, y_train, X_val, y_val, n_trials=n_trials)
        if has_test:
            xgb_test = evaluate_on_test(xgb_model, X_test, y_test, "xgboost")
        else:
            y_prob = xgb_model.predict_proba(X_val)
            xgb_test = compute_all_metrics(y_val.values, y_prob)
        results["xgboost"] = {"model": xgb_model, "run_id": run.info.run_id, **xgb_test}

    # 4. LightGBM with Optuna
    with mlflow.start_run(run_name="lightgbm_optuna") as run:
        lgb_model, lgb_params, _ = train_lightgbm_with_optuna(X_train, y_train, X_val, y_val, n_trials=n_trials)
        if has_test:
            lgb_test = evaluate_on_test(lgb_model, X_test, y_test, "lightgbm")
        else:
            y_prob = lgb_model.predict_proba(X_val)
            lgb_test = compute_all_metrics(y_val.values, y_prob)
        results["lightgbm"] = {"model": lgb_model, "run_id": run.info.run_id, **lgb_test}

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
