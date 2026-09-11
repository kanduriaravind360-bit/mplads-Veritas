"""Delay prediction.

This is the one model in the pipeline trained on a **real observed outcome**
rather than the proxy label: did a work finish within a year of sanction?

Two rules keep it honest:

* **Sanction-time features only.** Nothing that becomes known after sanction
  (disbursement, payments, completion, current status) may be an input,
  otherwise the model would be reading the answer.
* **Strictly historical context.** IDA and vendor track records are computed
  with an expanding window over earlier sanctions only. A work never sees its
  own outcome, or any later work's, in its own features.

Evaluation uses a time-based split: train on older sanctions, test on newer
ones. That matches how the model would actually be used and avoids the
optimism of a random split on time-ordered data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config
from ml.features import cutoff_date
from ml.gpu import fit_with_fallback, xgb_params

#: Inputs available at the moment a work is sanctioned.
SANCTION_TIME_FEATURES: tuple[str, ...] = (
    "log_amount",
    "days_to_sanction",
    "sanction_month",
    "is_march_sanction",
    "fiscal_year",
    "ida_prior_works",
    "ida_prior_delay_rate",
    "ida_prior_median_days_to_sanction",
    "vendor_prior_works",
    "vendor_prior_delay_rate",
)

_CATEGORICALS: tuple[str, ...] = ("work_type", "state", "chamber", "work_category")


@dataclass
class DelayResult:
    """Trained delay model, its metrics and its predictions."""

    model: Any
    metrics: dict[str, Any]
    predictions: pd.Series
    reasons: pd.Series
    features: list[str] = field(default_factory=list)
    device: str = "cpu"


def build_labels(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> pd.Series:
    """``delayed = 1`` when a work did not finish within the horizon.

    Only works sanctioned at least ``horizon_days`` before the cut-off are
    labelled; anything younger has not had time to be late, so labelling it
    would inject noise. Everything else is NA.
    """
    cfg = cfg or load_config("ml")
    horizon = int(cfg["delay"]["horizon_days"])
    cutoff = cutoff_date(df, cfg)

    mature = (cutoff - df["sanction_date"]).dt.days >= horizon
    completed_in_time = df["completion_date"].notna() & (
        (df["completion_date"] - df["sanction_date"]).dt.days <= horizon
    )
    labels = pd.Series(pd.NA, index=df.index, dtype="Int64")
    labels[mature] = (~completed_in_time[mature]).astype("int64")
    return labels.rename("delayed")


def _expanding_history(df: pd.DataFrame, key: str, horizon: int) -> pd.DataFrame:
    """Prior-only track record per ``key``, in sanction order.

    For each row: how many works that IDA or vendor had sanctioned *before*
    this one, and what fraction of those ran late. Uses shifted cumulative
    sums so the current row is never part of its own history.
    """
    order = df.sort_values(["sanction_date", "work_id"], kind="stable")
    grp = order.groupby(key, observed=True)

    prior_n = grp.cumcount()
    was_late = (
        order["completion_date"].isna()
        | ((order["completion_date"] - order["sanction_date"]).dt.days > horizon)
    ).astype("float64")
    # Subtracting the row's own value turns an inclusive cumulative sum into a
    # strictly prior one, so no work contributes to its own history.
    prior_late = was_late.groupby(order[key], observed=True).cumsum() - was_late
    dts = order["days_to_sanction"].astype("float64")
    prior_dts_sum = dts.groupby(order[key], observed=True).cumsum() - dts

    out = pd.DataFrame(
        {
            f"{key}_prior_works": prior_n.astype("float64"),
            f"{key}_prior_delay_rate": (prior_late / prior_n.replace(0, np.nan)).fillna(0.0),
            f"{key}_prior_mean_days_to_sanction": (
                prior_dts_sum / prior_n.replace(0, np.nan)
            ).fillna(0.0),
        },
        index=order.index,
    )
    return out.reindex(df.index)


def build_matrix(
    df: pd.DataFrame, cfg: dict[str, Any] | None = None
) -> tuple[pd.DataFrame, list[str]]:
    """Assemble the sanction-time design matrix, with historical-only context."""
    cfg = cfg or load_config("ml")
    horizon = int(cfg["delay"]["horizon_days"])

    ida_hist = _expanding_history(df, "ida", horizon)
    vendor_hist = _expanding_history(df.assign(vendor=df["vendor_name"]), "vendor", horizon)

    matrix = pd.DataFrame(index=df.index)
    matrix["log_amount"] = np.log1p(df["sanction_amount"].astype("float64").clip(lower=0))
    matrix["days_to_sanction"] = df["days_to_sanction"].astype("float64")
    matrix["sanction_month"] = df["sanction_date"].dt.month.astype("float64")
    matrix["is_march_sanction"] = (df["sanction_date"].dt.month == 3).astype("int8")
    start = int(cfg["features"]["fiscal_year_start_month"])
    year = df["sanction_date"].dt.year
    matrix["fiscal_year"] = np.where(df["sanction_date"].dt.month >= start, year, year - 1).astype(
        "float64"
    )

    matrix["ida_prior_works"] = ida_hist["ida_prior_works"]
    matrix["ida_prior_delay_rate"] = ida_hist["ida_prior_delay_rate"]
    matrix["ida_prior_median_days_to_sanction"] = ida_hist["ida_prior_mean_days_to_sanction"]
    matrix["vendor_prior_works"] = vendor_hist["vendor_prior_works"]
    matrix["vendor_prior_delay_rate"] = vendor_hist["vendor_prior_delay_rate"]

    # Fill numerics before adding the categoricals: fillna(0.0) is invalid on a
    # categorical dtype, and XGBoost handles categorical NA natively anyway.
    matrix = matrix.fillna(0.0)
    for col in _CATEGORICALS:
        matrix[col] = df[col].astype(str).astype("category")

    return matrix, list(matrix.columns)


def train(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> DelayResult:
    """Train the delay model, score every work, and explain each prediction."""
    cfg = cfg or load_config("ml")
    dcfg = cfg["delay"]
    seed = int(cfg["seed"])

    import xgboost as xgb
    from sklearn.metrics import average_precision_score, roc_auc_score

    labels = build_labels(df, cfg)
    matrix, names = build_matrix(df, cfg)

    labelled = labels.notna()
    x_all = matrix.loc[labelled]
    y_all = labels.loc[labelled].astype("int64")
    dates = df.loc[labelled, "sanction_date"]

    order = np.argsort(dates.to_numpy(), kind="stable")
    n_test = max(1, int(len(order) * float(dcfg["test_fraction"])))
    train_idx, test_idx = order[:-n_test], order[-n_test:]

    params = xgb_params(dict(dcfg["xgb"]))
    params.update({"random_state": seed, "enable_categorical": True, "eval_metric": "aucpr"})

    def factory(p: dict[str, Any]) -> Any:
        return xgb.XGBClassifier(**p)

    model, device = fit_with_fallback(factory, params, x_all.iloc[train_idx], y_all.iloc[train_idx])

    test_pred = model.predict_proba(x_all.iloc[test_idx])[:, 1]
    y_test = y_all.iloc[test_idx]
    metrics: dict[str, Any] = {
        "n_labelled": int(labelled.sum()),
        "n_train": int(len(train_idx)),
        "n_test": int(len(test_idx)),
        "delay_rate_train": float(y_all.iloc[train_idx].mean()),
        "delay_rate_test": float(y_test.mean()),
        "train_sanction_max": str(dates.iloc[train_idx].max().date()),
        "test_sanction_min": str(dates.iloc[test_idx].min().date()),
        "device": device,
        "split": "time-based: oldest sanctions train, newest test",
        "horizon_days": int(dcfg["horizon_days"]),
    }
    if y_test.nunique() > 1:
        metrics["roc_auc"] = float(roc_auc_score(y_test, test_pred))
        metrics["pr_auc"] = float(average_precision_score(y_test, test_pred))
    else:
        metrics["roc_auc"] = None
        metrics["pr_auc"] = None

    # Refit on everything labelled before scoring the live population.
    final, device = fit_with_fallback(factory, params, x_all, y_all)
    predictions = pd.Series(final.predict_proba(matrix)[:, 1], index=df.index, name="delay_risk")
    # Delay risk is only meaningful for works that are still open.
    predictions = predictions.where(df["completion_date"].isna(), 0.0)

    reasons = _shap_reasons(final, matrix, names, cfg, mask=df["completion_date"].isna())
    return DelayResult(
        model=final,
        metrics=metrics,
        predictions=predictions,
        reasons=reasons,
        features=names,
        device=device,
    )


def _shap_reasons(
    model: Any,
    matrix: pd.DataFrame,
    names: list[str],
    cfg: dict[str, Any],
    mask: pd.Series,
) -> pd.Series:
    """Top contributing features per row, by SHAP value.

    Only rows in ``mask`` are explained, and only up to ``shap_sample`` of them,
    because SHAP on the full population is the slowest part of the pipeline and
    nobody reads an explanation for a work that is already finished.
    """
    top_k = int(cfg["delay"]["shap_top"])
    cap = int(cfg["delay"]["shap_sample"])
    seed = int(cfg["seed"])

    out = pd.Series([[] for _ in range(len(matrix))], index=matrix.index, dtype="object")
    candidates = matrix.index[mask.to_numpy()]
    if len(candidates) == 0:
        return out.rename("delay_reasons")
    if len(candidates) > cap:
        candidates = pd.Index(
            np.random.default_rng(seed).choice(candidates.to_numpy(), size=cap, replace=False)
        )

    subset = matrix.loc[candidates]
    booster = model.get_booster()
    import xgboost as xgb

    dmatrix = xgb.DMatrix(subset, enable_categorical=True)
    contribs = booster.predict(dmatrix, pred_contribs=True)[:, :-1]

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
    return out.rename("delay_reasons")
