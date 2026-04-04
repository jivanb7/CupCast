"""
ml/src/evaluate.py
===================
Evaluation metrics, plots, and MLFlow logging utilities.
"""

import logging
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    roc_auc_score,
)

from ml.src.config import RESULT_LABELS

logger = logging.getLogger(__name__)


def compute_all_metrics(y_true: np.ndarray, y_prob: np.ndarray) -> dict:
    """
    Compute all scalar evaluation metrics.

    Parameters
    ----------
    y_true : array-like of int (0=H, 1=D, 2=A)
    y_prob : array of shape (n_samples, 3) -- predicted probabilities

    Returns dict with keys: accuracy, f1_macro, log_loss_val, roc_auc_macro, brier_score
    """
    y_pred = np.argmax(y_prob, axis=1)

    metrics = {
        "accuracy": accuracy_score(y_true, y_pred),
        "f1_macro": f1_score(y_true, y_pred, average="macro"),
        "log_loss": log_loss(y_true, y_prob, labels=[0, 1, 2]),
    }

    # ROC-AUC (one-vs-rest, macro)
    try:
        metrics["roc_auc_macro"] = roc_auc_score(
            y_true, y_prob, multi_class="ovr", average="macro"
        )
    except ValueError:
        # May fail if a class has no samples in y_true
        metrics["roc_auc_macro"] = 0.0

    # Brier score: average across classes
    brier_scores = []
    for cls in range(y_prob.shape[1]):
        y_binary = (y_true == cls).astype(int)
        brier_scores.append(brier_score_loss(y_binary, y_prob[:, cls]))
    metrics["brier_score"] = np.mean(brier_scores)

    return metrics


def log_confusion_matrix(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    labels: list[str] = RESULT_LABELS,
    artifact_name: str = "confusion_matrix.png",
) -> None:
    """Generate and log a confusion matrix plot to the active MLFlow run."""
    fig, ax = plt.subplots(figsize=(6, 5))
    cm = confusion_matrix(y_true, y_pred)
    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=labels)
    disp.plot(ax=ax, cmap="Blues")
    ax.set_title("Confusion Matrix")
    plt.tight_layout()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        fig.savefig(f.name, dpi=100)
        mlflow.log_artifact(f.name, artifact_path="plots")
    plt.close(fig)
    logger.info("Logged confusion matrix to MLFlow")


def log_calibration_curve(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    artifact_name: str = "calibration_curve.png",
) -> None:
    """Generate and log calibration curves (one per class) to MLFlow."""
    fig, ax = plt.subplots(figsize=(7, 6))
    class_names = ["Home Win", "Draw", "Away Win"]

    for cls in range(y_prob.shape[1]):
        y_binary = (y_true == cls).astype(int)
        prob_true, prob_pred = calibration_curve(
            y_binary, y_prob[:, cls], n_bins=10, strategy="uniform"
        )
        ax.plot(prob_pred, prob_true, marker="o", label=class_names[cls])

    ax.plot([0, 1], [0, 1], "k--", label="Perfectly calibrated")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Fraction of positives")
    ax.set_title("Calibration Curves")
    ax.legend()
    plt.tight_layout()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        fig.savefig(f.name, dpi=100)
        mlflow.log_artifact(f.name, artifact_path="plots")
    plt.close(fig)
    logger.info("Logged calibration curve to MLFlow")


def log_feature_importance(
    model,
    feature_names: list[str],
    model_type: str = "xgboost",
    artifact_name: str = "feature_importance.png",
    top_n: int = 30,
) -> None:
    """Generate and log a feature importance bar chart to MLFlow."""
    # Extract importances
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    elif hasattr(model, "coef_"):
        # Logistic Regression: use max abs coef across classes
        importances = np.abs(model.coef_).mean(axis=0)
    else:
        logger.warning("Model type %s doesn't support feature importance", type(model))
        return

    # Sort and select top N
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

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        fig.savefig(f.name, dpi=100)
        mlflow.log_artifact(f.name, artifact_path="plots")
    plt.close(fig)
    logger.info("Logged feature importance plot to MLFlow")
