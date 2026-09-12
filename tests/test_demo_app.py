"""Checks for the Streamlit demo app.

The app is a presentation surface, so the things worth testing are that it will
open at all, that it never trains anything, and that the honesty rules it is
supposed to display are actually in it.

Streamlit's script runner is not exercised here; importing ``demo_app`` would
execute the whole page. These tests read the module and the artefacts it
depends on instead, which is enough to catch the failures that would matter on
stage: a missing column, a renamed artefact, or a caveat quietly dropped.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "demo_app.py"


@pytest.fixture(scope="module")
def source() -> str:
    return APP.read_text(encoding="utf-8")


def test_demo_app_exists_and_parses(source: str) -> None:
    """A syntax error here means a blank screen in front of the judges."""
    assert APP.exists(), "demo_app.py is missing"
    ast.parse(source)


def test_demo_app_never_trains(source: str) -> None:
    """The app must read artefacts, not rebuild them.

    ``score_new_works`` is allowed: it scores an upload with the saved models.
    Calling the training entry points would take minutes and change the outputs
    mid-demo.
    """
    tree = ast.parse(source)
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for banned in ("train", "run_injection_test", "fit_predict", "find_duplicates"):
        assert banned not in called, f"demo app calls {banned}(), which retrains"


def test_demo_app_caches_every_loader(source: str) -> None:
    """Uncached loading of a 77k-row parquet on every rerun makes the app crawl."""
    tree = ast.parse(source)
    loaders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("load_")
    ]
    assert loaders, "no loader functions found"
    for func in loaders:
        decorators = ast.unparse(ast.Module(body=func.decorator_list, type_ignores=[]))
        assert "cache_data" in decorators, f"{func.name} is not cached"


def test_demo_app_states_the_honesty_caveats(source: str) -> None:
    """CLAUDE.md rule 4 applies hardest to the surface a judge actually sees."""
    assert "risk indicator" in source.lower()
    assert "never about the Member" in source or "never a judgement" in source
    # The two weak results must be on the page, not buried.
    assert "weakest at 46%" in source
    assert "not a verified fraud case" in source or "not a fraud detection rate" in source


def test_demo_app_reads_only_existing_artefacts() -> None:
    """Every artefact the app expects must be something the pipeline produces."""
    processed = ROOT / "data" / "processed"
    if not (processed / "scored_works.parquet").exists():
        pytest.skip("pipeline output not built in this environment")

    for name in ("scored_works", "duplicates", "split_groups", "rollup_state"):
        assert (processed / f"{name}.parquet").exists(), f"{name}.parquet missing"
    assert (ROOT / "models" / "metrics.json").exists()


def test_scored_output_has_the_columns_the_app_needs() -> None:
    """The columns the demo reads must survive any pipeline change."""
    path = ROOT / "data" / "processed" / "scored_works.parquet"
    if not path.exists():
        pytest.skip("pipeline output not built in this environment")

    columns = set(pd.read_parquet(path).columns)
    required = {
        "work_id",
        "state",
        "work_type",
        "work_description",
        "sanction_amount",
        "sanction_date",
        "completion_date",
        "risk_score",
        "band",
        "reasons_en",
        "reasons_hi",
        # Per-detector contributions drive the detail panel.
        "rule",
        "supervised",
        "unsupervised",
        "cost",
        "duplicate",
        "delay",
        # The delay page needs the raw probability, not the fused signal.
        "delay_risk",
    }
    missing = required - columns
    assert not missing, f"scored_works.parquet is missing: {sorted(missing)}"


def test_demo_script_names_real_works() -> None:
    """The walkthrough must reference works that exist in the data."""
    script = ROOT / "docs" / "DEMO_SCRIPT.md"
    assert script.exists(), "docs/DEMO_SCRIPT.md is missing"
    text = script.read_text(encoding="utf-8")

    path = ROOT / "data" / "processed" / "scored_works.parquet"
    if not path.exists():
        pytest.skip("pipeline output not built in this environment")

    work_ids = set(pd.read_parquet(path, columns=["work_id"])["work_id"])
    quoted = {"WS/MP18249/2025-2026/187616", "WS/MP18249/2025-2026/187617"}
    for work_id in quoted:
        assert work_id in text, f"{work_id} is not in the demo script"
        assert work_id in work_ids, f"{work_id} is not in the data"
