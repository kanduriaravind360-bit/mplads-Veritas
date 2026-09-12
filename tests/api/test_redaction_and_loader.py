"""Presentation-mode redaction, and loader behaviour that protects workflow."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app import redact
from backend.app.loader import stable_group_id
from backend.app.settings import get_settings


@pytest.fixture()
def presentation(monkeypatch):  # type: ignore[no-untyped-def]
    on = replace(get_settings(), presentation_mode=True)
    monkeypatch.setattr(redact, "get_settings", lambda: on)
    return on


def test_redaction_replaces_people_everywhere(presentation) -> None:  # type: ignore[no-untyped-def]
    record = {
        "mp_name": "Shri Invented Person",
        "vendor_name": "Invented Traders Pvt Ltd",
        "constituency": "Shri Invented Person (2022-28) (2022-2028)",
        "work_description": "Road work recommended by Shri Invented Person, executed by Invented Traders Pvt Ltd",
        "state": "Bihar",
        "work_id": "WS/MP147/2025-2026/1",
    }
    out = redact.redact_record(record)
    assert out["mp_name"].startswith("MP-")
    assert out["vendor_name"].startswith("Vendor V-")
    assert "Invented Person" not in out["constituency"]
    assert "Invented Person" not in out["work_description"]
    assert "Invented Traders" not in out["work_description"]
    assert out["state"] == "Bihar" and out["work_id"] == record["work_id"], "places and ids stay"


def test_pseudonyms_are_stable_and_distinct(presentation) -> None:  # type: ignore[no-untyped-def]
    assert redact.pseudonym("mp", "Shri A") == redact.pseudonym("mp", "shri a ")
    assert redact.pseudonym("mp", "Shri A") != redact.pseudonym("mp", "Shri B")


def test_real_constituency_names_are_not_pseudonymised(presentation) -> None:  # type: ignore[no-untyped-def]
    assert redact.redact_record({"constituency": "DHARWAD"})["constituency"] == "DHARWAD"


def test_redaction_is_off_by_default() -> None:
    record = {"mp_name": "Shri Invented Person", "vendor_name": "X Traders"}
    assert redact.redact_record(record) == record


def test_group_ids_are_stable_across_pipeline_runs() -> None:
    """The pipeline renumbers groups each run; the app id must not move with it."""
    first = stable_group_id("SPL", ["B", "A", "C"])
    assert first == stable_group_id("SPL", ["C", "B", "A"])
    assert first != stable_group_id("SPL", ["A", "B"])
    assert first != stable_group_id("DUP", ["A", "B", "C"])


def test_reload_keeps_reviewer_workflow(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A pipeline refresh updates scores but never erases a reviewer's status.

    Runs on its own in-memory database: a reload retires every alert it is not
    given, which would wreck the shared test data.
    """
    from sqlalchemy.orm import sessionmaker

    from backend.app import db, loader, models

    engine = db.make_engine("sqlite:///:memory:")
    db.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        models.Work(
            work_id="W1",
            source="training",
            state="Bihar",
            ida="PATNA(X)",
            district="PATNA",
            constituency="PATNA",
            work_type="Road",
            band="High",
        )
    )
    session.add(
        models.Alert(
            alert_id="W1",
            alert_type="high_risk_work",
            severity="High",
            risk_score=90.0,
            state="Bihar",
            ida="PATNA(X)",
            district="PATNA",
            status="Under Review",
        )
    )
    session.commit()

    row = {
        "alert_id": "W1",
        "alert_type": "high_risk_work",
        "severity": "Critical",
        "risk_score": 55.5,
        "amount": 1.0,
        "n_works": 1,
        "work_type": "Road",
        "reasons_en": ["refreshed"],
        "reasons_hi": ["refreshed"],
        "evidence": {},
        "source": "pipeline",
        "state": "Bihar",
        "ida": "PATNA(X)",
        "district": "PATNA",
        "mp_code": None,
        "constituency": "PATNA",
        "_work_ids": ["W1"],
    }
    monkeypatch.setattr(loader, "_alert_rows", lambda lookup: ([dict(row)], {}))
    new, retired, _ = loader.load_alerts(session, {"W1": {}})
    session.commit()
    session.expire_all()

    refreshed = session.get(models.Alert, "W1")
    assert (new, retired) == (0, 0)
    assert refreshed.risk_score == 55.5 and refreshed.severity == "Critical", "scores refresh"
    assert refreshed.status == "Under Review", "workflow survives a reload"
    session.close()


def test_private_names_in_descriptions_are_masked() -> None:
    from backend.app.redact import mask_private_names

    assert (
        mask_private_names("Sanjay Saroj S/o Ram Chandra Pasi ke Ghar ke samne Handpump")
        == "[name] S/o [name] ke Ghar ke samne Handpump"
    )
    assert mask_private_names(r"VINOD SHARMA S\O SHIV RAM SHARMA K GHAR 01 NAG SOLAR LIGHT") == (
        r"[name] S\O [name] K GHAR 01 NAG SOLAR LIGHT"
    )
    assert (
        mask_private_names("street to house of Shri Manohar. The agency")
        == "street to house of [name] The agency"
    )
    # C/o abbreviates "construction of" here and names no one.
    assert (
        mask_private_names("C/o Common Shed Thaud Dibber GP") == "C/o Common Shed Thaud Dibber GP"
    )
    assert mask_private_names("Construction of CC road at ward 12") == (
        "Construction of CC road at ward 12"
    )


def test_vendor_graph_ids_do_not_carry_names(client, auth) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/api/network/vendors", headers=auth("ministry")).json()
    vendor_ids = [n["id"] for n in body["nodes"] if n["type"] == "vendor"]
    assert vendor_ids and all("Invented" not in i for i in vendor_ids)
    ids = {n["id"] for n in body["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in body["edges"])
