"""Phase A: severe-rule floor, state-relative cost channel, split routing.

Each test pins the behaviour that was wrong before, on small synthetic frames,
so it runs in seconds and does not depend on the national corpus.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml import cost_peers
from ml.config import load_config
from ml.detect_duplicates import find_split_works, fit_split_peer_stats
from ml.pipeline import build_alerts
from ml.risk import _cost_reason, apply_severe_floor, band_for
from ml.rules import severe_rules_fired

CUTS = {"critical": 95.0, "high": 85.0, "medium": 64.0}


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config("ml")


# --- 1. severe-rule floor ---------------------------------------------------


def test_one_severe_rule_lifts_a_low_work_into_high(cfg: dict) -> None:
    """A work that fused to 61 (Low) with a severe rule fired must reach High."""
    df = pd.DataFrame({"severe_rule_count": [0, 1]})
    risk = pd.Series([61.2, 61.2])
    new, lifted = apply_severe_floor(risk, df, CUTS, cfg)

    assert band_for(new.iloc[0], cfg, CUTS) != "High", "no severe rule, no lift"
    assert band_for(new.iloc[1], cfg, CUTS) == "High"
    assert lifted.tolist() == [False, True]


def test_two_severe_rules_lift_into_critical(cfg: dict) -> None:
    df = pd.DataFrame({"severe_rule_count": [2]})
    new, _ = apply_severe_floor(pd.Series([40.0]), df, CUTS, cfg)
    assert band_for(new.iloc[0], cfg, CUTS) == "Critical"


def test_floor_keeps_order_and_leaves_higher_scores_alone(cfg: dict) -> None:
    """Lifted works are ordered by their original score and not all tied."""
    df = pd.DataFrame({"severe_rule_count": [1, 1, 1]})
    risk = pd.Series([20.0, 60.0, 92.0])
    new, lifted = apply_severe_floor(risk, df, CUTS, cfg)

    assert new.iloc[0] < new.iloc[1], "original ordering must survive the lift"
    assert new.iloc[2] == pytest.approx(92.0), "a work already above the floor is untouched"
    assert not lifted.iloc[2]
    headroom = float(cfg["rules"]["severe_floor"]["floor_headroom"])
    assert new.iloc[1] <= CUTS["high"] + headroom * (CUTS["critical"] - CUTS["high"]) + 1e-9


def test_fast_completion_is_severe_only_within_a_day_and_fully_paid(cfg: dict) -> None:
    df = pd.DataFrame(
        {
            "sanction_amount": [100.0, 100.0, 100.0, 100.0],
            "total_fund_disbursed": [100.0, 100.0, 50.0, 100.0],
            "duration_days": [1.0, 3.0, 1.0, 0.0],
        }
    )
    rules = pd.DataFrame(
        {
            "rule_fast_completion": [True, True, True, True],
            "rule_stuck_work": [False] * 4,
            "rule_payment_stuck": [False] * 4,
        }
    )
    fired = severe_rules_fired(df, rules, cfg)
    # 1 day paid, 3 days paid, 1 day half paid, same day paid
    assert fired["severe_fast_completion"].tolist() == [True, False, False, True]


def test_round_amount_is_not_severe(cfg: dict) -> None:
    """It fires on 36% of works; making it severe would flood the queue."""
    assert "rule_round_amount" not in cfg["rules"]["severe"]


# --- 2. state-relative cost channel -----------------------------------------


def _two_state_corpus(n: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    cheap = 20_000 * np.exp(rng.normal(0, 0.05, n))
    dear = 60_000 * np.exp(rng.normal(0, 0.05, n))
    return pd.DataFrame(
        {
            "work_type": ["Solar Light"] * (2 * n),
            "state": ["State A"] * n + ["State B"] * n,
            "sanction_amount": np.concatenate([cheap, dear]),
        }
    )


def test_state_channel_flags_a_price_that_is_only_ordinary_elsewhere(cfg: dict) -> None:
    """2.5x the local median must fire even though it is normal in another state."""
    artifact = cost_peers.fit(_two_state_corpus(), cfg)
    new = pd.DataFrame(
        {
            "work_type": ["Solar Light", "Solar Light"],
            "state": ["State A", "State B"],
            "sanction_amount": [50_000.0, 50_000.0],
        }
    )
    out = cost_peers.apply(new, artifact, cfg)

    assert out["state_cost_signal"].iloc[0] > 0, "2.5x the State A median should fire"
    assert out["state_cost_signal"].iloc[1] == 0, "the same price is cheap in State B"
    assert out["state_peer_label"].iloc[0] == "Solar Light in State A"
    assert out["state_cost_ratio"].iloc[0] == pytest.approx(2.5, rel=0.05)


def test_state_channel_falls_back_when_the_state_is_too_thin(cfg: dict) -> None:
    corpus = _two_state_corpus()
    artifact = cost_peers.fit(corpus, cfg)
    unseen = pd.DataFrame(
        {"work_type": ["Solar Light"], "state": ["Nowhere"], "sanction_amount": [40_000.0]}
    )
    out = cost_peers.apply(unseen, artifact, cfg)
    assert out["state_peer_scope"].iloc[0] in {"cost_band", "national"}


def test_stronger_cost_channel_wins_and_is_named() -> None:
    state = pd.DataFrame(
        {"state_cost_signal": [0.9, 0.1, 0.0], "state_cost_ratio": [2.5, 1.2, 1.0]}
    )
    expected = pd.Series([0.2, 0.5, 0.0])
    ratio = pd.Series([1.4, 2.1, 1.0])
    out = cost_peers.combine(expected, state, ratio)

    assert out["cost_channel"].tolist() == ["state_peer", "expected", ""]
    assert out["cost_signal"].tolist() == [0.9, 0.5, 0.0]
    assert out["cost_ratio"].tolist() == [2.5, 2.1, 1.0]


def test_cost_reason_says_which_channel_fired() -> None:
    templates = load_config("reasons")
    state_row = pd.Series(
        {
            "cost_channel": "state_peer",
            "cost_signal": 0.6,
            "cost_ratio": 2.5,
            "state_peer_label": "Solar Light in Uttar Pradesh",
        }
    )
    expected_row = pd.Series(
        {
            "cost_channel": "expected",
            "cost_signal": 0.6,
            "cost_ratio": 2.1,
            "expected_cost_amount": 100_000.0,
            "sanction_amount": 210_000.0,
        }
    )
    state_text = _cost_reason(state_row, templates)
    expected_text = _cost_reason(expected_row, templates)

    assert state_text and "2.5x the median for Solar Light in Uttar Pradesh" in state_text[0]
    assert expected_text and "2.1x the cost predicted from this description" in expected_text[0]


# --- 3. split routing ---------------------------------------------------------


def _split_batch() -> pd.DataFrame:
    """Four pieces of one road, one district, one week, each just under Rs 10 lakh."""
    amounts = [998_400.0, 997_600.0, 999_100.0, 996_900.0]
    return pd.DataFrame(
        {
            "work_id": [f"DEMO-{i}" for i in range(1, 5)],
            "ida": ["DEMO DISTRICT"] * 4,
            "constituency": ["DEMO CONSTITUENCY"] * 4,
            "state": ["Bihar"] * 4,
            "work_type": ["Road / Pavement"] * 4,
            "work_description": [
                f"Widening and strengthening of Behrapur approach road reach {i}"
                for i in range(1, 5)
            ],
            "sanction_date": pd.to_datetime(
                ["2025-05-05", "2025-05-06", "2025-05-07", "2025-05-08"]
            ),
            "sanction_amount": amounts,
            "vendor_name": ["Behrapur Infra Contractors"] * 4,
        }
    )


def _national_stats(cfg: dict) -> dict:
    """Saved-style peer stats in which each piece sits below the national median."""
    rng = np.random.default_rng(42)
    amounts = 1_200_000 * np.exp(rng.normal(0, 0.6, 400))
    corpus = pd.DataFrame(
        {
            "work_type": ["Road / Pavement"] * 400,
            "state": ["Bihar"] * 400,
            "peer_group": ["Road / Pavement | Bihar"] * 400,
            "sanction_amount": amounts,
        }
    )
    return fit_split_peer_stats(corpus, cfg)


def test_small_upload_split_is_found_with_saved_peer_stats(cfg: dict) -> None:
    """The four road pieces were called duplicates because the median came from the batch."""
    batch = _split_batch()
    stats = _national_stats(cfg)

    with_saved = find_split_works(batch, cfg, peer_stats=stats)
    assert len(with_saved) == 1
    assert int(with_saved["n_works"].iloc[0]) == 4

    # Computed from the four pieces alone, two of them are above "the median",
    # so no group can form. That is the behaviour this change fixes.
    batch_only = find_split_works(batch.assign(peer_group="Road / Pavement | Bihar"), cfg)
    assert batch_only.empty


def test_split_alert_absorbs_the_duplicate_cluster_inside_it(cfg: dict) -> None:
    scored = pd.DataFrame(
        {
            "work_id": ["A", "B", "C", "D"],
            "band": ["Low"] * 4,
            "risk_score": [10.0] * 4,
            "state": ["Bihar"] * 4,
            "ida": ["X"] * 4,
            "constituency": ["Y"] * 4,
            "work_type": ["Road / Pavement"] * 4,
            "sanction_amount": [1.0] * 4,
            "reasons_en": [[]] * 4,
            "reasons_hi": [[]] * 4,
        }
    )
    duplicates = pd.DataFrame(
        {
            "dup_group_id": ["DUP00001"],
            "n_works": [2],
            "work_ids": ["A,B"],
            "ida": ["X"],
            "constituency": ["Y"],
            "work_type": ["Road / Pavement"],
            "total_amount": [2.0],
        }
    )
    splits = pd.DataFrame(
        {
            "split_group_id": ["SPL00001"],
            "work_ids": ["A,B,C,D"],
            "n_works": [4],
            "ida": ["X"],
            "constituency": ["Y"],
            "work_type": ["Road / Pavement"],
            "total_amount": [3_992_000.0],
            "span_days": [3.0],
            "same_vendor": [True],
        }
    )
    pairs = pd.DataFrame({"work_id_a": ["A"], "work_id_b": ["B"], "pair_score": [0.97]})

    alerts = build_alerts(scored, duplicates, splits, cfg, dup_pairs=pairs)

    assert set(alerts["alert_type"]) == {"split_work_group"}, (
        "duplicate inside a split is not its own alert"
    )
    reasons = alerts["reasons_en"].iloc[0]
    assert reasons[0].startswith("Possible split work"), "the split pattern is named first"
    assert any("97%" in text for text in reasons[1:]), "similarity is kept as supporting evidence"
