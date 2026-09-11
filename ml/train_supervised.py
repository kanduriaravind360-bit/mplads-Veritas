"""Supervised model on the PROXY label.

**Read this before quoting any number from here.** ``anomaly_label`` is not
confirmed fraud. It is ``anomaly_score >= 4``, where ``anomaly_score`` is a
weighted sum of seven hand-written flags (CLAUDE.md rule 3). A model fitted to
it learns to *reproduce and generalise that rule set*, nothing more. A strong
score here means the rules are learnable from observable data, not that fraud
was detected. The caveat travels with the metrics in ``models/metrics.json``.

The model is still worth having: it generalises the rules to works whose flags
did not quite trip, and it ranks within the large "some flags fired" middle that
the binary rule cannot separate.

Two safeguards:

* **No leakage.** Inputs come from the leak-safe feature list only. The flag
  columns that *define* the label are never inputs; :func:`ml.features.assert_leak_safe`
  is called before training.
* **GroupKFold by constituency.** The same area never appears in both train and
  test, so the model cannot memorise local quirks and call it generalisation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config
from ml.features import assert_leak_safe
from ml.gpu import fit_with_fallback, xgb_params

PROXY_LABEL_CAVEAT = (
    "anomaly_label is a rule-based PROXY, not confirmed fraud: it equals "
    "(anomaly_score >= 4) where anomaly_score is a weighted sum of 7 hand-written "
    "flags. This model learns to reproduce and generalise that rule set. Treat its "
    "output as a risk indicator for review, never as evidence of wrongdoing."
)


@dataclass
class SupervisedResult:
    """Trained proxy-label model with out-of-fold predictions and metrics."""

    model: Any
    metrics: dict[str, Any]
    predictions: pd.Series
    reasons: pd.Series
    features: list[str] = field(default_factory=list)
    device: str = "cpu"


def _precision_at_k(y_true: np.ndarray, scores: np.ndarray, k: int) -> float | None:
    """Share of true positives among the k highest-scoring works."""
    if k > len(scores):
        return None
    top = np.argpartition(-scores, kth=k - 1)[:k]
    return float(y_true[top].mean())


def train(
    df: pd.DataFrame,
    feats: pd.DataFrame,
    names: list[str],
    cfg: dict[str, Any] | None = None,
) -> SupervisedResult:
    """Cross-validate by constituency, then refit on everything and score."""
    cfg = cfg or load_config("ml")
    scfg = cfg["supervised"]
    seed = int(cfg["seed"])
    assert_leak_safe(names)

    import xgboost as xgb
    from sklearn.metrics import average_precision_score, roc_auc_score
    from sklearn.model_selection import GroupKFold

    x = feats[names]
    y = df["anomaly_label"].astype("int64").to_numpy()
    groups = df[scfg["group_column"]].astype(str).to_numpy()

    positives = int(y.sum())
    negatives = int(len(y) - positives)
    # The positive rate is ~1.2%; without this the model predicts all-negative.
    scale_pos_weight = negatives / max(1, positives)

    params = xgb_params(dict(scfg["xgb"]))
    params.update(
        {
            "random_state": seed,
            "eval_metric": "aucpr",
            "scale_pos_weight": scale_pos_weight,
        }
    )

    def factory(p: dict[str, Any]) -> Any:
        return xgb.XGBClassifier(**p)

    n_splits = int(scfg["n_splits"])
    oof = np.zeros(len(y), dtype="float64")
    fold_scores: list[dict[str, float]] = []
    device = "cpu"

    splitter = GroupKFold(n_splits=n_splits)
    for train_idx, test_idx in splitter.split(x, y, groups=groups):
        model, device = fit_with_fallback(factory, params, x.iloc[train_idx], y[train_idx])
        model.get_booster().set_param({"device": "cpu"})
        pred = model.predict_proba(x.iloc[test_idx])[:, 1]
        oof[test_idx] = pred
        if len(np.unique(y[test_idx])) > 1:
            fold_scores.append(
                {
                    "pr_auc": float(average_precision_score(y[test_idx], pred)),
                    "roc_auc": float(roc_auc_score(y[test_idx], pred)),
                }
            )

    metrics: dict[str, Any] = {
        "n_rows": int(len(y)),
        "n_positive": positives,
        "positive_rate": float(y.mean()),
        "scale_pos_weight": float(scale_pos_weight),
        "n_splits": n_splits,
        "grouped_by": scfg["group_column"],
        "cv": "GroupKFold by constituency (no area spans train and test)",
        "device": device,
        "pr_auc_oof": float(average_precision_score(y, oof)),
        "roc_auc_oof": float(roc_auc_score(y, oof)),
        "pr_auc_folds": [round(f["pr_auc"], 4) for f in fold_scores],
        "roc_auc_folds": [round(f["roc_auc"], 4) for f in fold_scores],
        "baseline_pr_auc": float(y.mean()),
        "CAVEAT": PROXY_LABEL_CAVEAT,
    }
    for k in scfg["precision_at"]:
        metrics[f"precision_at_{k}"] = _precision_at_k(y, oof, int(k))

    final, device = fit_with_fallback(factory, params, x, y)
    final.get_booster().set_param({"device": "cpu"})
    predictions = pd.Series(oof, index=df.index, name="supervised_prob")
    reasons = _shap_reasons(final, x, names, cfg)

    return SupervisedResult(
        model=final,
        metrics=metrics,
        predictions=predictions,
        reasons=reasons,
        features=list(names),
        device=device,
    )


def _shap_reasons(model: Any, x: pd.DataFrame, names: list[str], cfg: dict[str, Any]) -> pd.Series:
    """Top positively-contributing features per row, by SHAP value."""
    scfg = cfg["supervised"]
    top_k = int(scfg["shap_top"])
    cap = int(scfg["shap_sample"])
    seed = int(cfg["seed"])

    import xgboost as xgb

    out = pd.Series([[] for _ in range(len(x))], index=x.index, dtype="object")
    candidates = x.index
    if len(candidates) > cap:
        candidates = pd.Index(
            np.random.default_rng(seed).choice(candidates.to_numpy(), size=cap, replace=False)
        )

    contribs = model.get_booster().predict(xgb.DMatrix(x.loc[candidates]), pred_contribs=True)[
        :, :-1
    ]
    arr = np.asarray(contribs)

    k = min(top_k, arr.shape[1])
    idx = np.argpartition(-np.abs(arr), kth=k - 1, axis=1)[:, :k]
    rows = np.arange(arr.shape[0])[:, None]
    order = np.argsort(-np.abs(arr[rows, idx]), axis=1)
    idx = idx[rows, order]

    feature_names = np.array(names)
    picked = [
        [(str(feature_names[c]), float(arr[r, c])) for c in idx[r] if arr[r, c] > 0]
        for r in range(arr.shape[0])
    ]
    out.loc[candidates] = pd.Series(picked, index=candidates, dtype="object")
    return out.rename("supervised_reasons")
