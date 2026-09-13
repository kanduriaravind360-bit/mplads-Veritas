"""Planted cases for the reviewer-learning panel.

    python -m ml.planted

Runs the evaluation's injection (``ml.evaluate.inject``, seed 42: inflated cost,
reworded duplicates, implausibly fast completion, split groups) through the full
pipeline and saves ONLY the planted rows with their six fusion channels.

These are synthetic works whose anomaly type is known by construction, which is
why the learning panel may treat them as confirmed positives: no real work is
ever labelled confirmed. They are loaded into their own table, never as works,
so they cannot appear in any dashboard, count or map.

Nothing committed changes: models, metrics and scored outputs are not written.
"""

from __future__ import annotations

import time

import pandas as pd

from ml.config import load_config, resolve
from ml.evaluate import inject
from ml.pipeline import load_works, run
from ml.risk import _SIGNALS


def main() -> None:
    started = time.perf_counter()
    cfg = load_config("ml")
    works = load_works(cfg)
    injected, truth = inject(works, cfg)
    result = run(cfg, df=injected, use_embeddings=True, train_models=True, save=False)

    planted = result.scored.merge(truth, on="work_id", how="inner")
    columns = [
        "work_id",
        "injection",
        *_SIGNALS,
        "base_risk_score",
        "risk_score",
        "band",
        "severe_rule_count",
        "completion_date",
        "work_type",
        "state",
    ]
    out = planted[[c for c in columns if c in planted.columns]].copy()
    out["is_open"] = out["completion_date"].isna() if "completion_date" in out else True
    out = out.drop(columns=["completion_date"], errors="ignore")

    path = resolve(cfg["paths"]["planted_scored"])
    out.to_parquet(path, index=False)
    bands = out["band"].value_counts().to_dict()
    print(
        f"{len(out)} planted cases saved to {path} in {time.perf_counter() - started:.0f}s; "
        f"bands {bands}; by type {out['injection'].value_counts().to_dict()}"
    )


if __name__ == "__main__":
    pd.set_option("display.width", 160)
    main()
