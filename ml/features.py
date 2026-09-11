"""Leak-safe feature engineering.

Every feature here is computable from observable facts about a work. None of
them touch ``flag_*``, ``anomaly_score`` or ``flag_reasons`` (CLAUDE.md rule 3);
:func:`assert_leak_safe` enforces that and is exercised by the test suite.

Two decisions worth knowing about:

* **Robust cost z-scores.** The dataset's own ``cost_zscore`` uses mean and
  standard deviation on a heavily right-skewed amount, so a handful of very
  large works drag the mean up and inflate the standard deviation, which hides
  genuine outliers. We instead take the median and MAD of ``log_amount`` within
  a peer group.
* **Peer groups.** ``work_category`` is 97.7% "Normal/Others" and therefore
  useless. Peers are ``work_type`` x ``state``, falling back to ``work_type``
  nationally when a group is thinner than ``features.peer_min_group``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config, resolve
from ml.data import LEAKY_COLUMNS

#: Columns produced here that describe the work but are not model inputs.
ID_COLUMNS: tuple[str, ...] = ("work_id", "peer_group", "peer_n")


def cutoff_date(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> pd.Timestamp:
    """The "today" used for every age calculation.

    Config wins if set; otherwise the latest date anywhere in the data, so the
    pipeline is reproducible and never depends on when it happens to be run.
    """
    cfg = cfg or load_config("ml")
    configured = cfg.get("cutoff_date")
    if configured:
        return pd.Timestamp(configured)
    cols = ["recommended_date", "sanction_date", "completion_date", "latest_expenditure_date"]
    return max(df[c].max() for c in cols if c in df.columns)


def robust_z(
    values: pd.Series,
    groups: pd.Series,
    cfg: dict[str, Any],
    min_mad: float | None = None,
) -> pd.Series:
    """Median/MAD z-score of ``values`` within ``groups``.

    Robust to the long right tail of sanction amounts, unlike a mean/std score.

    ``min_mad`` floors the deviation in the variable's own units. Many peer
    groups share a single amount or turnaround time, giving MAD = 0; without a
    floor every row that differs at all scores infinity. The result is clipped
    to ``features.z_clip`` because past that point everything is equally
    extreme and the tail only adds noise.
    """
    fcfg = cfg["features"]
    scale = float(fcfg["mad_scale"])
    floor = float(fcfg["min_mad"]) if min_mad is None else float(min_mad)
    clip = float(fcfg["z_clip"])

    med = values.groupby(groups).transform("median")
    mad = (values - med).abs().groupby(groups).transform("median")
    z = (values - med) / (scale * mad.clip(lower=floor))
    return z.clip(lower=-clip, upper=clip)


def _percentile_within(values: pd.Series, groups: pd.Series) -> pd.Series:
    """Rank of each value within its group, scaled to [0, 1]."""
    return values.groupby(groups).rank(pct=True, method="average")


def build_peer_groups(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Attach ``peer_group`` and ``peer_n``.

    Peers are work_type x state where that group is large enough to estimate a
    median and MAD from, otherwise work_type nationally.
    """
    cfg = cfg or load_config("ml")
    min_n = int(cfg["features"]["peer_min_group"])

    fine = df["work_type"].astype(str) + " | " + df["state"].astype(str)
    counts = fine.map(fine.value_counts())
    coarse = df["work_type"].astype(str) + " | ALL-INDIA"

    out = df.copy()
    out["peer_group"] = np.where(counts >= min_n, fine, coarse)
    out["peer_n"] = out["peer_group"].map(out["peer_group"].value_counts())
    return out


def _cost_features(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    unit = float(cfg["features"]["round_amount_unit"])
    out = pd.DataFrame(index=df.index)
    amount = df["sanction_amount"].astype("float64")

    out["log_amount"] = np.log1p(amount.clip(lower=0))
    out["cost_robust_z"] = robust_z(out["log_amount"], df["peer_group"], cfg)
    out["cost_pct_in_type"] = _percentile_within(amount, df["work_type"].astype(str))
    out["amount_vs_peer_median"] = amount / amount.groupby(df["peer_group"]).transform(
        "median"
    ).replace(0, np.nan)
    out["is_round_lakh"] = ((amount > 0) & (amount % unit == 0)).astype("int8")
    return out


def _time_features(df: pd.DataFrame, cfg: dict[str, Any], cutoff: pd.Timestamp) -> pd.DataFrame:
    fcfg = cfg["features"]
    out = pd.DataFrame(index=df.index)
    wtype = df["work_type"].astype(str)

    day_floor = float(fcfg["min_mad_days"])
    dts = df["days_to_sanction"].astype("float64")
    out["days_to_sanction"] = dts
    out["days_to_sanction_z"] = robust_z(dts, wtype, cfg, min_mad=day_floor)

    duration = df["duration_days"].astype("float64")
    out["duration_days"] = duration
    out["duration_pct_in_type"] = _percentile_within(duration, wtype)

    # Age of still-open works. Completed works get 0 so the column means
    # "how long has this been sitting unfinished", not "how old is the record".
    is_open = df["completion_date"].isna()
    age = (cutoff - df["sanction_date"]).dt.days.astype("float64")
    out["days_since_sanction_open"] = np.where(is_open, age, 0.0)
    out["is_open"] = is_open.astype("int8")

    month = df["sanction_date"].dt.month
    out["sanction_month"] = month.astype("float64")
    out["is_march_sanction"] = (month == int(fcfg["march_month"])).astype("int8")

    start = int(fcfg["fiscal_year_start_month"])
    year = df["sanction_date"].dt.year
    out["fiscal_year"] = np.where(month >= start, year, year - 1).astype("float64")
    return out


def _money_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    sanctioned = df["sanction_amount"].astype("float64").replace(0, np.nan)
    disbursed = df["total_fund_disbursed"].astype("float64")

    out["disbursed_ratio"] = (disbursed / sanctioned).fillna(0.0)
    out["num_payments"] = df["num_payments"].astype("float64").fillna(0.0)
    out["payment_in_progress"] = (
        df["latest_payment_status"].astype(str) == "Payment In-Progress"
    ).astype("int8")
    out["disbursed_but_not_complete"] = (
        (out["disbursed_ratio"] > 0) & df["completion_date"].isna()
    ).astype("int8")
    out["has_vendor"] = df["vendor_name"].notna().astype("int8")
    return out


def _status_features(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    order: dict[str, int] = cfg["features"]["stage_order"]
    default = int(order.get("Unknown", 0))
    out = pd.DataFrame(index=df.index)
    out["stage_ordinal"] = (
        df["work_status"].astype(str).map(order).fillna(default).astype("float64")
    )
    return out


def _vendor_features(df: pd.DataFrame, cost_z: pd.Series) -> pd.DataFrame:
    """Vendor concentration and reach.

    Vendors are identified by name, which is imperfect but is what the data
    gives us. Roughly 20% of works have no vendor recorded; those get zeros,
    with ``has_vendor`` carrying the distinction.
    """
    out = pd.DataFrame(index=df.index)
    vendor = df["vendor_name"]
    known = vendor.notna()

    total = vendor.map(vendor.value_counts())
    out["vendor_total_works"] = total.fillna(0.0).astype("float64")

    pair = vendor.astype(str) + " | " + df["ida"].astype(str)
    in_ida = pair.map(pair.value_counts()).where(known)
    out["vendor_works_in_ida"] = in_ida.fillna(0.0).astype("float64")

    ida_size = df["ida"].map(df["ida"].value_counts()).astype("float64")
    out["vendor_share_of_ida"] = (out["vendor_works_in_ida"] / ida_size.replace(0, np.nan)).fillna(
        0.0
    )

    known_rows = df.loc[known]
    n_mps = known_rows.groupby("vendor_name", observed=True)["mp_name"].nunique()
    n_states = known_rows.groupby("vendor_name", observed=True)["state"].nunique()
    out["vendor_n_mps"] = vendor.map(n_mps).fillna(0.0).astype("float64")
    out["vendor_n_states"] = vendor.map(n_states).fillna(0.0).astype("float64")

    med_z = cost_z.where(known).groupby(vendor).median()
    out["vendor_median_cost_z"] = vendor.map(med_z).fillna(0.0).astype("float64")
    return out


def _context_features(df: pd.DataFrame) -> pd.DataFrame:
    """IDA and MP context, including vendor concentration (HHI) within the IDA.

    HHI is the sum of squared vendor shares: 1.0 means one vendor holds every
    work in the district, low values mean a competitive spread.
    """
    out = pd.DataFrame(index=df.index)

    for key, prefix in (("ida", "ida"), ("mp_name", "mp")):
        grp = df.groupby(key, observed=True)
        out[f"{prefix}_works"] = df[key].map(grp.size()).astype("float64")
        out[f"{prefix}_median_days_to_sanction"] = (
            df[key].map(grp["days_to_sanction"].median()).astype("float64")
        )
        completion = grp["completion_date"].apply(lambda s: s.notna().mean())
        out[f"{prefix}_completion_rate"] = df[key].map(completion).astype("float64")

    known = df["vendor_name"].notna()
    pair_counts = (
        df.loc[known]
        .groupby(["ida", "vendor_name"], observed=True)
        .size()
        .rename("n")
        .reset_index()
    )
    totals = pair_counts.groupby("ida", observed=True)["n"].transform("sum")
    pair_counts["share_sq"] = (pair_counts["n"] / totals) ** 2
    hhi = pair_counts.groupby("ida", observed=True)["share_sq"].sum()
    out["ida_vendor_hhi"] = df["ida"].map(hhi).fillna(0.0).astype("float64")
    return out


def build_features(
    df: pd.DataFrame, cfg: dict[str, Any] | None = None
) -> tuple[pd.DataFrame, list[str]]:
    """Build the full leak-safe feature matrix.

    Returns ``(frame, feature_names)`` where ``frame`` also carries ``work_id``,
    ``peer_group`` and ``peer_n`` for joining and explanation. Those three are
    excluded from ``feature_names``.
    """
    cfg = cfg or load_config("ml")
    if "work_type" not in df.columns:
        raise ValueError("build_features needs a work_type column; run ml.work_type first")

    base = build_peer_groups(df, cfg)
    cutoff = cutoff_date(base, cfg)

    cost = _cost_features(base, cfg)
    parts = [
        cost,
        _time_features(base, cfg, cutoff),
        _money_features(base),
        _status_features(base, cfg),
        _vendor_features(base, cost["cost_robust_z"]),
        _context_features(base),
    ]
    feats = pd.concat(parts, axis=1)
    feats = feats.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    names = [c for c in feats.columns if c not in ID_COLUMNS]
    feats.insert(0, "work_id", base["work_id"].to_numpy())
    feats["peer_group"] = base["peer_group"].to_numpy()
    feats["peer_n"] = base["peer_n"].to_numpy()

    assert_leak_safe(names)
    return feats, names


def assert_leak_safe(feature_names: list[str]) -> None:
    """Raise if any feature name leaks the proxy label (CLAUDE.md rule 3)."""
    banned = set(LEAKY_COLUMNS) | {"anomaly_label"}
    hits = [f for f in feature_names if f in banned or f.startswith("flag_")]
    if hits:
        raise ValueError(f"LEAKAGE: these must never be model features: {hits}")


def save_feature_list(feature_names: list[str], cfg: dict[str, Any] | None = None) -> Path:
    """Write the feature list to ``models/feature_list.json``."""
    cfg = cfg or load_config("ml")
    path = resolve(cfg["paths"]["feature_list"])
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "n_features": len(feature_names),
        "features": sorted(feature_names),
        "excluded_leaky_columns": sorted(set(LEAKY_COLUMNS) | {"anomaly_label"}),
        "note": (
            "Leak-safe feature list. flag_*, anomaly_score, flag_reasons and "
            "anomaly_label are never inputs (CLAUDE.md rule 3)."
        ),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
