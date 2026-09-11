"""Invariants of the MPLADS works dataset.

These guard the two things every later step depends on: that we are looking at
the full 77,312-work extract, and that the proxy label is exactly the weighted
flag rule it claims to be (CLAUDE.md rule 3).
"""

from __future__ import annotations

import pandas as pd
import pytest

from ml.config import load_config
from ml.data import FLAG_COLUMNS, compute_anomaly_score, load_processed

EXPECTED_ROWS = 77_312

EXPECTED_WEIGHTS: dict[str, int] = {
    "flag_sanction_delay": 2,
    "flag_stuck_work": 3,
    "flag_cost_outlier": 3,
    "flag_fast_completion": 2,
    "flag_round_amount": 1,
    "flag_vendor_concentration": 3,
    "flag_payment_stuck": 1,
}

EXPECTED_THRESHOLD = 4


@pytest.fixture(scope="module")
def works() -> pd.DataFrame:
    """The cleaned works table, built from the raw workbook if not yet cached."""
    return load_processed()


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config("data")


def test_row_count(works: pd.DataFrame) -> None:
    assert len(works) == EXPECTED_ROWS


def test_work_id_is_unique(works: pd.DataFrame) -> None:
    assert works["work_id"].is_unique
    assert works["work_id"].notna().all()


def test_config_matches_documented_weights(cfg: dict) -> None:
    """The config must carry the weights from the problem statement, unchanged."""
    assert cfg["flag_weights"] == EXPECTED_WEIGHTS
    assert cfg["anomaly_label_threshold"] == EXPECTED_THRESHOLD


def test_anomaly_score_reproduces_from_flags(works: pd.DataFrame) -> None:
    """anomaly_score is exactly the weighted sum of the seven flag columns."""
    recomputed = compute_anomaly_score(works)
    mismatches = int((recomputed != works["anomaly_score"]).sum())
    assert mismatches == 0, f"{mismatches} rows where the weighted flag sum != anomaly_score"


def test_anomaly_score_reproduces_with_literal_weights(works: pd.DataFrame) -> None:
    """Same check, weights written out literally so the test does not trust the config."""
    score = sum(works[col].astype(int) * weight for col, weight in EXPECTED_WEIGHTS.items())
    assert score.equals(works["anomaly_score"].astype(int))


def test_label_is_score_at_or_above_threshold(works: pd.DataFrame) -> None:
    """anomaly_label == (anomaly_score >= 4), with no exceptions."""
    expected = (works["anomaly_score"] >= EXPECTED_THRESHOLD).astype(int)
    assert expected.equals(works["anomaly_label"].astype(int))


def test_all_flag_columns_present_and_boolean(works: pd.DataFrame) -> None:
    for col in FLAG_COLUMNS:
        assert col in works.columns
        assert works[col].dtype == bool
