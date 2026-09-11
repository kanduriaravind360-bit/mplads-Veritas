"""Recompute the seven transparent rules from observable data.

The dataset ships ``flag_*``, ``anomaly_score`` and ``flag_reasons`` already
computed. Reading them is tempting, but it breaks in two ways that matter:

1. **Uploaded data does not have them.** ``score_new_works`` receives a CSV of
   works, not a pre-flagged extract. A rule layer that can only read precomputed
   columns contributes nothing there.
2. **They do not respond to the data.** If a work's cost is changed, an
   inherited flag column still describes the old cost. That silently breaks both
   the injection test and any re-scoring after a correction.

So the rules are recomputed here from the same observable columns the original
flags were derived from. Thresholds live in ``configs/ml.yaml`` and were
reverse-engineered from the shipped flags, which separate cleanly:

========================== ================================ ==========
rule                        observable                       threshold
========================== ================================ ==========
flag_sanction_delay        days_to_sanction                 >= 334
flag_cost_outlier          cost_zscore                      >  2.50
flag_fast_completion       duration_days                    <= 6
flag_stuck_work            days_since_sanction + status     >= 612, early stage
flag_round_amount          sanction_amount % 100000         == 0
flag_vendor_concentration  vendor_work_count                >= 191
flag_payment_stuck         latest_payment_status            in progress
========================== ================================ ==========

:func:`agreement_with_shipped` measures how well the recomputation reproduces
the shipped flags, and that agreement is reported in ``models/metrics.json``.

This is **not** a leakage violation. The rule score is never a model input; it
is one transparent signal blended at the very end, exactly as the shipped flags
would have been (CLAUDE.md rule 3 and spec item 3e).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config

RULE_COLUMNS: tuple[str, ...] = (
    "rule_sanction_delay",
    "rule_stuck_work",
    "rule_cost_outlier",
    "rule_fast_completion",
    "rule_round_amount",
    "rule_vendor_concentration",
    "rule_payment_stuck",
)

#: Maps each recomputed rule to the shipped flag it reproduces.
SHIPPED_EQUIVALENT: dict[str, str] = {
    "rule_sanction_delay": "flag_sanction_delay",
    "rule_stuck_work": "flag_stuck_work",
    "rule_cost_outlier": "flag_cost_outlier",
    "rule_fast_completion": "flag_fast_completion",
    "rule_round_amount": "flag_round_amount",
    "rule_vendor_concentration": "flag_vendor_concentration",
    "rule_payment_stuck": "flag_payment_stuck",
}

#: Human-readable text per rule, matching the dataset's own wording so that
#: reviewers see one consistent vocabulary.
RULE_TEXT: dict[str, str] = {
    "rule_sanction_delay": "Sanctioning delay is a statistical outlier for this work category",
    "rule_stuck_work": "Still in an early stage (not yet started) far longer than typical",
    "rule_cost_outlier": "Sanctioned cost is a statistical outlier for this work category",
    "rule_fast_completion": "Completed unusually fast for this work category",
    "rule_round_amount": "Suspiciously round sanctioned amount",
    "rule_vendor_concentration": (
        "Vendor handles unusually high number of works in this constituency"
    ),
    "rule_payment_stuck": "Payment in-progress for over 60 days",
}


def _cutoff(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.Timestamp:
    """Reference "today" for staleness, shared with the feature layer."""
    from ml.features import cutoff_date

    return cutoff_date(df, cfg)


def _robust_cost_z(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.Series:
    """Cost outlier measure, preferring our robust peer z-score.

    Falls back to the dataset's own ``cost_zscore`` when the robust version is
    unavailable, so the rule still works on a bare uploaded extract.
    """
    from ml.features import build_peer_groups, robust_z

    if "work_type" not in df.columns:
        return pd.to_numeric(df.get("cost_zscore"), errors="coerce").fillna(0.0)

    base = build_peer_groups(df, cfg)
    log_amount = np.log1p(
        pd.to_numeric(base["sanction_amount"], errors="coerce").fillna(0.0).clip(lower=0)
    )
    return robust_z(log_amount, base["peer_group"], cfg)


def compute_rules(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Recompute the seven rules and their weighted score from observable data."""
    cfg = cfg or load_config("ml")
    rcfg = cfg["rules"]
    weights: dict[str, int] = cfg["rules"]["weights"]

    out = pd.DataFrame(index=df.index)

    days_to_sanction = pd.to_numeric(df.get("days_to_sanction"), errors="coerce")
    out["rule_sanction_delay"] = (days_to_sanction >= float(rcfg["sanction_delay_days"])).fillna(
        False
    )

    early_stages = set(rcfg["stuck_work_stages"])
    days_since = pd.to_numeric(df.get("days_since_sanction"), errors="coerce")
    is_early = df["work_status"].astype(str).isin(early_stages)
    out["rule_stuck_work"] = (is_early & (days_since >= float(rcfg["stuck_work_days"]))).fillna(
        False
    )

    cost_z = _robust_cost_z(df, cfg)
    shipped_z = pd.to_numeric(df.get("cost_zscore"), errors="coerce").fillna(0.0)
    # Either measure crossing its threshold is enough: the robust score catches
    # peer-relative overpricing, the shipped one keeps parity with the original.
    out["rule_cost_outlier"] = (
        (cost_z > float(rcfg["cost_outlier_robust_z"]))
        | (shipped_z > float(rcfg["cost_outlier_zscore"]))
    ).fillna(False)

    duration = pd.to_numeric(df.get("duration_days"), errors="coerce")
    out["rule_fast_completion"] = (duration <= float(rcfg["fast_completion_days"])).fillna(False)

    unit = float(rcfg["round_amount_unit"])
    amount = pd.to_numeric(df["sanction_amount"], errors="coerce")
    out["rule_round_amount"] = ((amount > 0) & (amount % unit == 0)).fillna(False)

    vendor_count = pd.to_numeric(df.get("vendor_work_count"), errors="coerce")
    if vendor_count.isna().all() and "vendor_name" in df.columns:
        vendor_count = df["vendor_name"].map(df["vendor_name"].value_counts())
    out["rule_vendor_concentration"] = (
        vendor_count >= float(rcfg["vendor_concentration_works"])
    ).fillna(False)

    in_progress = (
        df.get("latest_payment_status", pd.Series(index=df.index, dtype="object"))
        .astype(str)
        .eq(str(rcfg["payment_stuck_status"]))
    )
    # "In progress" alone is not stuck; it has to have been sitting there.
    last_activity = pd.to_datetime(df.get("latest_expenditure_date"), errors="coerce")
    stale_days = (_cutoff(df, cfg) - last_activity).dt.days
    out["rule_payment_stuck"] = (
        in_progress & (stale_days >= float(rcfg["payment_stuck_days"]))
    ).fillna(False)

    for col in RULE_COLUMNS:
        out[col] = out[col].astype(bool)

    score = pd.Series(0.0, index=df.index, dtype="float64")
    for col in RULE_COLUMNS:
        score += out[col].astype("float64") * float(weights[col])
    out["rule_score"] = score
    out["rule_label"] = (score >= float(rcfg["label_threshold"])).astype("int8")

    # A single serious rule should carry a work into the review queue on its
    # own. Injected fast completions tripped their rule 100% of the time yet
    # ranked low, because one 2-point rule against a threshold of 4 reads as
    # half-confidence and nothing else fired.
    critical = [c for c in rcfg.get("critical_rules", []) if c in out.columns]
    if critical:
        any_critical = out[critical].any(axis=1)
        floor = float(rcfg["critical_rule_signal"]) * float(rcfg["label_threshold"])
        out["rule_score"] = np.where(any_critical, np.maximum(score, floor), score)
    out["rule_any_critical"] = out[critical].any(axis=1) if critical else False
    out["rule_reasons"] = _reason_text(out)
    return out


def _reason_text(rules: pd.DataFrame) -> pd.Series:
    """Semicolon-joined rule text, matching the dataset's own phrasing."""
    parts: list[str] = []
    for _, row in rules[list(RULE_COLUMNS)].iterrows():
        hits = [RULE_TEXT[c] for c in RULE_COLUMNS if row[c]]
        parts.append("; ".join(hits) if hits else "No rule-based flags")
    return pd.Series(parts, index=rules.index, dtype="object")


def max_score(cfg: dict[str, Any] | None = None) -> int:
    """Highest achievable rule score, used to normalise the fusion signal."""
    cfg = cfg or load_config("ml")
    return int(sum(cfg["rules"]["weights"].values()))


def agreement_with_shipped(
    df: pd.DataFrame, rules: pd.DataFrame, cfg: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compare the recomputed rules against the dataset's shipped flags.

    Reported in metrics so any drift between the two is visible rather than
    assumed away.
    """
    cfg = cfg or load_config("ml")
    out: dict[str, Any] = {}
    for rule_col, flag_col in SHIPPED_EQUIVALENT.items():
        if flag_col not in df.columns:
            continue
        shipped = df[flag_col].astype(bool)
        ours = rules[rule_col].astype(bool)
        out[rule_col] = {
            "agreement": round(float((shipped == ours).mean()), 4),
            "shipped_true": int(shipped.sum()),
            "recomputed_true": int(ours.sum()),
            "both_true": int((shipped & ours).sum()),
        }
    if "anomaly_label" in df.columns:
        shipped_label = df["anomaly_label"].astype(int)
        out["label"] = {
            "agreement": round(float((shipped_label == rules["rule_label"]).mean()), 4),
            "shipped_positive": int(shipped_label.sum()),
            "recomputed_positive": int(rules["rule_label"].sum()),
        }
    return out
