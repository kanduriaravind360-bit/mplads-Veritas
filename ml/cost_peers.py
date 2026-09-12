"""State-relative cost channel: is this work expensive for ITS state?

The expected-cost model prices a work from its description, type and state, but
it is trained nationally, so it inherits the national spread of prices. A solar
light at 2.5x the Uttar Pradesh median costs Rs 52,360, which is ordinary for a
solar light in West Bengal, so the model predicts about that and the residual is
zero. Measured on the demo work: predicted Rs 53,451, actual Rs 52,360.

This second channel asks the narrower question directly: how far is the log
amount from the median for the same work type in the same state, in robust
(median/MAD) units. When a state has too few works of that type to estimate a
median, it falls back to the same work type across states of similar cost level,
and then to the work type nationally.

The final cost signal is the stronger of this channel and the expected-cost
residual, and the reason text names which one fired.

Everything here is fitted on the training corpus and saved; scoring an upload
looks the statistics up and never recomputes them from the uploaded batch.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config

_NATIONAL = "nationally"


def soft_signal(z: pd.Series, z_start: float, z_full: float) -> pd.Series:
    """Map a robust z-score to a 0-1 cost signal that never saturates.

    Zero up to ``z_start``, then rising smoothly: 0.9 at ``z_full``, and on
    towards 1 without ever reaching it. The earlier linear mapping clipped at
    1.0 from ``z_full`` upward, which left 3,325 works tied at exactly 1.0 in the
    cost queue. A reviewer could not order them, and a planted overcharge lost
    every one of those ties. With this mapping a z of 6 still outranks a z of 5.
    """
    tau = max(1e-9, z_full - z_start) / np.log(10.0)
    excess = (z.astype("float64") - z_start).clip(lower=0.0).fillna(0.0)
    return 1.0 - np.exp(-excess / tau)


def _group_stats(log_amount: pd.Series, amount: pd.Series, key: pd.Series) -> dict[str, Any]:
    """Median, MAD and count of log amount, plus the median rupee amount, per group."""
    frame = pd.DataFrame({"key": key, "log": log_amount, "amount": amount})
    grouped = frame.groupby("key", observed=True)
    median_log = grouped["log"].median()
    mad_log = grouped["log"].agg(lambda s: float((s - s.median()).abs().median()))
    median_amount = grouped["amount"].median()
    sizes = grouped.size()
    return {
        str(k): {
            "median_log": float(median_log[k]),
            "mad_log": float(mad_log[k]),
            "median_amount": float(median_amount[k]),
            "n": int(sizes[k]),
        }
        for k in median_log.index
    }


def _cost_index_bands(
    df: pd.DataFrame, log_amount: pd.Series, n_bands: int, min_works: int
) -> dict[str, str]:
    """Assign each state to a cost band from how far its prices sit from national.

    A state's cost index is the median, over its works, of the work's log amount
    minus the national median for that work type. States are then split into
    ``n_bands`` equal-count bands. A state with too few works to judge goes in
    the middle band.
    """
    work_type = df["work_type"].astype(str)
    national_median = log_amount.groupby(work_type).transform("median")
    deviation = (log_amount - national_median).rename("deviation")
    per_state = pd.DataFrame({"state": df["state"].astype(str), "deviation": deviation})
    summary = per_state.groupby("state")["deviation"].agg(["median", "size"])

    labels = _band_labels(n_bands)
    middle = labels[len(labels) // 2]
    judged = summary.loc[summary["size"] >= min_works, "median"]

    bands: dict[str, str] = {state: middle for state in summary.index}
    if len(judged) >= n_bands:
        codes = pd.qcut(judged.rank(method="first"), n_bands, labels=False)
        for state, code in codes.items():
            bands[str(state)] = labels[int(code)]
    return bands


def _band_labels(n_bands: int) -> list[str]:
    if n_bands == 3:
        return ["lower-cost states", "mid-cost states", "higher-cost states"]
    return [f"cost band {i + 1} of {n_bands}" for i in range(n_bands)]


def fit(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fit the peer statistics on the training corpus and return them as an artifact."""
    cfg = cfg or load_config("ml")
    ccfg = cfg["cost_state"]
    min_peers = int(ccfg["min_peers"])

    amount = pd.to_numeric(df["sanction_amount"], errors="coerce").astype("float64").clip(lower=0)
    log_amount = np.log1p(amount)
    work_type = df["work_type"].astype(str)
    state = df["state"].astype(str)

    state_band = _cost_index_bands(df, log_amount, int(ccfg["index_bands"]), min_peers)
    band = state.map(state_band).fillna(_band_labels(int(ccfg["index_bands"]))[1])

    return {
        "fine": _group_stats(log_amount, amount, work_type + " | " + state),
        "band": _group_stats(log_amount, amount, work_type + " | " + band),
        "national": _group_stats(log_amount, amount, work_type),
        "state_band": state_band,
        "min_peers": min_peers,
        "fitted_on_rows": int(len(df)),
    }


def apply(
    df: pd.DataFrame, artifact: dict[str, Any], cfg: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Score each work against its saved state peer group.

    Returns ``state_peer_scope`` (which level was used), ``state_peer_label``,
    ``state_peer_median``, ``state_cost_ratio``, ``state_cost_z`` and
    ``state_cost_signal``.
    """
    cfg = cfg or load_config("ml")
    ccfg = cfg["cost_state"]
    scale = float(cfg["features"]["mad_scale"])
    min_mad = float(ccfg["min_mad_log"])
    z_start = float(ccfg["signal_z_start"])
    z_full = float(ccfg["signal_z_full"])
    min_peers = int(artifact.get("min_peers", ccfg["min_peers"]))

    fine: dict[str, dict[str, float]] = artifact["fine"]
    band_stats: dict[str, dict[str, float]] = artifact["band"]
    national: dict[str, dict[str, float]] = artifact["national"]
    state_band: dict[str, str] = artifact["state_band"]
    middle = _band_labels(int(ccfg["index_bands"]))[1]

    amount = pd.to_numeric(df["sanction_amount"], errors="coerce").astype("float64").clip(lower=0)
    log_amount = np.log1p(amount)

    scopes: list[str] = []
    labels: list[str] = []
    medians_log: list[float] = []
    mads_log: list[float] = []
    median_amounts: list[float] = []

    for work_type, state in zip(df["work_type"].astype(str), df["state"].astype(str), strict=True):
        band = state_band.get(state, middle)
        chosen: tuple[str, str, dict[str, float]] | None = None
        for scope, key, label, table in (
            ("state", f"{work_type} | {state}", f"{work_type} in {state}", fine),
            ("cost_band", f"{work_type} | {band}", f"{work_type} in {band}", band_stats),
            ("national", work_type, f"{work_type} {_NATIONAL}", national),
        ):
            stats = table.get(key)
            if stats is not None and int(stats["n"]) >= min_peers:
                chosen = (scope, label, stats)
                break

        if chosen is None:
            scopes.append("none")
            labels.append("")
            medians_log.append(np.nan)
            mads_log.append(np.nan)
            median_amounts.append(np.nan)
            continue
        scope, label, stats = chosen
        scopes.append(scope)
        labels.append(label)
        medians_log.append(float(stats["median_log"]))
        mads_log.append(float(stats["mad_log"]))
        median_amounts.append(float(stats["median_amount"]))

    median_log = pd.Series(medians_log, index=df.index, dtype="float64")
    spread = scale * pd.Series(mads_log, index=df.index, dtype="float64").clip(lower=min_mad)
    z = ((log_amount - median_log) / spread).clip(
        -float(cfg["features"]["z_clip"]), float(cfg["features"]["z_clip"])
    )
    median_amount = pd.Series(median_amounts, index=df.index, dtype="float64")

    # Only overcharging is scored. Costing less than peers is a different
    # question and is not, on its own, a reason for review.
    signal = soft_signal(z, z_start, z_full)

    return pd.DataFrame(
        {
            "state_peer_scope": scopes,
            "state_peer_label": labels,
            "state_peer_median": median_amount,
            "state_cost_ratio": (amount / median_amount.replace(0, np.nan)).round(3),
            "state_cost_z": z.fillna(0.0).round(3),
            # Not rounded: rounding would reintroduce the ties soft_signal removes.
            "state_cost_signal": signal,
        },
        index=df.index,
    )


def combine(
    expected_signal: pd.Series,
    state: pd.DataFrame,
    expected_ratio: pd.Series,
) -> pd.DataFrame:
    """Take the stronger of the two cost channels and record which one it was."""
    state_signal = state["state_cost_signal"].astype("float64")
    expected = expected_signal.astype("float64").fillna(0.0)

    use_state = state_signal > expected
    signal = np.where(use_state, state_signal, expected)
    channel = np.where(signal <= 0, "", np.where(use_state, "state_peer", "expected"))
    ratio = np.where(use_state, state["state_cost_ratio"], expected_ratio)

    return pd.DataFrame(
        {
            "cost_signal": signal,
            "cost_channel": channel,
            "cost_ratio": np.round(ratio.astype("float64"), 3),
        },
        index=state.index,
    )
