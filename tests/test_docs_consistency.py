"""Docs and deck quote the system's own numbers, and name no real person."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    # Dataclasses look their module up by name while the class is being built.
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_quoted_model_numbers_match_metrics() -> None:
    checker = _script("check_numbers")
    metrics = json.loads((ROOT / "models" / "metrics.json").read_text(encoding="utf-8"))
    missing = checker.check(checker.metric_claims(metrics))
    assert not missing, "\n".join(missing)


def test_no_committed_file_names_a_real_mp_or_vendor() -> None:
    if not (ROOT / "data" / "processed" / "works.parquet").exists():
        pytest.skip("processed data not built in this environment")
    assert _script("privacy_scan").main() == 0
