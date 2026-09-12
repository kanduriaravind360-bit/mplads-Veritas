"""Score the held-out constituencies and compare them against training.

This is the honest generalisation check. Every work here belongs to a
constituency that was removed before anything was fitted, so no model and no
peer statistic has seen it, nor any of its neighbours.

Two caveats stated up front, because they change how the numbers should be read:

* Held-out works are scored the way an uploaded CSV is scored, so their peer
  comparisons are computed within the holdout batch. A batch of 3,890 works from
  27 constituencies gives thinner peer groups than the national run, which makes
  the cost signal a little noisier here than in production.
* The delay model is the only one measured against a real outcome. The band
  counts are a distribution comparison, not an accuracy measure, because no
  held-out work carries a verified fraud label. Nothing does.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config

_BANDS = ("Low", "Medium", "High", "Critical")


def _band_shares(scored: pd.DataFrame) -> dict[str, Any]:
    counts = scored["band"].value_counts()
    total = max(1, len(scored))
    return {
        "counts": {band: int(counts.get(band, 0)) for band in _BANDS},
        "shares": {band: round(float(counts.get(band, 0)) / total, 4) for band in _BANDS},
        "n": int(len(scored)),
    }


def _delay_metrics(
    works: pd.DataFrame, predictions: pd.Series, cfg: dict[str, Any]
) -> dict[str, Any]:
    """ROC-AUC and PR-AUC of the delay model on works with a known outcome."""
    from sklearn.metrics import average_precision_score, roc_auc_score

    from ml.train_delay import build_labels

    labels = build_labels(works, cfg)
    mask = labels.notna()
    if int(mask.sum()) == 0:
        return {"note": "no held-out work is old enough to have a delay outcome yet"}

    y = labels[mask].astype("int64").to_numpy()
    p = predictions[mask].astype("float64").to_numpy()
    out: dict[str, Any] = {
        "n_labelled": int(mask.sum()),
        "delay_rate": round(float(y.mean()), 4),
    }
    if len(np.unique(y)) > 1:
        out["roc_auc"] = round(float(roc_auc_score(y, p)), 4)
        out["pr_auc"] = round(float(average_precision_score(y, p)), 4)
    else:
        out["roc_auc"] = None
        out["pr_auc"] = None
        out["note"] = "only one outcome class present in the holdout"
    return out


def evaluate(
    train_scored: pd.DataFrame,
    train_metrics: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score the holdout with the train-fitted models and compare."""
    cfg = cfg or load_config("ml")
    from ml import holdout as holdout_module
    from ml.pipeline import score_new_works

    works = holdout_module.load(cfg)
    scored = score_new_works(works, cfg)
    if "holdout_scored" in cfg["paths"]:
        # Kept so the application can show every real work, holdout included,
        # without re-scoring the holdout on every load.
        from ml.config import resolve
        from ml.pipeline import _as_json

        out = scored.copy()
        for column in ("unsup_reasons", "supervised_reasons", "delay_reasons"):
            if column in out and not out[column].map(lambda v: isinstance(v, str)).all():
                out[column] = _as_json(out[column])
        out.to_parquet(resolve(cfg["paths"]["holdout_scored"]), index=False)

    train_delay = train_metrics.get("delay_model", {})
    holdout_delay = _delay_metrics(scored, scored.get("delay_risk", pd.Series(dtype=float)), cfg)

    return {
        "n_holdout_works": int(len(works)),
        "n_holdout_constituencies": int(works["constituency"].nunique()),
        "risk_bands": {
            "train": _band_shares(train_scored),
            "holdout": _band_shares(scored),
        },
        "delay_model": {
            "train_test_split": {
                "roc_auc": train_delay.get("roc_auc"),
                "pr_auc": train_delay.get("pr_auc"),
                "note": "time-based split inside the training constituencies",
            },
            "holdout": holdout_delay,
        },
        "how_exclusion_was_verified": [
            "The split happens in ml.pipeline.run before any stage that fits or "
            "aggregates, so no later stage can see a held-out row.",
            "Whole constituencies are held out, not rows, so a held-out work's "
            "neighbours are absent too and cannot carry it into vendor or "
            "district history.",
            "ml.holdout.verify asserts no shared work_id and no shared "
            "constituency between the two sets; both checks are recorded in "
            "metrics.json under 'holdout'.",
            "Selection is a deterministic hash of constituency name and seed, so "
            "it cannot drift between runs or machines.",
            "tests/test_holdout.py re-derives the split and fails if any held-out "
            "constituency appears in the scored training output.",
        ],
        "caveats": [
            "Held-out works are scored like an uploaded CSV, so their peer "
            "comparisons come from within the 3,890-work batch rather than the "
            "national population. That makes the cost signal noisier here than "
            "in production, not cleaner.",
            "Band counts compare distributions. They are not an accuracy "
            "measure, because no work in this data carries a verified fraud "
            "label.",
        ],
    }
