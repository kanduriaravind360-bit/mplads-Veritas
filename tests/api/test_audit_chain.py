"""The audit trail is a hash chain, and verification catches tampering.

Each test builds its own chain in a fresh in-memory database, because the
tamper tests deliberately break the chain and must not poison other tests.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.app import audit, db, models


@pytest.fixture()
def chain() -> Iterator[Session]:
    engine = db.make_engine("sqlite:///:memory:")
    db.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    for i in range(5):
        audit.append(
            session,
            actor=f"user{i}@test",
            action="status_change",
            entity_type="alert",
            entity_id=f"A{i}",
            payload={"to": "Under Review", "n": i},
        )
    session.commit()
    yield session
    session.close()


def test_hashes_link_each_event_to_the_previous_one(chain: Session) -> None:
    rows = chain.query(models.AuditEvent).order_by(models.AuditEvent.seq).all()
    assert rows[0].prev_hash == audit.GENESIS
    for earlier, later in zip(rows, rows[1:], strict=False):
        assert later.prev_hash == earlier.hash
    report = audit.verify(chain)
    assert report.ok and report.events_checked == 5 and report.head_hash == rows[-1].hash


def test_editing_a_past_event_is_detected(chain: Session) -> None:
    chain.execute(
        text('UPDATE audit_events SET payload = \'{"to": "Confirmed", "n": 2}\' WHERE seq = 3')
    )
    chain.commit()
    report = audit.verify(chain)
    assert not report.ok
    assert report.first_broken_seq == 3
    assert "does not match its hash" in (report.reason or "")


def test_changing_the_actor_is_detected(chain: Session) -> None:
    chain.execute(text("UPDATE audit_events SET actor = 'someone.else@test' WHERE seq = 2"))
    chain.commit()
    assert audit.verify(chain).first_broken_seq == 2


def test_deleting_an_event_is_detected(chain: Session) -> None:
    chain.execute(text("DELETE FROM audit_events WHERE seq = 2"))
    chain.commit()
    report = audit.verify(chain)
    assert not report.ok and report.first_broken_seq == 3


def test_rehashing_one_event_still_breaks_the_next(chain: Session) -> None:
    """Fixing up the edited row's own hash is not enough: its successor points at the old one."""
    row = chain.get(models.AuditEvent, 3)
    row.payload = {"to": "Confirmed", "n": 2}
    event = {
        "seq": row.seq,
        "ts": row.ts,
        "actor": row.actor,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "payload": row.payload,
    }
    row.hash = audit.compute_hash(row.prev_hash, event)
    chain.commit()
    report = audit.verify(chain)
    assert not report.ok and report.first_broken_seq == 4


def test_verify_endpoint_reports_the_live_chain(client, auth) -> None:  # type: ignore[no-untyped-def]
    client.post(
        "/api/alerts/T/MP900/PAT/1/comments",
        json={"body": "chain test"},
        headers=auth("state_bihar"),
    )
    body = client.get("/api/audit/verify", headers=auth("ministry")).json()
    assert body["ok"] is True and body["events_checked"] > 0 and len(body["head_hash"]) == 64
    assert client.get("/api/audit/verify", headers=auth("district_lucknow")).status_code == 403
