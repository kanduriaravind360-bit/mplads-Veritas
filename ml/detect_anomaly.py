"""Unsupervised anomaly detection.

Isolation Forest and ECOD are run on the scaled leak-safe feature matrix and
rank-averaged into a single 0-1 score. Neither model ever sees the proxy label,
so this is the one detector in the pipeline that owes nothing to the dataset's
hand-written rules.

Each work also gets the features that deviate furthest from its peer-group
median. Those become the plain-language reasons a reviewer sees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config

#: Features whose deviation is meaningless or misleading as a stated reason.
#: Flags and calendar values are either already binary or have no natural
#: "distance from normal" a reviewer would act on.
_REASON_BLOCKLIST: frozenset[str] = frozenset(
    {
        "is_open",
        "is_round_lakh",
        "is_march_sanction",
        "sanction_month",
        "fiscal_year",
        "has_vendor",
        "payment_in_progress",
        "disbursed_but_not_complete",
        "stage_ordinal",
    }
)


#: Features that say the same thing. Only the strongest member of each family
#: is offered as a reason, so a reviewer sees distinct findings.
FEATURE_FAMILY: dict[str, str] = {
    "log_amount": "cost",
    "cost_robust_z": "cost",
    "cost_pct_in_type": "cost",
    "amount_vs_peer_median": "cost",
    "days_to_sanction": "sanction_speed",
    "days_to_sanction_z": "sanction_speed",
    "duration_days": "execution_time",
    "duration_pct_in_type": "execution_time",
    "days_since_sanction_open": "stalled",
    "disbursed_ratio": "money_flow",
    "num_payments": "money_flow",
    "vendor_total_works": "vendor_scale",
    "vendor_works_in_ida": "vendor_scale",
    "vendor_share_of_ida": "vendor_concentration",
    "ida_vendor_hhi": "vendor_concentration",
    "vendor_n_mps": "vendor_reach",
    "vendor_n_states": "vendor_reach",
    "vendor_median_cost_z": "vendor_pricing",
    "ida_works": "ida_context",
    "ida_median_days_to_sanction": "ida_context",
    "ida_completion_rate": "ida_performance",
    "mp_works": "mp_context",
    "mp_median_days_to_sanction": "mp_context",
    "mp_completion_rate": "mp_performance",
}


@dataclass
class AnomalyResult:
    """Output of the unsupervised layer."""

    scores: pd.Series  # anomaly_unsup, 0-1, higher = more unusual
    iforest_rank: pd.Series
    ecod_rank: pd.Series
    reasons: pd.Series  # list[tuple[feature, z]] per row
    device: str


def _scale(matrix: pd.DataFrame) -> np.ndarray:
    """Robust-scale the feature matrix so no single wide column dominates."""
    from sklearn.preprocessing import RobustScaler

    scaler = RobustScaler(quantile_range=(5.0, 95.0))
    scaled = scaler.fit_transform(matrix.to_numpy(dtype="float64"))
    return np.nan_to_num(scaled, nan=0.0, posinf=0.0, neginf=0.0)


def _peer_deviation(feats: pd.DataFrame, names: list[str], cfg: dict[str, Any]) -> pd.DataFrame:
    """Robust deviation of every feature from its peer-group median."""
    scale = float(cfg["features"]["mad_scale"])
    clip = float(cfg["features"]["z_clip"])
    groups = feats["peer_group"]

    out = {}
    for name in names:
        if name in _REASON_BLOCKLIST:
            continue
        values = feats[name].astype("float64")
        med = values.groupby(groups).transform("median")
        mad = (values - med).abs().groupby(groups).transform("median")
        spread = (scale * mad).replace(0, np.nan)
        # Where the peer group is perfectly uniform, fall back to the national
        # spread so a deviation is still expressed on some real scale.
        national = scale * (values - values.median()).abs().median()
        spread = spread.fillna(national if national > 0 else 1.0)
        out[name] = ((values - med) / spread).clip(-clip, clip)
    return pd.DataFrame(out, index=feats.index)


def _top_reasons(deviation: pd.DataFrame, top_k: int, min_z: float) -> pd.Series:
    """For each row, the ``top_k`` features furthest from the peer median.

    At most one feature per family is returned. Without this, an expensive work
    reports "cost is high", "cost z-score is high" and "amount is high" as three
    separate findings, which reads as three problems when it is one.
    """
    values = deviation.to_numpy(dtype="float64")
    names = np.array(deviation.columns)
    families = np.array([FEATURE_FAMILY.get(str(n), str(n)) for n in names])
    magnitude = np.abs(values)

    # Consider more candidates than needed, since family de-duplication drops some.
    k = min(max(top_k * 3, top_k), values.shape[1])
    idx = np.argpartition(-magnitude, kth=k - 1, axis=1)[:, :k]
    rows = np.arange(values.shape[0])[:, None]
    order = np.argsort(-magnitude[rows, idx], axis=1)
    idx = idx[rows, order]

    picked = []
    for r in range(values.shape[0]):
        seen: set[str] = set()
        chosen: list[tuple[str, float]] = []
        for c in idx[r]:
            if magnitude[r, c] < min_z:
                break
            family = families[c]
            if family in seen:
                continue
            seen.add(family)
            chosen.append((str(names[c]), float(values[r, c])))
            if len(chosen) == top_k:
                break
        picked.append(chosen)
    return pd.Series(picked, index=deviation.index, dtype="object")


def detect(
    feats: pd.DataFrame, names: list[str], cfg: dict[str, Any] | None = None
) -> AnomalyResult:
    """Run Isolation Forest + ECOD and rank-average them into ``anomaly_unsup``.

    Rank-averaging rather than score-averaging is deliberate: the two models
    produce scores on incomparable scales, and only their ordering is
    meaningful.
    """
    cfg = cfg or load_config("ml")
    acfg = cfg["anomaly"]
    seed = int(cfg["seed"])

    matrix = feats[names]
    scaled = _scale(matrix)

    from pyod.models.ecod import ECOD
    from sklearn.ensemble import IsolationForest

    ifcfg = acfg["isolation_forest"]
    iforest = IsolationForest(
        n_estimators=int(ifcfg["n_estimators"]),
        max_samples=ifcfg["max_samples"],
        contamination=float(ifcfg["contamination"]),
        random_state=seed,
        n_jobs=-1,
    ).fit(scaled)
    # Negate: sklearn returns higher = more normal.
    iforest_raw = -iforest.score_samples(scaled)

    ecod = ECOD(contamination=float(acfg["ecod"]["contamination"]), n_jobs=-1)
    ecod.fit(scaled)
    ecod_raw = ecod.decision_scores_

    n = len(matrix)
    if_rank = pd.Series(iforest_raw, index=matrix.index).rank(pct=True)
    ec_rank = pd.Series(ecod_raw, index=matrix.index).rank(pct=True)
    combined = ((if_rank + ec_rank) / 2.0).rank(pct=True) if n > 1 else if_rank

    # Keep only the outlier tail. A raw percentile rank gives every average work
    # 0.5, which adds a constant to every risk score and hides real outliers.
    tail_start = float(acfg["tail_start_percentile"])
    combined = ((combined - tail_start) / max(1e-9, 1.0 - tail_start)).clip(0.0, 1.0)

    deviation = _peer_deviation(feats, names, cfg)
    reasons = _top_reasons(deviation, int(acfg["top_reasons"]), float(acfg["min_reason_z"]))

    return AnomalyResult(
        scores=combined.rename("anomaly_unsup"),
        iforest_rank=if_rank.rename("iforest_rank"),
        ecod_rank=ec_rank.rename("ecod_rank"),
        reasons=reasons.rename("unsup_reasons"),
        device="cpu",
    )
