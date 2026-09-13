"""Model performance: the full metrics document and a presentation-ready summary."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.app.deps import Context, context
from backend.app.metrics_doc import metrics
from backend.app.settings import get_settings

router = APIRouter(prefix="/models", tags=["models"])

_EXPLAIN = {
    "detector_fired": "Of the planted cases of this kind, the share the detector flagged at all.",
    "recall_at_top_5pct": "Of the planted cases, the share found in the top 5% of that detector's own queue.",
    "recall_at_top_10pct": "The same, in the top 10% of the queue.",
    "precision_at_top_5pct": "Of the top 5% of the queue, the share that were planted cases; a floor, because genuine anomalies count as misses.",
    "delay_roc_auc": "How well the delay model ranks a late work above an on-time one: 0.5 is chance, 1.0 is perfect.",
    "delay_pr_auc": "Precision averaged across recall levels for late works; judged against the share of works that run late.",
    "proxy_pr_auc": "How well the proxy model reproduces the dataset's hand-written rule label. It measures learnability of the rules, not fraud detection.",
    "holdout": "Scores on whole constituencies removed before anything was fitted; the honest generalisation check.",
}


@router.get("/metrics")
def full_metrics(ctx: Context = Depends(context)) -> dict[str, Any]:
    return metrics(ctx.db)


@router.get("/summary")
def summary(ctx: Context = Depends(context)) -> dict[str, Any]:
    m = metrics(ctx.db)
    injection = m.get("injection_test", {})
    holdout = m.get("holdout_evaluation", {})
    delay = m.get("delay_model", {})
    supervised = m.get("supervised_model", {})
    per_stream = injection.get("per_stream_recall", {})
    return {
        "per_detector": [
            {
                "detector": name,
                "fired": v.get("detector_fired"),
                "queue_size": v.get("queue_size"),
                "recall_at_top_1pct": v.get("recall_at_top_1pct"),
                "recall_at_top_5pct": v.get("recall_at_top_5pct"),
                "recall_at_top_10pct": v.get("recall_at_top_10pct"),
                "precision_at_top_5pct": v.get("precision_at_top_5pct"),
            }
            for name, v in sorted(per_stream.items())
        ],
        "global_rank_recall": injection.get("per_type", {}),
        "before_after": injection.get("recall_at_top_5pct_before_after", {}),
        "delay_model": {
            "train": {"roc_auc": delay.get("roc_auc"), "pr_auc": delay.get("pr_auc")},
            "holdout": holdout.get("delay_model", {}).get("holdout", {}),
        },
        "proxy_model": {
            "pr_auc_oof": supervised.get("pr_auc_oof"),
            "roc_auc_oof": supervised.get("roc_auc_oof"),
            "caveat": supervised.get("CAVEAT") or supervised.get("caveat"),
        },
        "holdout_bands": holdout.get("risk_bands", {}),
        "holdout_size": {
            "works": holdout.get("n_holdout_works"),
            "constituencies": holdout.get("n_holdout_constituencies"),
        },
        "severe_floor": m.get("severe_floor", {}),
        "cost_state_channel": m.get("cost_state_channel", {}),
        "band_cutoffs": m.get("band_cutoffs", {}),
        "weights": m.get("weights", {}),
        "weak_spot": injection.get("weakest_detector_plain_language"),
        "caveats": [
            supervised.get("CAVEAT")
            or supervised.get("caveat")
            or "The proxy label is a hand-written rule set, not verified fraud.",
            injection.get("weakest_detector_plain_language"),
            *([injection["CAVEAT"]] if injection.get("CAVEAT") else []),
            *(holdout.get("caveats") or []),
        ],
        "explanations": _EXPLAIN,
        "thresholds": {
            "high_delay_risk": float(get_settings().api["predictions"]["high_delay_risk"]),
        },
    }
