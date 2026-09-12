"""Constituency-level holdout, reserved before anything is fitted.

The injection test proves the detectors respond to planted anomalies. It cannot
prove the models generalise, because every work it scores was also part of the
population the models and the peer statistics were built from.

This reserves 5% of works and keeps them out of everything:

* out of the delay model, the proxy-label model and the expected-cost model;
* out of every peer, vendor, district and constituency statistic, so a held-out
  work never even contributes to the median another work is compared against.

The split is by **whole constituency**, not by row. Splitting rows would leave a
held-out work's neighbours in training, and since vendor concentration and
district history are computed within an area, the model would effectively have
seen it. Holding out whole constituencies removes that path.

Selection is deterministic: constituencies are hashed with the seed, so the same
constituencies are held out on every run and on any machine, and the choice
cannot drift when the data is re-sorted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ml.config import load_config, resolve


@dataclass
class HoldoutSplit:
    """A train/holdout split and the evidence that it is clean."""

    train: pd.DataFrame
    holdout: pd.DataFrame
    constituencies: list[str]
    checks: dict[str, Any]


def _bucket(name: str, seed: int) -> float:
    """Stable 0-1 position for a constituency, from its name and the seed."""
    digest = hashlib.blake2b(f"{seed}:{name}".encode(), digest_size=8).hexdigest()
    return int(digest, 16) / float(1 << 64)


def choose_constituencies(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> list[str]:
    """Pick the constituencies to hold out, deterministically.

    Constituencies are taken in hash order until the requested share of WORKS is
    reached, so the holdout is about the right size in rows even though whole
    areas are removed at a time.
    """
    cfg = cfg or load_config("ml")
    hcfg = cfg["holdout"]
    seed = int(cfg["seed"])
    target = float(hcfg["fraction"])

    counts = df["constituency"].astype(str).value_counts()
    ordered = sorted(counts.index, key=lambda name: _bucket(name, seed))

    total = int(counts.sum())
    chosen: list[str] = []
    running = 0
    for name in ordered:
        if running / total >= target:
            break
        chosen.append(name)
        running += int(counts[name])
    return sorted(chosen)


def split(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> HoldoutSplit:
    """Split into train and holdout by whole constituency."""
    cfg = cfg or load_config("ml")
    names = choose_constituencies(df, cfg)
    held = df["constituency"].astype(str).isin(set(names))

    train = df.loc[~held].reset_index(drop=True)
    holdout = df.loc[held].reset_index(drop=True)
    return HoldoutSplit(
        train=train,
        holdout=holdout,
        constituencies=names,
        checks=verify(train, holdout),
    )


def verify(train: pd.DataFrame, holdout: pd.DataFrame) -> dict[str, Any]:
    """Evidence that no held-out work can reach a fitted model or a statistic.

    Every one of these must hold. They are written into ``models/metrics.json``
    so the claim is checkable rather than asserted.
    """
    train_ids = set(train["work_id"])
    holdout_ids = set(holdout["work_id"])
    train_areas = set(train["constituency"].astype(str))
    holdout_areas = set(holdout["constituency"].astype(str))

    total = len(train) + len(holdout)
    return {
        "n_train": len(train),
        "n_holdout": len(holdout),
        "holdout_share_of_works": round(len(holdout) / total, 4) if total else 0.0,
        "n_holdout_constituencies": len(holdout_areas),
        "no_shared_work_id": len(train_ids & holdout_ids) == 0,
        "no_shared_constituency": len(train_areas & holdout_areas) == 0,
        "split_unit": "whole constituency",
        "why_constituency": (
            "Splitting by row would leave a held-out work's neighbours in "
            "training, and vendor concentration and district history are computed "
            "within an area, so the model would effectively have seen it."
        ),
    }


def write_config(
    names: list[str], checks: dict[str, Any], cfg: dict[str, Any] | None = None
) -> Path:
    """Record the held-out constituencies in ``configs/holdout.yaml``."""
    cfg = cfg or load_config("ml")
    path = resolve("configs/holdout.yaml")
    payload = {
        "generated_by": "ml.holdout.split, via python -m ml.train",
        "seed": int(cfg["seed"]),
        "fraction_requested": float(cfg["holdout"]["fraction"]),
        "note": (
            "These constituencies are excluded from every fitted model and from "
            "every peer, vendor, district and constituency statistic. Selection "
            "is a deterministic hash of the constituency name and the seed, so "
            "it is identical on any machine and cannot drift."
        ),
        "checks": checks,
        "constituencies": names,
    }
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=88),
        encoding="utf-8",
    )
    return path


def save(holdout: pd.DataFrame, cfg: dict[str, Any] | None = None) -> Path:
    """Write the held-out works to parquet."""
    cfg = cfg or load_config("ml")
    path = resolve(cfg["paths"]["holdout_works"])
    path.parent.mkdir(parents=True, exist_ok=True)
    holdout.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
    return path


def load(cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Read the held-out works, if they have been built."""
    cfg = cfg or load_config("ml")
    path = resolve(cfg["paths"]["holdout_works"])
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run `python -m ml.train` to build the holdout.")
    return pd.read_parquet(path)


def is_enabled(cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or load_config("ml")
    return bool(cfg.get("holdout", {}).get("enabled", False))
