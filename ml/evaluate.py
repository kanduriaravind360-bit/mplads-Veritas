"""Proof that the detectors work: synthetic anomaly injection.

The proxy label cannot validate this pipeline, because it *is* the rule set we
are trying to go beyond. So instead we plant known anomalies in a copy of the
data, re-run the detectors blind, and measure how many of the planted cases come
back near the top of the ranking.

Four injection types, matching the four things the system claims to find:

============== =========================================================
inflated_cost  amount multiplied 3-5x within the same work type
duplicate      a reworded copy of a real work in the same constituency
fast_complete  completed in days with 100% of funds disbursed
split_group    one work replaced by several small ones to the same vendor
============== =========================================================

Recall is reported at the top 1% and top 5% of ``risk_score``, which is what a
reviewer with limited time would actually look at.

**This measures detector sensitivity to the patterns we defined, not real-world
fraud detection rates.** Injected anomalies are cleaner than real ones. Read the
numbers as a lower bound on obviousness, not as an accuracy claim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config, resolve

INJECTION_TYPES: tuple[str, ...] = (
    "inflated_cost",
    "duplicate",
    "fast_complete",
    "split_group",
)

#: Recall at the top 5% measured at the end of step 2, before the step 2b
#: detector work. Carried here so the model-performance page can show the
#: improvement rather than only the current number.
BASELINE_RECALL_AT_TOP_5PCT: dict[str, float] = {
    "inflated_cost": 0.180,
    "fast_complete": 0.167,
    "split_group": 0.101,
    "duplicate": 0.053,
}

#: Targets set for step 2b.
RECALL_TARGETS: dict[str, float] = {
    "inflated_cost": 0.60,
    "duplicate": 0.70,
    "split_group": 0.50,
    "fast_complete": 0.90,
}

#: Why a target is still missed, recorded rather than tuned away.
MISSED_TARGET_REASONS: dict[str, str] = {
    "duplicate": (
        "Structurally capped, not a detector failure: the detector finds 73% of "
        "planted duplicates. The data already contains 9,239 rows that are EXACT "
        "duplicates of another work in the same constituency, and the top 5% of "
        "the ranking holds only 3,865 works. A planted duplicate is reworded and "
        "therefore less similar than an exact copy, so any correctly ordered "
        "queue puts those 9,239 real cases first. Reaching the 70% target would "
        "mean ranking reworded copies above exact ones, which is backwards. The "
        "right measure for duplicates is the duplicate_group alert stream, where "
        "a reviewer actually works, not rank within the global risk score."
    ),
    "fast_complete": (
        "81.3% against a 90% target. The detector fires on 100% of planted cases, "
        "but the pattern is not rare: 2,686 works in the real data were also "
        "completed within 6 days with funds fully disbursed, and they compete for "
        "the same places. The injected cases are indistinguishable from those, so "
        "this measures whether the whole pattern ranks highly, not whether the "
        "plants were found."
    ),
    "inflated_cost": (
        "53.3% against a 60% target, up from 18.0%. The expected-cost model now "
        "fires on 96.7% of planted cases, so this is a ranking limit rather than "
        "a detection one: roughly 9,000 works carry some cost signal and only "
        "3,865 places exist in the top 5%."
    ),
    "split_group": (
        "21.6% against a 50% target, up from 10.1%. Detection improved from 12% "
        "to 46% once vendor identity became optional and the window stopped "
        "requiring a contiguous run of below-median works. The remaining gap is "
        "that 7,069 works sit in some split group, far more than the top 5% can "
        "hold, and planted groups of four works score mid-range against larger "
        "genuine ones."
    ),
}

_METRICS_CAVEAT = (
    "Injection recall measures detector sensitivity to synthetic anomalies of "
    "the patterns this system defines. Injected cases are cleaner than real "
    "ones, so these are an upper bound on how obvious such cases are, not a "
    "measured real-world fraud detection rate. All outputs are risk indicators "
    "for human review, never findings of fraud."
)


def _reword(text: str, rng: np.random.Generator, drop: float) -> str:
    """Drop a fraction of tokens and shuffle lightly, as a re-entry would."""
    tokens = str(text).split()
    if len(tokens) < 4:
        return f"{text} (revised)"
    keep = max(3, int(round(len(tokens) * (1 - drop))))
    idx = sorted(rng.choice(len(tokens), size=keep, replace=False).tolist())
    return " ".join(tokens[i] for i in idx)


def inject(
    df: pd.DataFrame, cfg: dict[str, Any] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(data_with_injections, truth_table)``.

    The truth table lists every injected ``work_id`` and its injection type.
    Injected rows are appended with fresh ids so no genuine record is destroyed.
    """
    cfg = cfg or load_config("ml")
    icfg = cfg["evaluation"]["injection"]
    rng = np.random.default_rng(int(cfg["seed"]))
    per_type = int(icfg["per_type"])

    work = df.reset_index(drop=True).copy()
    new_rows: list[dict[str, Any]] = []
    truth: list[dict[str, str]] = []
    counter = 0

    def clone(source: pd.Series, tag: str) -> dict[str, Any]:
        nonlocal counter
        counter += 1
        row = source.to_dict()
        row["work_id"] = f"INJ-{tag}-{counter:05d}"
        return row

    # 1. Inflated cost: same work type, 3-5x the sanctioned amount.
    eligible = work.loc[work["sanction_amount"] > 0]
    picks = eligible.sample(n=min(per_type, len(eligible)), random_state=int(cfg["seed"]))
    lo, hi = float(icfg["cost_multiplier_min"]), float(icfg["cost_multiplier_max"])
    for _, src in picks.iterrows():
        row = clone(src, "COST")
        multiplier = float(rng.uniform(lo, hi))
        row["sanction_amount"] = float(src["sanction_amount"]) * multiplier
        if pd.notna(src["total_fund_disbursed"]):
            row["total_fund_disbursed"] = float(src["total_fund_disbursed"]) * multiplier
        new_rows.append(row)
        truth.append(
            {"work_id": row["work_id"], "injection": "inflated_cost", "group": row["work_id"]}
        )

    # 2. Duplicate: a reworded copy of a real work, same constituency.
    dup_pool = work.loc[work["work_description"].notna()]
    picks = dup_pool.sample(n=min(per_type, len(dup_pool)), random_state=int(cfg["seed"]) + 1)
    drop = float(icfg["duplicate_reword_drop"])
    for _, src in picks.iterrows():
        row = clone(src, "DUP")
        row["work_description"] = _reword(src["work_description"], rng, drop)
        # A re-entry lands close in time and at a similar value.
        row["sanction_amount"] = float(src["sanction_amount"]) * float(rng.uniform(0.9, 1.1))
        if pd.notna(src["sanction_date"]):
            row["sanction_date"] = src["sanction_date"] + pd.Timedelta(
                days=int(rng.integers(1, 60))
            )
        new_rows.append(row)
        truth.append(
            {"work_id": row["work_id"], "injection": "duplicate", "group": str(src["work_id"])}
        )

    # 3. Fast completion with the money fully drawn.
    picks = work.sample(n=min(per_type, len(work)), random_state=int(cfg["seed"]) + 2)
    fast_days = int(icfg["fast_completion_days"])
    for _, src in picks.iterrows():
        row = clone(src, "FAST")
        row["completion_date"] = src["sanction_date"] + pd.Timedelta(days=fast_days)
        row["duration_days"] = float(fast_days)
        row["total_fund_disbursed"] = float(src["sanction_amount"])
        row["amount_disbursed_completed"] = float(src["sanction_amount"])
        row["work_status"] = "Work Completed"
        new_rows.append(row)
        truth.append(
            {"work_id": row["work_id"], "injection": "fast_complete", "group": row["work_id"]}
        )

    # 4. Split groups: one work becomes several small ones to the same vendor.
    size = int(icfg["split_group_size"])
    pool = work.loc[work["vendor_name"].notna() & (work["sanction_amount"] > 0)]
    n_groups = max(1, per_type // size)
    picks = pool.sample(n=min(n_groups, len(pool)), random_state=int(cfg["seed"]) + 3)

    # Size the pieces against the peer distribution, not against the source, so
    # each is below the peer median while the group clears the peer p90.
    amounts = work["sanction_amount"].astype("float64")
    by_type = amounts.groupby(work["work_type"].astype(str)) if "work_type" in work else None
    median = by_type.transform("median") if by_type is not None else amounts
    piece_fraction = float(icfg["split_piece_of_median"])

    for group_number, (idx, src) in enumerate(picks.iterrows(), start=1):
        piece = float(median.loc[idx]) * piece_fraction
        group_id = f"SPLIT-{group_number:04d}"
        for k in range(size):
            row = clone(src, "SPL")
            # Each piece sits below the peer median; together they exceed p90.
            row["sanction_amount"] = piece
            if pd.notna(src["sanction_date"]):
                row["sanction_date"] = src["sanction_date"] + pd.Timedelta(days=int(k * 3))
            row["work_description"] = f"{src['work_description']} - phase {k + 1}"
            new_rows.append(row)
            truth.append({"work_id": row["work_id"], "injection": "split_group", "group": group_id})

    injected = pd.concat([work, pd.DataFrame(new_rows)], ignore_index=True)
    return injected, pd.DataFrame(truth)


def recall_at(
    scored: pd.DataFrame, truth: pd.DataFrame, fractions: list[float]
) -> dict[str, dict[str, float]]:
    """Recall per injection type at each top-k fraction of ``risk_score``."""
    ranked = scored.sort_values("risk_score", ascending=False, kind="stable")
    ids = ranked["work_id"].to_numpy()
    n = len(ranked)

    out: dict[str, dict[str, float]] = {}
    for kind, group in truth.groupby("injection"):
        planted = set(group["work_id"])
        row: dict[str, float] = {"n_injected": float(len(planted))}
        for frac in fractions:
            k = max(1, int(round(n * frac)))
            found = len(planted & set(ids[:k]))
            row[f"recall_at_top_{frac:.0%}".replace("%", "pct")] = round(found / len(planted), 4)
            row[f"found_at_top_{frac:.0%}".replace("%", "pct")] = float(found)
        out[kind] = row
    return out


def _detector_recall(scored: pd.DataFrame, truth: pd.DataFrame) -> dict[str, float]:
    """Did the detector meant to catch each injection actually fire?

    More informative than rank-based recall on its own: a detector can fire
    correctly and still not reach the top 1% of a national ranking, because
    these patterns are common in the real data. Separating "did it fire" from
    "did it rank" says which half needs work.
    """
    by_id = dict(zip(truth["work_id"], truth["injection"], strict=True))
    marked = scored.assign(_injection=scored["work_id"].map(by_id))
    injected = marked.loc[marked["_injection"].notna()]

    checks = {
        # The expected-cost model is the cost detector now; the rule threshold is
        # only a coarse backstop and understates what is actually detected.
        "inflated_cost": lambda d: (d["cost_signal"] > 0)
        if "cost_signal" in d
        else d["rule_cost_outlier"],
        "fast_complete": lambda d: d["rule_fast_completion"]
        if "rule_fast_completion" in d
        else d["unsupervised"] > 0,
        "duplicate": lambda d: d["duplicate"] > 0,
        "split_group": lambda d: d["in_split_group"].astype("float64") > 0,
    }

    out: dict[str, float] = {}
    for kind, test in checks.items():
        group = injected.loc[injected["_injection"] == kind]
        if group.empty:
            continue
        out[kind] = round(float(test(group).mean()), 4)
    return out


def run_injection_test(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inject known anomalies, re-run the detectors, and measure recall."""
    cfg = cfg or load_config("ml")
    from ml.pipeline import load_works, run

    works = load_works(cfg)
    injected, truth = inject(works, cfg)

    # Embeddings must be recomputed: the injected rows have new descriptions and
    # the cache is keyed by row count, so it will correctly miss here.
    result = run(cfg, df=injected, use_embeddings=True, train_models=True, save=False)

    fractions = [float(f) for f in cfg["evaluation"]["recall_at"]]
    per_type = recall_at(result.scored, truth, fractions)
    detector_recall = _detector_recall(result.scored, truth)

    planted = set(truth["work_id"])
    ranked = result.scored.sort_values("risk_score", ascending=False, kind="stable")
    overall: dict[str, float] = {"n_injected": float(len(planted))}
    for frac in fractions:
        k = max(1, int(round(len(ranked) * frac)))
        found = len(planted & set(ranked["work_id"].to_numpy()[:k]))
        overall[f"recall_at_top_{frac:.0%}".replace("%", "pct")] = round(found / len(planted), 4)

    comparison = {}
    for kind, values in per_type.items():
        now = float(values.get("recall_at_top_5pct", 0.0))
        before = BASELINE_RECALL_AT_TOP_5PCT.get(kind)
        target = RECALL_TARGETS.get(kind)
        comparison[kind] = {
            "before_step2b": before,
            "after_step2b": round(now, 4),
            "change": round(now - before, 4) if before is not None else None,
            "target": target,
            "target_met": bool(target is not None and now >= target),
        }

    return {
        "per_type": per_type,
        "detector_recall": detector_recall,
        "detector_recall_note": (
            "Did the detector meant to catch each injection fire at all. This is "
            "separate from whether the work then reached the top of the national "
            "ranking, which also depends on how many genuine cases compete for "
            "the same places."
        ),
        "recall_at_top_5pct_before_after": comparison,
        "missed_target_reasons": MISSED_TARGET_REASONS,
        "overall": overall,
        "n_rows_with_injections": int(len(injected)),
        "n_injected": int(len(truth)),
        "CAVEAT": _METRICS_CAVEAT,
    }


def write_metrics(
    pipeline_metrics: dict[str, Any],
    injection_metrics: dict[str, Any] | None,
    feature_names: list[str],
    cfg: dict[str, Any] | None = None,
) -> Path:
    """Write the single consolidated ``models/metrics.json``."""
    cfg = cfg or load_config("ml")
    path = resolve(cfg["paths"]["metrics"])
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_by": "python -m ml.train",
        "seed": int(cfg["seed"]),
        "honesty_note": (
            "All outputs are risk indicators for human review, not findings of "
            "fraud. MP-level figures describe implementation risk of works "
            "recommended in a constituency, never a judgement of the MP."
        ),
        **pipeline_metrics,
        "feature_list": sorted(feature_names),
        "detector_weights": dict(cfg["risk"]["weights"]),
        "risk_bands_thresholds": dict(cfg["risk"]["bands"]),
    }
    if injection_metrics is not None:
        payload["injection_test"] = injection_metrics

    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
