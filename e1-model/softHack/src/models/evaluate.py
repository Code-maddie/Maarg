"""Model evaluation metrics, diagnostic curves, and reporting for E1."""

import os
from typing import Dict, Any, Tuple
import numpy as np
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt

from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    brier_score_loss,
    log_loss,
    confusion_matrix,
    roc_curve,
    precision_recall_curve
)
from sklearn.calibration import calibration_curve


def compute_classification_metrics(y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.5) -> Dict[str, Any]:
    """
    Computes standard evaluation metrics for probability predictions:
    ROC-AUC, PR-AUC, accuracy, precision, recall, F1, Brier score, log loss, confusion matrix.
    """
    y_pred = (y_prob >= threshold).astype(int)
    cm = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel()

    metrics = {
        "roc_auc": float(roc_auc_score(y_true, y_prob)),
        "pr_auc": float(average_precision_score(y_true, y_prob)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "brier_score": float(brier_score_loss(y_true, y_prob)),
        "log_loss": float(log_loss(y_true, y_prob)),
        "threshold": float(threshold),
        "confusion_matrix": {
            "tn": int(tn),
            "fp": int(fp),
            "fn": int(fn),
            "tp": int(tp)
        },
        "sample_count": int(len(y_true)),
        "positive_count": int(y_true.sum()),
        "positive_rate": float(y_true.mean())
    }
    return metrics


def plot_and_save_curves(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    output_dir: str = "artifacts/misplacement_classifier/v1",
    model_name: str = "E1 Production Model"
) -> Dict[str, str]:
    """Generates and saves Confusion Matrix, ROC Curve, PR Curve, and Calibration Curve plots."""
    os.makedirs(output_dir, exist_ok=True)
    paths = {}

    y_pred = (y_prob >= 0.5).astype(int)
    cm = confusion_matrix(y_true, y_pred)

    # 1. Confusion Matrix
    cm_path = os.path.join(output_dir, "confusion_matrix.png")
    fig, ax = plt.subplots(figsize=(5, 4))
    im = ax.imshow(cm, interpolation='nearest', cmap=plt.cm.Blues)
    ax.figure.colorbar(im, ax=ax)
    classes = ["Normal (0)", "Disrupted (1)"]
    ax.set(xticks=np.arange(cm.shape[1]),
           yticks=np.arange(cm.shape[0]),
           xticklabels=classes, yticklabels=classes,
           title=f"Confusion Matrix: {model_name}",
           ylabel="True label",
           xlabel="Predicted label")
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, format(cm[i, j], 'd'),
                    ha="center", va="center",
                    color="white" if cm[i, j] > cm.max() / 2. else "black")
    fig.tight_layout()
    fig.savefig(cm_path, dpi=150)
    plt.close(fig)
    paths["confusion_matrix_plot"] = cm_path

    # 2. ROC Curve
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    auc_val = roc_auc_score(y_true, y_prob)
    roc_path = os.path.join(output_dir, "roc_curve.png")
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(fpr, tpr, color="darkorange", lw=2, label=f"ROC curve (AUC = {auc_val:.3f})")
    ax.plot([0, 1], [0, 1], color="navy", lw=1, linestyle="--")
    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.05])
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title(f"ROC Curve: {model_name}")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(roc_path, dpi=150)
    plt.close(fig)
    paths["roc_curve_plot"] = roc_path

    # 3. Precision-Recall Curve
    prec, rec, _ = precision_recall_curve(y_true, y_prob)
    pr_auc_val = average_precision_score(y_true, y_prob)
    pr_path = os.path.join(output_dir, "pr_curve.png")
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(rec, prec, color="green", lw=2, label=f"PR curve (PR-AUC = {pr_auc_val:.3f})")
    ax.axhline(y=y_true.mean(), color="grey", linestyle="--", label=f"Baseline ({y_true.mean():.3f})")
    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.05])
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title(f"Precision-Recall Curve: {model_name}")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(pr_path, dpi=150)
    plt.close(fig)
    paths["pr_curve_plot"] = pr_path

    # 4. Calibration Curve
    prob_true, prob_pred = calibration_curve(y_true, y_prob, n_bins=10, strategy="uniform")
    brier_val = brier_score_loss(y_true, y_prob)
    cal_path = os.path.join(output_dir, "calibration_curve.png")
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(prob_pred, prob_true, "s-", color="blue", label=f"Model (Brier = {brier_val:.4f})")
    ax.plot([0, 1], [0, 1], "--", color="gray", label="Perfectly calibrated")
    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.0])
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Fraction of positives")
    ax.set_title(f"Calibration Curve: {model_name}")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(cal_path, dpi=150)
    plt.close(fig)
    paths["calibration_curve_plot"] = cal_path

    print(f"Evaluation plots saved to {output_dir}")
    return paths
