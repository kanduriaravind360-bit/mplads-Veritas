"""Re-fuse the stored channel signals: threshold simulator and counterfactuals.

Both call the pipeline's own ``ml.risk.fuse``, ``band_cutoffs`` and
``apply_severe_floor``, so a simulation with the configured weights reproduces
the stored scores (tests check it) and nothing here can drift from how works
were actually scored. Nothing is written: a simulation is a what-if.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from functools import cache
from typing import Any

import numpy as np
import pandas as pd
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app import metrics_doc, models
from backend.app.scoping import DISTRICT, MP, STATE, Scope
from ml.config import CONFIG_DIR, load_config
from ml.risk import _SIGNALS, apply_severe_floor, band_cutoffs, fuse

BANDS = ("Critical", "High", "Medium", "Low")
QUEUE = ("High", "Critical")


@dataclass
class Population:
    key: tuple[Any, ...]
    frame: pd.DataFrame


_population: Population | None = None


def population(db: Session) -> pd.DataFrame:
    """Every scored work with its channels, cached until the works table changes."""
    global _population
    key = tuple(
        db.execute(select(func.count(models.Work.work_id), func.max(models.Work.scored_at))).one()
    )
    if _population is None or _population.key != key:
        columns = [
            models.Work.work_id,
            models.Work.source,
            models.Work.state,
            models.Work.ida,
            models.Work.mp_code,
            models.Work.sanction_amount,
            models.Work.is_open,
            models.Work.severe_rule_count,
            models.Work.band,
            models.Work.risk_score,
            *(getattr(models.Work, f"sig_{name}") for name in _SIGNALS),
        ]
        rows = db.execute(select(*columns)).all()
        frame = pd.DataFrame(rows, columns=[c.key for c in columns])
        frame = frame.rename(columns={f"sig_{name}": name for name in _SIGNALS})
        frame["is_open"] = frame["is_open"].astype(bool)
        _population = Population(key=key, frame=frame)
    return _population.frame


def scope_mask(frame: pd.DataFrame, scope: Scope) -> np.ndarray:
    if scope.role == STATE:
        return (frame["state"] == scope.state).to_numpy()
    if scope.role == DISTRICT:
        return (frame["ida"] == scope.ida).to_numpy()
    if scope.role == MP:
        return (frame["mp_code"] == scope.mp_code).to_numpy()
    return np.ones(len(frame), dtype=bool)


def defaults() -> dict[str, Any]:
    risk = load_config("ml")["risk"]
    return {
        "weights": {k: float(v) for k, v in risk["weights"].items()},
        "band_percentiles": {k: float(v) for k, v in risk["band_percentiles"].items()},
        "single_signal_target": float(risk["single_signal_target"]),
    }


def _bands(scores: np.ndarray, cuts: dict[str, float]) -> np.ndarray:
    return np.select(
        [scores >= cuts["critical"], scores >= cuts["high"], scores >= cuts["medium"]],
        ["Critical", "High", "Medium"],
        default="Low",
    )


def rescore(
    frame: pd.DataFrame, weights: dict[str, float], percentiles: dict[str, float]
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    """Scores, bands and cut-offs under new weights, exactly as the pipeline computes them.

    Cut-offs are percentiles of the TRAINING works' base scores, as in the
    pipeline; holdout and uploaded works are banded against them.
    """
    cfg = copy.deepcopy(load_config("ml"))
    cfg["risk"]["weights"] = {**cfg["risk"]["weights"], **weights}
    cfg["risk"]["band_percentiles"] = {**cfg["risk"]["band_percentiles"], **percentiles}
    signals = frame[list(_SIGNALS)]
    base = fuse(signals, frame["is_open"], cfg)
    training = (frame["source"] == "training").to_numpy()
    cuts = band_cutoffs(base[training] if training.any() else base, cfg)
    floored, _ = apply_severe_floor(base, frame, cuts, cfg)
    scores = floored.to_numpy(dtype="float64")
    return scores, _bands(scores, cuts), cuts


def simulate(
    db: Session, scope: Scope, weights: dict[str, float], percentiles: dict[str, float]
) -> dict[str, Any]:
    frame = population(db)
    scores, bands, cuts = rescore(frame, weights, percentiles)
    mask = scope_mask(frame, scope)
    amount = frame["sanction_amount"].fillna(0.0).to_numpy()
    current_band = frame["band"].to_numpy()

    in_now = np.isin(current_band, QUEUE) & mask
    in_sim = np.isin(bands, QUEUE) & mask
    entering = in_sim & ~in_now
    leaving = in_now & ~in_sim

    def counts(values: np.ndarray) -> list[dict[str, Any]]:
        return [
            {
                "band": b,
                "works": int(((values == b) & mask).sum()),
                "amount": float(amount[(values == b) & mask].sum()),
            }
            for b in BANDS
        ]

    verdicts = _verdict_overlap(db, frame, mask, in_now, in_sim)
    top_entering = frame.loc[entering, ["work_id"]].assign(score=scores[entering])
    return {
        "scope_works": int(mask.sum()),
        "cutoffs": {k: round(v, 2) for k, v in cuts.items()},
        "current": {
            "bands": counts(current_band),
            "queue": int(in_now.sum()),
            "money_at_risk": float(amount[in_now].sum()),
        },
        "simulated": {
            "bands": counts(bands),
            "queue": int(in_sim.sum()),
            "money_at_risk": float(amount[in_sim].sum()),
        },
        "entering": {"works": int(entering.sum()), "amount": float(amount[entering].sum())},
        "leaving": {"works": int(leaving.sum()), "amount": float(amount[leaving].sum())},
        "entering_examples": top_entering.sort_values("score", ascending=False)
        .head(5)["work_id"]
        .tolist(),
        "verdicts": verdicts,
        "note": (
            "A what-if on the stored detector channels: nothing is re-scored or saved. "
            "Cut-offs are percentiles of the training works, as in the pipeline."
        ),
    }


def _verdict_overlap(
    db: Session, frame: pd.DataFrame, mask: np.ndarray, in_now: np.ndarray, in_sim: np.ndarray
) -> dict[str, Any]:
    """How reviewer verdicts on real works sit in the current and simulated queues."""
    rows = db.execute(select(models.Feedback.work_id, models.Feedback.verdict)).all()
    if not rows:
        return {"labelled": 0}
    index = {w: i for i, w in enumerate(frame["work_id"].to_numpy())}
    out = {"labelled": 0, "confirmed_in_queue": [0, 0], "false_positive_in_queue": [0, 0]}
    for work_id, verdict in rows:
        i = index.get(work_id)
        if i is None or not mask[i]:
            continue
        out["labelled"] += 1
        key = (
            "confirmed_in_queue"
            if verdict == "confirmed"
            else "false_positive_in_queue"
            if verdict in ("false_positive", "not_duplicate")
            else None
        )
        if key:
            out[key][0] += int(in_now[i])
            out[key][1] += int(in_sim[i])
    return out


# ------------------------------------------------------------------ counterfactual


@cache
def _templates() -> dict[str, dict[str, str]]:
    with (CONFIG_DIR / "reasons.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["counterfactual"]


def _say(key: str, **values: Any) -> dict[str, str]:
    template = _templates()[key]
    return {lang: template[lang].format(**values) for lang in ("en", "hi")}


def _inr(amount: float) -> str:
    if amount >= 1e7:
        return f"Rs {amount / 1e7:.2f} crore"
    if amount >= 1e5:
        return f"Rs {amount / 1e5:.2f} lakh"
    return f"Rs {amount:,.0f}"


def counterfactual(db: Session, work: models.Work) -> dict[str, Any]:
    """What would have to change for this work to leave the review queue."""
    cfg = load_config("ml")
    risk_cfg = cfg["risk"]
    weights = {k: float(v) for k, v in risk_cfg["weights"].items()}
    k = -math.log(1.0 - float(risk_cfg["single_signal_target"])) / max(weights.values())
    cuts = metrics_doc.metrics(db).get("band_cutoffs") or {}
    target = float(cuts.get("high", 0.0))

    signals = {name: float(getattr(work, f"sig_{name}") or 0.0) for name in _SIGNALS}
    applies = {name: (name != "delay" or bool(work.is_open)) for name in _SIGNALS}
    contribution = {n: weights[n] * signals[n] if applies[n] else 0.0 for n in _SIGNALS}
    evidence = sum(contribution.values())

    def to_score(e: float) -> float:
        return 100.0 * (1.0 - math.exp(-k * max(e, 0.0)))

    needed = -math.log(1.0 - target / 100.0) / k if 0 < target < 100 else 0.0
    reduction = max(0.0, evidence - needed)
    in_queue = work.band in QUEUE
    top_pair = db.execute(
        select(models.DuplicatePair.work_id_a, models.DuplicatePair.work_id_b)
        .where(
            (models.DuplicatePair.work_id_a == work.work_id)
            | (models.DuplicatePair.work_id_b == work.work_id)
        )
        .order_by(models.DuplicatePair.pair_score.desc())
        .limit(1)
    ).first()
    similar = (
        None if top_pair is None else (top_pair[1] if top_pair[0] == work.work_id else top_pair[0])
    )

    channels = []
    for name in sorted(_SIGNALS, key=lambda n: contribution[n], reverse=True):
        if contribution[name] <= 1e-6:
            continue
        without = to_score(evidence - contribution[name])
        needed_signal = (
            max(0.0, signals[name] - reduction / weights[name]) if weights[name] else 0.0
        )
        channels.append(
            {
                "channel": name,
                "signal": round(signals[name], 3),
                "contribution": round(contribution[name], 4),
                "score_without": round(without, 2),
                "clears_alone": without < target,
                "signal_needed": round(needed_signal, 3)
                if reduction <= contribution[name] + 1e-9
                else None,
                "condition": _condition(work, name, needed_signal, cfg, similar),
            }
        )

    # Smallest set of channels, strongest first, whose removal clears the queue.
    minimal: list[str] = []
    remaining = evidence
    for item in channels:
        if to_score(remaining) < target:
            break
        minimal.append(item["channel"])
        remaining -= item["contribution"]

    detail = work.detail or {}
    severe = [
        name.removeprefix("severe_")
        for name in ("severe_fast_completion", "severe_stuck_work", "severe_payment_stuck")
        if detail.get(name)
    ]
    return {
        "work_id": work.work_id,
        "in_queue": in_queue,
        "risk_score": round(work.risk_score, 2),
        "base_risk_score": round(work.base_risk_score, 2),
        "band": work.band,
        "queue_cutoff": round(target, 2),
        "channels": channels,
        "minimal_set": minimal,
        "score_after_minimal": round(to_score(remaining), 2),
        "severe_rules": severe,
        "severe_note": (
            "A severe rule fired, and the severe-rule floor keeps this work at High or above "
            "until the rule itself no longer holds, whatever the other channels say."
        )
        if severe
        else None,
        "rules": [
            {"rule": rule, **_rule_condition(work, rule, cfg)}
            for rule in (
                "rule_sanction_delay",
                "rule_stuck_work",
                "rule_cost_outlier",
                "rule_fast_completion",
                "rule_round_amount",
                "rule_vendor_concentration",
                "rule_payment_stuck",
            )
            if getattr(work, rule)
        ],
        "note": (
            "Computed from the stored detector channels with the configured fusion. It shows "
            "which evidence the score rests on; it does not say what should have been sanctioned."
        ),
    }


def _condition(
    work: models.Work,
    channel: str,
    needed_signal: float,
    cfg: dict[str, Any],
    similar_work: str | None = None,
) -> dict:
    if channel == "cost":
        z = (work.detail or {}).get("cost_residual_z")
        ratio = work.cost_ratio
        ecfg = cfg["expected_cost"]
        if work.cost_channel == "expected" and z and ratio and float(z) > 0 and float(ratio) > 1:
            z = float(z)
            z_target = float(ecfg["signal_z_start"]) + needed_signal * (
                float(ecfg["signal_z_full"]) - float(ecfg["signal_z_start"])
            )
            if z_target < z:
                amount = float(work.sanction_amount) * float(ratio) ** (-(z - z_target) / z)
                return _say("cost", amount=_inr(work.sanction_amount), target=_inr(amount))
        return _say("cost_general")
    if channel == "duplicate":
        if (work.split_score or 0) >= (work.dup_score or 0) and (work.split_score or 0) > 0:
            return _say("split")
        return _say("duplicate", pair=similar_work or "the most similar work")
    if channel == "delay":
        return _say("delay")
    if channel == "rule":
        fired = [r for r in ("rule_stuck_work", "rule_cost_outlier") if getattr(work, r)]
        return _rule_condition(work, fired[0], cfg) if fired else _say("model")
    return _say("model")


def _rule_condition(work: models.Work, rule: str, cfg: dict[str, Any]) -> dict[str, str]:
    rules = cfg["rules"]
    values = {
        "days": {
            "rule_sanction_delay": rules["sanction_delay_days"],
            "rule_fast_completion": rules["fast_completion_days"],
        }.get(rule, ""),
        "stage": work.work_status or "",
    }
    return _say(rule, **values)
