"""The guaranteed demo path: scenarios found in data, idempotent, loud when missing."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app import audit, db, demo_seed, models
from backend.app.settings import get_settings
from tests.api.conftest import seed


@pytest.fixture()
def demo_db(monkeypatch) -> Iterator[Session]:  # type: ignore[no-untyped-def]
    engine = db.make_engine("sqlite:///:memory:")
    db.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    seed(session)
    api = dict(get_settings().api)
    api["demo"] = {
        "split_case": {"district": "KANPUR", "work_type": "CC / Concrete Road"},
        "false_positive_alerts": ["T/MP147/LKO/1"],
        "high_delay_district": "PATNA",
    }
    settings = replace(get_settings(), api=api)
    monkeypatch.setattr(demo_seed, "get_settings", lambda: settings)
    yield session
    session.close()


def test_demo_seed_opens_the_split_case_once(demo_db: Session) -> None:
    first = demo_seed.run(demo_db)
    demo_db.commit()
    second = demo_seed.run(demo_db)
    demo_db.commit()
    assert first["split_case"]["created"] is True and second["split_case"]["created"] is False
    cases = demo_db.execute(select(models.Case)).scalars().all()
    assert len(cases) == 1 and cases[0].ida.startswith("KANPUR")
    assert "times the 90th-percentile cost" in (cases[0].summary or "")
    assert first["high_delay_district"]["open_works"] == 3


def test_reset_returns_the_live_demo_alert_to_open_on_the_audit_trail(demo_db: Session) -> None:
    alert = demo_db.get(models.Alert, "T/MP147/LKO/1")
    alert.status = "False positive"
    demo_db.commit()
    result = demo_seed.run(demo_db, reset=True)
    demo_db.commit()
    walk = result["false_positive_walkthrough"][0]
    assert walk["status"] == "Open" and walk["was"] == "False positive"
    events = audit.trail_for(demo_db, "alert", "T/MP147/LKO/1")
    assert any(e["action"] == "demo_reset" for e in events)
    assert audit.verify(demo_db).ok


def test_missing_scenario_fails_loudly(demo_db: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = demo_seed.get_settings()
    api = dict(settings.api)
    api["demo"] = {**api["demo"], "high_delay_district": "NOWHERE"}
    monkeypatch.setattr(demo_seed, "get_settings", lambda: replace(settings, api=api))
    with pytest.raises(demo_seed.DemoDataMissingError):
        demo_seed.run(demo_db)
