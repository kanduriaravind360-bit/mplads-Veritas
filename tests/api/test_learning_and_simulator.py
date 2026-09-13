"""Threshold simulator, counterfactuals, and learning from verdicts."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.orm import Session, sessionmaker

from backend.app import db, models
from backend.app.services import fusion, learning
from ml.config import load_config
from ml.risk import _SIGNALS, apply_severe_floor, band_cutoffs, fuse


def test_rescore_with_configured_weights_matches_the_pipeline() -> None:
    rng = np.random.default_rng(42)
    n = 400
    frame = pd.DataFrame({name: rng.beta(0.4, 2.0, n) for name in _SIGNALS})
    frame["is_open"] = rng.random(n) < 0.5
    frame["severe_rule_count"] = (rng.random(n) < 0.05).astype(int)
    frame["source"] = "training"
    cfg = load_config("ml")

    base = fuse(frame[list(_SIGNALS)], frame["is_open"], cfg)
    cuts = band_cutoffs(base, cfg)
    expected, _ = apply_severe_floor(base, frame, cuts, cfg)

    d = fusion.defaults()
    scores, bands, got_cuts = fusion.rescore(frame, d["weights"], d["band_percentiles"])
    assert np.allclose(scores, expected.to_numpy())
    assert got_cuts == pytest.approx(cuts)
    assert (bands == "Critical").mean() >= 0.01


def test_simulator_is_scoped_and_validated(client, auth) -> None:  # type: ignore[no-untyped-def]
    body = client.post("/api/simulator", json={}, headers=auth("district_lucknow")).json()
    assert body["scope_works"] == 2
    assert sum(b["works"] for b in body["simulated"]["bands"]) == 2

    bad = client.post(
        "/api/simulator",
        json={"band_percentiles": {"high": 0.99, "critical": 0.95}},
        headers=auth("ministry"),
    )
    assert bad.status_code == 422
    assert (
        client.post("/api/simulator", json={"weights": {"cost": 2}}, headers=auth("ministry"))
    ).status_code == 422
    assert client.post("/api/simulator", json={}, headers=auth("mp_147")).status_code == 403


def test_counterfactual_is_scoped(client, auth) -> None:  # type: ignore[no-untyped-def]
    ok = client.get("/api/works/T/MP147/LKO/1/counterfactual", headers=auth("district_lucknow"))
    assert ok.status_code == 200
    body = ok.json()
    assert {"channels", "minimal_set", "queue_cutoff", "note"} <= set(body)
    outside = client.get(
        "/api/works/T/MP900/PAT/1/counterfactual", headers=auth("district_lucknow")
    )
    assert outside.status_code == 404


def test_learning_needs_both_kinds_of_verdict(client, auth) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/api/learning", headers=auth("ministry")).json()
    assert body["status"] in {"insufficient", "ok"}
    assert client.get("/api/learning", headers=auth("mp_147")).status_code == 403


@pytest.fixture()
def labelled() -> Iterator[Session]:
    """An isolated database with planted positives and seeded negatives."""
    engine = db.make_engine("sqlite:///:memory:")
    db.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    rng = np.random.default_rng(7)
    for i in range(120):
        strong = {name: float(rng.uniform(0.0, 0.3)) for name in _SIGNALS}
        strong["cost"] = float(rng.uniform(0.6, 1.0))
        session.add(
            models.PlantedCase(
                planted_id=f"INJ-COST-{i:05d}",
                injection="inflated_cost",
                signals=strong,
                risk_score=90.0,
                band="High",
                partition="learn" if i % 10 < 7 else "evaluate",
            )
        )
    for i in range(80):
        work_id = f"W{i}"
        weak = {name: float(rng.uniform(0.0, 0.3)) for name in _SIGNALS}
        weak["rule"] = float(rng.uniform(0.6, 1.0))
        session.add(
            models.Work(
                work_id=work_id,
                source="training",
                state="S",
                ida="I",
                district="D",
                constituency="C",
                work_type="Road",
                band="High",
                is_open=True,
            )
        )
        session.add(
            models.Alert(
                alert_id=work_id,
                alert_type="high_risk_work",
                severity="High",
                state="S",
                ida="I",
                district="D",
            )
        )
        session.flush()
        session.add(
            models.Feedback(
                alert_id=work_id,
                work_id=work_id,
                verdict="false_positive",
                signals=weak,
                is_seed=True,
                partition="learn" if i % 10 < 7 else "evaluate",
            )
        )
    session.commit()
    yield session
    session.close()


def test_learning_reweights_towards_confirmed_channels(labelled: Session) -> None:
    result = learning.learn(labelled)
    assert result["status"] == "ok"
    by_channel = {c["channel"]: c for c in result["channels"]}
    # Cost was active on the planted positives, rule on the dismissed ones.
    assert by_channel["cost"]["multiplier"] > 1.0 > by_channel["rule"]["multiplier"]
    configured = sum(result["configured_weights"].values())
    assert sum(result["learned_weights"].values()) == pytest.approx(configured, abs=1e-3)
    assert result["reranker"]["trained"] is True
    precision = result["precision"]
    assert precision["reranker"] >= precision["base_rate"]
    # Seeds never mark a real work as confirmed.
    assert result["counts"]["by_origin"]["seed_rule"]["positive"] == 0
