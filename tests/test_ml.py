"""Contract tests for the ML pipeline.

The leakage test is the important one: it is the automated enforcement of
CLAUDE.md rule 3, and it should fail loudly if anyone ever adds a flag column
to the feature list.

Most tests run on a deterministic sample with embeddings switched off, so the
suite stays fast and does not need the sentence-transformer model or a network.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from ml.config import load_config
from ml.data import LEAKY_COLUMNS, load_processed
from ml.detect_duplicates import find_duplicates
from ml.features import assert_leak_safe, build_features
from ml.pipeline import run
from ml.risk import band_for, fuse
from ml.work_type import assign_work_type

SAMPLE_ROWS = 5_000


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config("ml")


@pytest.fixture(scope="module")
def works() -> pd.DataFrame:
    return load_processed()


@pytest.fixture(scope="module")
def sample(works: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """A deterministic slice, big enough for peer groups to mean something."""
    return works.sample(n=SAMPLE_ROWS, random_state=int(cfg["seed"])).reset_index(drop=True)


@pytest.fixture(scope="module")
def scored(sample: pd.DataFrame, cfg: dict):
    return run(cfg, df=sample, use_embeddings=False, train_models=True, save=False)


# --- leakage ---------------------------------------------------------------


def test_feature_list_has_no_leaky_columns(scored) -> None:
    """CLAUDE.md rule 3: flag_*, anomaly_score and flag_reasons are never inputs."""
    names = scored.feature_names
    assert names, "pipeline produced no features"
    for banned in (*LEAKY_COLUMNS, "anomaly_label"):
        assert banned not in names
    assert not [n for n in names if n.startswith("flag_")]


def test_assert_leak_safe_rejects_a_flag_column() -> None:
    """The guard must actually fire, not just pass on clean input."""
    with pytest.raises(ValueError, match="LEAKAGE"):
        assert_leak_safe(["log_amount", "flag_cost_outlier"])

    with pytest.raises(ValueError, match="LEAKAGE"):
        assert_leak_safe(["log_amount", "anomaly_score"])


def test_saved_feature_list_is_clean(sample: pd.DataFrame, cfg: dict, tmp_path) -> None:
    """The on-disk feature list the backend reads must also be leak-free."""
    sample = sample.copy()
    sample["work_type"] = assign_work_type(sample, cfg, use_embeddings=False)
    _, names = build_features(sample, cfg)

    payload = {"features": sorted(names)}
    path = tmp_path / "feature_list.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = json.loads(path.read_text(encoding="utf-8"))["features"]
    assert not [n for n in loaded if n.startswith("flag_") or n in LEAKY_COLUMNS]


# --- risk score ------------------------------------------------------------


def test_risk_score_in_range_and_not_null(scored) -> None:
    risk = scored.scored["risk_score"]
    assert risk.notna().all(), "risk_score contains NaN"
    assert float(risk.min()) >= 0.0
    assert float(risk.max()) <= 100.0


def test_every_work_gets_a_band(scored) -> None:
    bands = scored.scored["band"]
    assert bands.notna().all()
    assert set(bands.unique()) <= {"Low", "Medium", "High", "Critical"}


def test_band_thresholds_match_config(cfg: dict) -> None:
    bands = cfg["risk"]["bands"]
    assert band_for(bands["medium"] - 0.01, cfg) == "Low"
    assert band_for(bands["medium"], cfg) == "Medium"
    assert band_for(bands["high"], cfg) == "High"
    assert band_for(bands["critical"], cfg) == "Critical"


def _signals(**values: float) -> pd.DataFrame:
    """One-row signal frame; unnamed signals default to zero."""
    from ml.risk import _SIGNALS

    return pd.DataFrame({name: [float(values.get(name, 0.0))] for name in _SIGNALS})


def _flat(value: float, delay: float = 0.0) -> pd.DataFrame:
    from ml.risk import _SIGNALS

    return pd.DataFrame({name: [delay if name == "delay" else value] for name in _SIGNALS})


def test_a_single_strong_signal_reaches_a_high_band(cfg: dict) -> None:
    """One detector at full confidence must be able to carry a work on its own.

    This is the property a linear blend could not provide: a work caught by
    exactly one detector was capped at that detector's weight, i.e. 25 of 100,
    so nothing reached High unless several detectors fired together. The target
    is the configured single_signal_target, which sits in the High band and
    leaves Critical to cases where detectors agree.
    """
    out = fuse(_signals(unsupervised=1.0), pd.Series([False]), cfg)
    weights = cfg["risk"]["weights"]
    target = float(cfg["risk"]["single_signal_target"])
    # The target applies to the highest-weighted signal; a lesser one scores
    # proportionally less.
    expected = 100.0 * (
        1.0 - (1.0 - target) ** (float(weights["unsupervised"]) / max(weights.values()))
    )
    assert out.iloc[0] == pytest.approx(expected, abs=2.0)
    assert out.iloc[0] > 0.0


def test_agreeing_detectors_escalate(cfg: dict) -> None:
    """Two independent detectors at the same strength must outrank one."""
    one = _signals(unsupervised=0.6)
    two = _signals(unsupervised=0.6, duplicate=0.6)
    closed = pd.Series([False])
    assert fuse(two, closed, cfg).iloc[0] > fuse(one, closed, cfg).iloc[0]


def test_fusion_is_monotone_in_every_signal(cfg: dict) -> None:
    """Raising any signal can never lower the risk score."""
    closed = pd.Series([False])
    scores = [fuse(_flat(v), closed, cfg).iloc[0] for v in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert scores == sorted(scores)


def test_delay_is_ignored_for_closed_works(cfg: dict) -> None:
    """A finished work must not be scored on a delay risk it cannot have."""
    from ml.risk import _SIGNALS

    signals = pd.DataFrame(
        {name: [0.9, 0.9] if name == "delay" else [0.0, 0.0] for name in _SIGNALS}
    )
    out = fuse(signals, pd.Series([True, False]), cfg)
    assert out.iloc[0] > 0.0, "an open work should carry its delay risk"
    assert out.iloc[1] == pytest.approx(0.0), "a closed work should not"


# --- work type -------------------------------------------------------------


def test_every_work_gets_a_work_type(scored) -> None:
    types = scored.scored["work_type"]
    assert types.notna().all()
    assert (types.astype(str).str.len() > 0).all()


def test_work_type_rules_beat_the_category_column(sample: pd.DataFrame, cfg: dict) -> None:
    """The derived type must be more informative than work_category.

    work_category is 97.7% "Normal/Others", which is why we derive a type at all.
    """
    sample = sample.copy()
    sample["work_type"] = assign_work_type(sample, cfg, use_embeddings=False)
    assert sample["work_type"].nunique() > sample["work_category"].nunique()
    assert sample["work_type"].value_counts(normalize=True).iloc[0] < 0.5


# --- reasons ---------------------------------------------------------------


def test_every_work_has_at_least_one_reason(scored) -> None:
    """A score with no evidence is not shown to a reviewer (CLAUDE.md rule 4)."""
    for column in ("reasons_en", "reasons_hi"):
        lengths = scored.scored[column].apply(len)
        assert lengths.min() >= 1, f"{column} has rows with no reason"


def test_english_and_hindi_reasons_are_paired(scored) -> None:
    en = scored.scored["reasons_en"].apply(len)
    hi = scored.scored["reasons_hi"].apply(len)
    assert (en == hi).all()


# --- duplicates ------------------------------------------------------------


def test_injected_duplicate_is_detected(sample: pd.DataFrame, cfg: dict) -> None:
    """A near-copy of a real work in the same constituency must be caught."""
    source = sample.loc[sample["work_description"].str.split().str.len() >= 8].iloc[0]

    clone = source.copy()
    clone["work_id"] = "INJ-DUP-TEST-0001"
    # Reword lightly, as a genuine re-entry would: same work, different typing.
    clone["work_description"] = str(source["work_description"]).replace("Construction", "Constrn")
    clone["sanction_date"] = source["sanction_date"] + pd.Timedelta(days=10)

    clone_frame = clone.to_frame().T.astype(sample.dtypes.to_dict())
    data = pd.concat([sample, clone_frame], ignore_index=True)
    data["work_type"] = assign_work_type(data, cfg, use_embeddings=False)

    # Identical embeddings for identical text; the clone gets the source's vector
    # so this test needs no model download.
    rng = np.random.default_rng(int(cfg["seed"]))
    vectors = rng.normal(size=(len(data), 16)).astype("float32")
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    source_pos = int(data.index[data["work_id"] == source["work_id"]][0])
    clone_pos = int(data.index[data["work_id"] == clone["work_id"]][0])
    vectors[clone_pos] = vectors[source_pos]

    result = find_duplicates(data, vectors, cfg)
    flagged = set(result.pairs["work_id_a"]) | set(result.pairs["work_id_b"])
    assert clone["work_id"] in flagged
    assert source["work_id"] in flagged


# --- reproducibility -------------------------------------------------------


def test_pipeline_is_reproducible_with_seed_42(sample: pd.DataFrame, cfg: dict) -> None:
    """Two runs over the same 5k rows must agree exactly (CLAUDE.md rule 5)."""
    first = run(cfg, df=sample, use_embeddings=False, train_models=True, save=False)
    second = run(cfg, df=sample, use_embeddings=False, train_models=True, save=False)

    pd.testing.assert_series_equal(
        first.scored["risk_score"], second.scored["risk_score"], check_names=False
    )
    pd.testing.assert_series_equal(first.scored["band"], second.scored["band"], check_names=False)
    assert first.scored["work_type"].tolist() == second.scored["work_type"].tolist()


# --- roll-ups --------------------------------------------------------------


def test_rollups_carry_their_denominator(scored, cfg: dict) -> None:
    """Every roll-up must show how many works it is based on."""
    for name, frame in scored.rollups.items():
        assert "works" in frame.columns, f"{name} roll-up has no denominator"
        assert "low_volume" in frame.columns
        assert (frame["works"] > 0).all()


def test_mp_rollup_is_framed_as_implementation_risk(scored) -> None:
    """CLAUDE.md rule 4: MP views describe implementation, not the MP."""
    mp = scored.rollups["mp"]
    assert "implementation_risk_index" in mp.columns
    assert "risk_index" not in mp.columns
    assert "implementation risk" in mp["measure"].iloc[0]


def test_low_volume_groups_never_top_a_ranking(scored, cfg: dict) -> None:
    """A 4-work constituency must not outrank a well-evidenced one."""
    min_works = int(cfg["risk"]["rollup_min_works"])
    for frame in scored.rollups.values():
        if (frame["works"] >= min_works).any():
            assert not bool(frame["low_volume"].iloc[0])


# --- recomputed rule layer -------------------------------------------------


def test_recomputed_rules_agree_with_shipped_flags(sample: pd.DataFrame, cfg: dict) -> None:
    """Our rules must reproduce the dataset's own flags closely.

    They are deliberately a slight superset (the robust cost z-score catches
    peer-relative overpricing the shipped mean/std score misses), so this asserts
    high agreement rather than exact equality.
    """
    from ml.rules import agreement_with_shipped, compute_rules

    data = sample.copy()
    data["work_type"] = assign_work_type(data, cfg, use_embeddings=False)
    rules = compute_rules(data, cfg)
    report = agreement_with_shipped(data, rules, cfg)

    # Most rules are deliberately a superset of the shipped flag and must not
    # miss any case it caught. rule_payment_stuck is the exception: it is
    # STRICTER, requiring the payment to be both in progress and stale, so it
    # legitimately catches fewer.
    stricter_than_shipped = {"rule_payment_stuck"}

    for name, stats in report.items():
        if name == "label":
            continue
        assert stats["agreement"] >= 0.90, f"{name} agreement {stats['agreement']}"
        if name not in stricter_than_shipped:
            assert stats["both_true"] == stats["shipped_true"], f"{name} misses shipped cases"


def test_rules_respond_to_changed_data(sample: pd.DataFrame, cfg: dict) -> None:
    """The point of recomputing: a changed cost must change the rule outcome.

    The shipped flag_* columns cannot do this, which is why they are not used as
    the fusion signal.
    """
    from ml.rules import compute_rules

    data = sample.copy()
    data["work_type"] = assign_work_type(data, cfg, use_embeddings=False)
    before = compute_rules(data, cfg)

    # Inflate a SUBSET so those rows become outliers against their peers.
    # Scaling every amount would move the peer median with it, and a relative
    # measure is supposed to ignore that.
    inflated = data.copy()
    victims = inflated.index[:200]
    inflated.loc[victims, "sanction_amount"] = inflated.loc[victims, "sanction_amount"] * 50.0
    after = compute_rules(inflated, cfg)

    # The shipped flags cannot see the change; ours must.
    assert inflated["flag_cost_outlier"].sum() == data["flag_cost_outlier"].sum()
    assert after["rule_cost_outlier"].sum() > before["rule_cost_outlier"].sum()
    newly_flagged = after.loc[victims, "rule_cost_outlier"].sum()
    assert newly_flagged > before.loc[victims, "rule_cost_outlier"].sum()


def test_rule_signal_is_not_a_model_feature(scored) -> None:
    """CLAUDE.md rule 3 again: the rule columns must stay out of the features."""
    for name in scored.feature_names:
        assert not name.startswith("rule_")
        assert name not in {"rule_score", "rule_label", "rule_reasons"}


# --- step 2b detectors -----------------------------------------------------


def test_every_fusion_signal_has_a_weight(cfg: dict) -> None:
    """A signal with no weight would be silently ignored by the fusion."""
    from ml.risk import _SIGNALS

    weights = cfg["risk"]["weights"]
    assert set(_SIGNALS) <= set(weights), f"unweighted signals: {set(_SIGNALS) - set(weights)}"


def test_quantity_extraction_finds_known_units() -> None:
    """The regexes must read the quantities they claim to."""
    from ml.quantity import extract

    cases = pd.Series(
        [
            "Construction of CC road 250 mtr in village Rampur",
            "Installation of 2 km approach road",
            "Supply of 150 W LED street light",
            "Providing 5000 ltr water tank",
            "Purchase of 12 nos desks",
            "Construction of community hall",
        ]
    )
    out = extract(cases)
    assert out["quantity"].tolist()[:5] == [250.0, 2000.0, 150.0, 5000.0, 12.0]
    assert out["quantity_unit"].tolist()[:5] == [
        "length_m",
        "length_m",
        "power_w",
        "volume_l",
        "count",
    ]
    assert pd.isna(out["quantity"].iloc[5]), "a description with no quantity must yield NaN"


def test_expected_cost_flags_an_inflated_work(sample: pd.DataFrame, cfg: dict) -> None:
    """Multiplying a work's cost must raise its expected-cost residual."""
    from ml.expected_cost import fit_predict
    from ml.quantity import add_unit_rates, extract

    data = sample.copy()
    data["work_type"] = assign_work_type(data, cfg, use_embeddings=False)
    quantities = add_unit_rates(data, extract(data["work_description"]), cfg)

    inflated = data.copy()
    victims = inflated.index[:100]
    inflated.loc[victims, "sanction_amount"] = inflated.loc[victims, "sanction_amount"] * 4.0
    inflated_q = add_unit_rates(inflated, extract(inflated["work_description"]), cfg)

    base = fit_predict(data, quantities, None, cfg)
    after = fit_predict(inflated, inflated_q, None, cfg)

    assert after.residual.loc[victims].mean() > base.residual.loc[victims].mean() + 0.5
    assert after.cost_signal.loc[victims].mean() > base.cost_signal.loc[victims].mean()


def test_band_cutoffs_follow_configured_percentiles(scored, cfg: dict) -> None:
    """Percentile banding must produce the configured share of each band."""
    from ml.risk import band_cutoffs

    if str(cfg["risk"].get("band_method")) != "percentile":
        pytest.skip("bands are configured as absolute thresholds")

    frame = scored.scored
    cuts = band_cutoffs(frame["risk_score"], cfg)
    assert cuts["critical"] >= cuts["high"] >= cuts["medium"]

    pcts = cfg["risk"]["band_percentiles"]
    share = (frame["band"] == "Critical").mean()
    assert share == pytest.approx(1.0 - float(pcts["critical"]), abs=0.02)
