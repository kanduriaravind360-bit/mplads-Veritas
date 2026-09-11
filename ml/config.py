"""Configuration loading.

All thresholds, mappings and paths live in ``configs/*.yaml`` (CLAUDE.md rule 5).
Modules read them through here rather than hard-coding values.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "configs"

SEED = 42


@cache
def load_config(name: str = "data") -> dict[str, Any]:
    """Load ``configs/<name>.yaml`` and return it as a dict.

    Results are cached, so the file is read once per process.
    """
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if not isinstance(cfg, dict):
        raise ValueError(f"config {path} did not parse to a mapping")
    return cfg


def resolve(relative: str) -> Path:
    """Turn a repo-relative path from a config file into an absolute path."""
    return PROJECT_ROOT / relative
