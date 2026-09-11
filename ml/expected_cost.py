"""Expected-cost model: learn what a work should cost, then measure the gap.

Peer groups are too coarse to price a work. A 100-metre lane and a 2-kilometre
highway are both "Road / Pavement", so the peer median sits between them and a
genuine overcharge hides inside the ordinary spread. Measured on this data the
median peer group has a MAD of 0.335 log-rupees, which means a fourfold
overcharge is under three robust deviations and escapes a peer-MAD test.

Instead we predict ``log(sanction_amount)`` from what the work actually is: its
type, state, chamber, fiscal year, any quantity stated in the description, and
the description embedding reduced by SVD. The residual, actual minus predicted,
is the cost signal.

Predictions are **out-of-fold**: every work is priced by a model that never saw
it. Without that, an overpriced work teaches the model to expect its own
inflated price and the residual collapses to zero.

This does not touch ``anomaly_label`` and is not covered by the leakage rule;
the target is the sanctioned amount, which is an observable fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config
from ml.gpu import fit_with_fallback, xgb_params


@dataclass
class ExpectedCostResult:
    """Out-of-fold cost predictions and the residual signals built from them."""

    predicted_log_amount: pd.Series
    residual: pd.Series
    residual_z: pd.Series
    unit_rate_pct: pd.Series
    cost_signal: pd.Series
    metrics: dict[str, Any] = field(default_factory=dict)


def _embedding_components(
    embeddings: np.ndarray | None, cfg: dict[str, Any], n_rows: int
) -> np.ndarray:
    """Reduce description embeddings with SVD, or return nothing if unavailable."""
    if embeddings is None or len(embeddings) != n_rows:
        return np.zeros((n_rows, 0), dtype="float32")

    from sklearn.decomposition import TruncatedSVD

    n_components = int(cfg["expected_cost"]["svd_components"])
    n_components = min(n_components, embeddings.shape[1] - 1, max(1, n_rows - 1))
    svd = TruncatedSVD(n_components=n_components, random_state=int(cfg["seed"]))
    return svd.fit_transform(embeddings).astype("float32")


def _design_matrix(
    df: pd.DataFrame,
    quantities: pd.DataFrame,
    components: np.ndarray,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Assemble the predictors: what the work is, not what it cost."""
    matrix = pd.DataFrame(index=df.index)

    matrix["log_quantity"] = np.log1p(quantities["quantity"].fillna(0.0))
    matrix["has_quantity"] = quantities["quantity"].notna().astype("int8")

    start = int(cfg["features"]["fiscal_year_start_month"])
    month = df["sanction_date"].dt.month
    year = df["sanction_date"].dt.year
    matrix["fiscal_year"] = np.where(month >= start, year, year - 1).astype("float64")
    matrix["description_length"] = df["work_description"].fillna("").astype(str).str.len()

    for column in ("work_type", "state", "chamber", "work_category"):
        matrix[column] = df[column].astype(str).astype("category")
    matrix["quantity_unit"] = quantities["quantity_unit"].fillna("none").astype("category")

    for i in range(components.shape[1]):
        matrix[f"emb_{i:02d}"] = components[:, i]

    return matrix


def fit_predict(
    df: pd.DataFrame,
    quantities: pd.DataFrame,
    embeddings: np.ndarray | None = None,
    cfg: dict[str, Any] | None = None,
) -> ExpectedCostResult:
    """Fit the expected-cost model out-of-fold and build the cost signal."""
    cfg = cfg or load_config("ml")
    ecfg = cfg["expected_cost"]
    seed = int(cfg["seed"])

    import xgboost as xgb
    from sklearn.model_selection import KFold

    amount = pd.to_numeric(df["sanction_amount"], errors="coerce").astype("float64")
    target = np.log1p(amount.clip(lower=0))

    components = _embedding_components(embeddings, cfg, len(df))
    matrix = _design_matrix(df, quantities, components, cfg)

    params = xgb_params(dict(ecfg["xgb"]))
    params.update({"random_state": seed, "enable_categorical": True})

    def factory(p: dict[str, Any]) -> Any:
        return xgb.XGBRegressor(**p)

    n_splits = int(ecfg["n_splits"])
    predictions = pd.Series(np.nan, index=df.index, dtype="float64")
    device = "cpu"

    splitter = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for train_idx, test_idx in splitter.split(matrix):
        model, device = fit_with_fallback(
            factory, params, matrix.iloc[train_idx], target.iloc[train_idx]
        )
        model.get_booster().set_param({"device": "cpu"})
        predictions.iloc[test_idx] = model.predict(matrix.iloc[test_idx])

    residual = (target - predictions).rename("cost_residual")

    # Robust z of the residual within work type: a type whose costs are
    # inherently noisy should need a bigger gap to look wrong.
    from ml.features import robust_z

    residual_z = robust_z(
        residual, df["work_type"].astype(str), cfg, min_mad=float(ecfg["min_residual_mad"])
    ).rename("cost_residual_z")

    unit_pct = (
        quantities["unit_rate_pct"]
        if "unit_rate_pct" in quantities.columns
        else pd.Series(np.nan, index=df.index)
    )
    signal = _combine(residual_z, unit_pct, cfg)

    mae = float(np.abs(residual).mean())
    metrics = {
        "n_rows": int(len(df)),
        "n_splits": n_splits,
        "device": device,
        "svd_components": int(components.shape[1]),
        "mae_log_rupees": round(mae, 4),
        "mae_as_cost_ratio": round(float(np.exp(mae)), 3),
        "residual_std": round(float(residual.std()), 4),
        "residual_mad": round(float((residual - residual.median()).abs().median()), 4),
        "r2": round(
            float(1 - residual.var() / target.var()) if float(target.var()) > 0 else 0.0, 4
        ),
        "note": (
            "Out-of-fold predictions: every work is priced by a model that never "
            "saw it. mae_as_cost_ratio is the typical multiplicative error, so "
            "1.6 means predictions are typically within about 1.6x."
        ),
    }

    return ExpectedCostResult(
        predicted_log_amount=predictions.rename("expected_log_amount"),
        residual=residual,
        residual_z=residual_z,
        unit_rate_pct=unit_pct.rename("unit_rate_pct"),
        cost_signal=signal.rename("cost_signal"),
        metrics=metrics,
    )


def _combine(residual_z: pd.Series, unit_rate_pct: pd.Series, cfg: dict[str, Any]) -> pd.Series:
    """Blend the residual z and the unit-rate percentile, taking the stronger.

    Both are mapped to 0-1 where 1 means "much more expensive than expected".
    Only overcharging is scored: a work costing less than predicted is a
    different question and not a fraud indicator on its own.
    """
    ecfg = cfg["expected_cost"]
    z_start = float(ecfg["signal_z_start"])
    z_full = float(ecfg["signal_z_full"])
    pct_start = float(ecfg["unit_rate_pct_start"])

    from_z = ((residual_z - z_start) / max(1e-9, z_full - z_start)).clip(0.0, 1.0).fillna(0.0)
    from_rate = (
        ((unit_rate_pct - pct_start) / max(1e-9, 1.0 - pct_start)).clip(0.0, 1.0).fillna(0.0)
    )
    return pd.concat([from_z, from_rate], axis=1).max(axis=1)
