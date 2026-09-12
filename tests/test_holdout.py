"""The holdout must be genuinely held out, and the demo works must be honest.

The value of a holdout is entirely in whether the exclusion is real, so these
tests try to catch the ways it could quietly stop being real: a drifting split,
a held-out constituency reappearing in the scored training output, or the demo
CSV naming a real MP.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ml.config import load_config
from ml.holdout import choose_constituencies, split, verify

ROOT = Path(__file__).resolve().parents[1]
DEMO_CSV = ROOT / "demo_data" / "live_demo_works.csv"


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config("ml")


@pytest.fixture(scope="module")
def works() -> pd.DataFrame:
    path = ROOT / "data" / "processed" / "works.parquet"
    if not path.exists():
        pytest.skip("works.parquet not built in this environment")
    return pd.read_parquet(path)


# --- the split itself ------------------------------------------------------


def test_split_is_deterministic(works: pd.DataFrame, cfg: dict) -> None:
    """A holdout that moves between runs proves nothing."""
    assert choose_constituencies(works, cfg) == choose_constituencies(works, cfg)


def test_split_is_stable_under_row_order(works: pd.DataFrame, cfg: dict) -> None:
    """Re-sorting the data must not change which areas are held out."""
    shuffled = works.sample(frac=1.0, random_state=7).reset_index(drop=True)
    assert choose_constituencies(works, cfg) == choose_constituencies(shuffled, cfg)


def test_split_holds_out_whole_constituencies(works: pd.DataFrame, cfg: dict) -> None:
    """No constituency may appear on both sides, or the exclusion leaks."""
    result = split(works, cfg)
    assert result.checks["no_shared_constituency"]
    assert result.checks["no_shared_work_id"]
    assert len(result.train) + len(result.holdout) == len(works)


def test_holdout_is_about_the_requested_size(works: pd.DataFrame, cfg: dict) -> None:
    target = float(cfg["holdout"]["fraction"])
    share = split(works, cfg).checks["holdout_share_of_works"]
    assert abs(share - target) < 0.02, f"holdout is {share:.1%}, wanted about {target:.0%}"


def test_verify_catches_a_leak() -> None:
    """The check must fail on a bad split, not just pass on a good one."""
    frame = pd.DataFrame({"work_id": ["A", "B"], "constituency": ["X", "X"]})
    leaked = verify(frame, frame)
    assert not leaked["no_shared_work_id"]
    assert not leaked["no_shared_constituency"]


# --- the exclusion actually held ------------------------------------------


def test_no_holdout_constituency_reaches_the_scored_output(works: pd.DataFrame, cfg: dict) -> None:
    """The strongest check: re-derive the split and look for it in the output.

    If a held-out constituency appears in scored_works.parquet, then it was in
    the population every statistic and every model was built from.
    """
    scored_path = ROOT / "data" / "processed" / "scored_works.parquet"
    if not scored_path.exists():
        pytest.skip("scored_works.parquet not built in this environment")

    held = set(choose_constituencies(works, cfg))
    scored_areas = set(
        pd.read_parquet(scored_path, columns=["constituency"])["constituency"].astype(str)
    )
    leaked = held & scored_areas
    assert not leaked, (
        f"held-out constituencies present in the training output: {sorted(leaked)[:5]}"
    )


def test_holdout_parquet_matches_the_config(cfg: dict) -> None:
    """The saved holdout must be the constituencies the config claims."""
    import yaml

    path = ROOT / "data" / "processed" / "holdout_works.parquet"
    config_path = ROOT / "configs" / "holdout.yaml"
    if not path.exists() or not config_path.exists():
        pytest.skip("holdout not built in this environment")

    recorded = set(yaml.safe_load(config_path.read_text(encoding="utf-8"))["constituencies"])
    actual = set(pd.read_parquet(path, columns=["constituency"])["constituency"].astype(str))
    assert actual == recorded


# --- the demo works --------------------------------------------------------


def test_demo_csv_exists_and_covers_every_scenario() -> None:
    if not DEMO_CSV.exists():
        pytest.skip("demo CSV not built in this environment")
    demo = pd.read_csv(DEMO_CSV)

    keys = set(demo["demo_key"])
    for expected in (
        "ordinary_solar",
        "overpriced_8x",
        "duplicate_copy",
        "fast_completion",
        "stalled",
    ):
        assert expected in keys, f"demo CSV is missing {expected}"
    assert sum(key.startswith("split_") for key in keys) >= 3
    assert len(demo) >= 12


def test_demo_works_are_clearly_synthetic() -> None:
    """CLAUDE.md rule 4: invented works must not be pinned on a real person."""
    if not DEMO_CSV.exists():
        pytest.skip("demo CSV not built in this environment")
    demo = pd.read_csv(DEMO_CSV)

    assert (demo["work_id"].astype(str).str.startswith("DEMO-")).all()
    for column in ("mp_name", "constituency"):
        values = demo[column].astype(str).str.lower()
        assert values.str.contains("demo|synthetic|placeholder").all(), (
            f"{column} does not mark these rows as invented"
        )

    works_path = ROOT / "data" / "processed" / "works.parquet"
    if works_path.exists():
        real = pd.read_parquet(works_path, columns=["mp_name", "work_id"])
        assert not set(demo["mp_name"]) & set(real["mp_name"].astype(str))
        assert not set(demo["work_id"]) & set(real["work_id"].astype(str))


def test_demo_csv_has_the_columns_scoring_needs() -> None:
    if not DEMO_CSV.exists():
        pytest.skip("demo CSV not built in this environment")
    demo = pd.read_csv(DEMO_CSV)
    required = {
        "work_id",
        "state",
        "ida",
        "constituency",
        "work_description",
        "sanction_date",
        "sanction_amount",
        "work_status",
        "recommended_date",
    }
    assert required <= set(demo.columns), f"missing: {sorted(required - set(demo.columns))}"
