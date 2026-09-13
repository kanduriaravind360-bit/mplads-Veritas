"""Learning from reviewer verdicts: Bayesian channel re-weighting and a re-ranker.

Two ways the system can use verdicts, both measured on verdicts they did not
learn from (the ``evaluate`` partition):

1. Bayesian re-weight. For each detector channel, the share of verdicts where the
   channel was active that were confirmed, with a Beta prior centred on the
   overall confirmed rate. A channel that reviewers keep confirming gains weight;
   one they keep dismissing loses it, within configured bounds. With few
   verdicts the prior dominates and nothing moves.
2. Re-ranker. A logistic regression on the six channels, trained once the learn
   partition holds enough verdicts.

Precision at k compares the ranking by configured fusion, by re-weighted fusion
and by the re-ranker. Nothing is applied automatically: learned weights can be
tried in the threshold simulator.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import beta
from sklearn.linear_model import LogisticRegression
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.settings import get_settings
from ml.config import SEED, load_config
from ml.risk import _SIGNALS, fuse

POSITIVE = {"confirmed"}
NEGATIVE = {"false_positive", "not_duplicate"}


def examples(db: Session) -> pd.DataFrame:
    """Labelled rows: planted positives plus reviewer and seeded verdicts."""
    cfg = get_settings().api["learning"]
    rows: list[dict[str, Any]] = []

    planted_bands = cfg["seed"].get("planted_bands") or ["High", "Critical"]
    for case in db.execute(
        select(models.PlantedCase).where(models.PlantedCase.band.in_(planted_bands))
    ).scalars():
        rows.append(
            {
                "origin": "planted",
                "kind": case.injection,
                "label": 1,
                "partition": case.partition,
                "is_open": case.is_open,
                **{name: float(case.signals.get(name, 0.0)) for name in _SIGNALS},
            }
        )

    verdicts = db.execute(
        select(models.Feedback, models.Work.is_open)
        .join(models.Work, models.Work.work_id == models.Feedback.work_id)
        .order_by(models.Feedback.created_at)
    ).all()
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for fb, is_open in verdicts:
        if fb.verdict not in POSITIVE | NEGATIVE or not fb.signals:
            continue
        # A later verdict on the same alert and work replaces an earlier one.
        latest[(fb.alert_id, fb.work_id or "")] = {
            "origin": "seed_rule" if fb.is_seed else "reviewer",
            "kind": fb.verdict,
            "label": 1 if fb.verdict in POSITIVE else 0,
            "partition": fb.partition,
            "is_open": bool(is_open),
            **{name: float(fb.signals.get(name, 0.0) or 0.0) for name in _SIGNALS},
        }
    rows.extend(latest.values())
    columns = ["origin", "kind", "label", "partition", "is_open", *_SIGNALS]
    return pd.DataFrame(rows, columns=columns)


def _precision_at(scores: np.ndarray, labels: np.ndarray, k: int) -> float | None:
    if len(scores) == 0:
        return None
    k = min(k, len(scores))
    order = np.argsort(-scores, kind="stable")[:k]
    return round(float(labels[order].mean()), 4)


def learn(db: Session) -> dict[str, Any]:
    lcfg = get_settings().api["learning"]
    ml_cfg = load_config("ml")
    weights = {k: float(v) for k, v in ml_cfg["risk"]["weights"].items()}
    data = examples(db)

    counts = {
        "total": int(len(data)),
        "by_origin": {
            origin: {
                "positive": int(((data["origin"] == origin) & (data["label"] == 1)).sum()),
                "negative": int(((data["origin"] == origin) & (data["label"] == 0)).sum()),
            }
            for origin in ("planted", "seed_rule", "reviewer")
        },
        "learn": int((data["partition"] == "learn").sum()),
        "evaluate": int((data["partition"] == "evaluate").sum()),
    }
    learn_set = data[data["partition"] == "learn"]
    eval_set = data[data["partition"] == "evaluate"]
    both_classes = learn_set["label"].nunique() == 2
    out: dict[str, Any] = {"counts": counts, "configured_weights": weights}
    if learn_set.empty or not both_classes:
        out["status"] = "insufficient"
        out["message"] = (
            "Needs verdicts of both kinds in the learn partition before anything is learned."
        )
        return out

    # 1. Bayesian re-weight.
    prior = float(learn_set["label"].mean())
    strength = float(lcfg["prior_strength"])
    a0, b0 = strength * prior, strength * (1.0 - prior)
    lo, hi = (float(x) for x in lcfg["weight_multiplier"])
    threshold = float(lcfg["active_signal"])
    channels = []
    raw: dict[str, float] = {}
    for name in _SIGNALS:
        active = learn_set[learn_set[name] >= threshold]
        confirmed = int(active["label"].sum())
        n = int(len(active))
        a, b = a0 + confirmed, b0 + (n - confirmed)
        mean = a / (a + b)
        multiplier = float(np.clip(mean / prior if prior else 1.0, lo, hi))
        raw[name] = weights[name] * multiplier
        channels.append(
            {
                "channel": name,
                "active_verdicts": n,
                "confirmed": confirmed,
                "posterior_precision": round(mean, 4),
                "interval_90": [
                    round(float(beta.ppf(0.05, a, b)), 4),
                    round(float(beta.ppf(0.95, a, b)), 4),
                ],
                "multiplier": round(multiplier, 3),
            }
        )
    # Keep the total weight, so band volumes stay comparable.
    scale = sum(weights.values()) / max(sum(raw.values()), 1e-9)
    learned = {name: round(value * scale, 4) for name, value in raw.items()}
    for item in channels:
        item["configured_weight"] = weights[item["channel"]]
        item["learned_weight"] = learned[item["channel"]]

    # 2. Precision on the evaluate partition.
    k = int(lcfg["precision_at"])
    labels = eval_set["label"].to_numpy()
    signals = eval_set[list(_SIGNALS)].reset_index(drop=True)
    is_open = eval_set["is_open"].reset_index(drop=True).astype(bool)
    before = fuse(signals, is_open, ml_cfg).to_numpy()
    reweighted_cfg = copy.deepcopy(ml_cfg)
    reweighted_cfg["risk"]["weights"] = learned
    after = fuse(signals, is_open, reweighted_cfg).to_numpy()

    reranker: dict[str, Any] = {"trained": False, "min_labels": int(lcfg["min_labels"])}
    reranked = None
    if len(learn_set) >= int(lcfg["min_labels"]):
        model = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=SEED)
        model.fit(learn_set[list(_SIGNALS)].to_numpy(), learn_set["label"].to_numpy())
        if len(eval_set):
            reranked = model.predict_proba(signals.to_numpy())[:, 1]
        reranker = {
            "trained": True,
            "min_labels": int(lcfg["min_labels"]),
            "n_learn": int(len(learn_set)),
            "coefficients": {
                name: round(float(c), 3) for name, c in zip(_SIGNALS, model.coef_[0], strict=True)
            },
        }

    out.update(
        {
            "status": "ok",
            "prior_confirmed_rate": round(prior, 4),
            "channels": channels,
            "learned_weights": learned,
            "reranker": reranker,
            "precision": {
                "k": min(k, len(eval_set)),
                "evaluate_rows": int(len(eval_set)),
                "base_rate": round(float(labels.mean()), 4) if len(labels) else None,
                "configured_fusion": _precision_at(before, labels, k),
                "reweighted_fusion": _precision_at(after, labels, k),
                "reranker": None if reranked is None else _precision_at(reranked, labels, k),
            },
            "caveats": [
                "Positives here are planted synthetic cases and negatives are rule-seeded benign "
                "patterns, so these figures show the learning mechanism working, not precision in "
                "the field. As reviewers record verdicts, theirs join and then outweigh the seeds.",
                "Nothing is applied automatically. Learned weights can be tried in the threshold "
                "simulator; changing production scoring is a separate, audited decision.",
            ],
        }
    )
    return out
