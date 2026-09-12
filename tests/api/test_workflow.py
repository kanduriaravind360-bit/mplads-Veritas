"""Alert lifecycle, assignment, comments, feedback, escalation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app import models
from backend.app.services.alerts import escalate_due


def test_lifecycle_happy_path_and_audit_order(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("district_kanpur")
    alert = "T/MP147/KNP/1"
    assert client.get(f"/api/alerts/{alert}", headers=headers).json()["allowed_transitions"] == [
        "Under Review"
    ]

    moved = client.post(
        f"/api/alerts/{alert}/transition",
        json={"to_status": "Under Review", "note": "looking"},
        headers=headers,
    )
    assert moved.status_code == 200 and moved.json()["status"] == "Under Review"
    confirmed = client.post(
        f"/api/alerts/{alert}/transition", json={"to_status": "Confirmed"}, headers=headers
    )
    assert confirmed.json()["status"] == "Confirmed"

    trail = client.get(f"/api/alerts/{alert}/audit", headers=headers).json()
    changes = [
        (e["payload"]["from"], e["payload"]["to"]) for e in trail if e["action"] == "status_change"
    ]
    assert changes == [("Open", "Under Review"), ("Under Review", "Confirmed")]
    assert all(
        e["actor"] == "district.kanpur@test" for e in trail if e["action"] == "status_change"
    )


def test_invalid_transition_is_rejected(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("state_bihar")
    # DUP-PATNA001 is never moved by any other test, so it is still Open here.
    response = client.post(
        "/api/alerts/DUP-PATNA001/transition", json={"to_status": "Confirmed"}, headers=headers
    )
    assert response.status_code == 409
    unknown = client.post(
        "/api/alerts/DUP-PATNA001/transition", json={"to_status": "Deleted"}, headers=headers
    )
    assert unknown.status_code == 422


def test_only_supervisors_reopen_a_closed_alert(client, auth) -> None:  # type: ignore[no-untyped-def]
    alert = "T/MP147/LKO/1"
    district = auth("district_lucknow")
    client.post(
        f"/api/alerts/{alert}/transition", json={"to_status": "Under Review"}, headers=district
    )
    client.post(
        f"/api/alerts/{alert}/transition", json={"to_status": "False positive"}, headers=district
    )
    assert (
        client.post(
            f"/api/alerts/{alert}/transition", json={"to_status": "Under Review"}, headers=district
        ).status_code
        == 409
    )
    reopened = client.post(
        f"/api/alerts/{alert}/transition",
        json={"to_status": "Under Review"},
        headers=auth("state_up"),
    )
    assert reopened.status_code == 200 and reopened.json()["status"] == "Under Review"


def test_cannot_assign_to_someone_outside_the_alerts_scope(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("state_up")
    bad = client.post(
        "/api/alerts/T/MP147/KNP/1/assign",
        json={"assignee_email": "district.lucknow@test"},
        headers=headers,
    )
    assert bad.status_code == 422
    good = client.post(
        "/api/alerts/T/MP147/KNP/1/assign",
        json={"assignee_email": "district.kanpur@test"},
        headers=headers,
    )
    assert good.status_code == 200 and good.json()["assignee"] == "district.kanpur@test"
    mp = client.post(
        "/api/alerts/T/MP147/KNP/1/assign", json={"assignee_email": "mp.147@test"}, headers=headers
    )
    assert mp.status_code == 422, "an MP cannot be made a reviewer"


def test_comments_and_feedback_are_recorded(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("state_bihar")
    alert = "DUP-PATNA001"
    assert (
        client.post(
            f"/api/alerts/{alert}/comments",
            json={"body": "checking with the agency"},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/alerts/{alert}/feedback", json={"verdict": "maybe"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/alerts/{alert}/feedback",
            json={"verdict": "not_duplicate", "work_id": "T/MP147/LKO/1"},
            headers=headers,
        ).status_code
        == 422
    )
    ok = client.post(
        f"/api/alerts/{alert}/feedback",
        json={"verdict": "not_duplicate", "work_id": "T/MP900/PAT/2"},
        headers=headers,
    )
    assert ok.status_code == 200
    detail = client.get(f"/api/alerts/{alert}", headers=headers).json()
    assert detail["comments"][-1]["body"] == "checking with the agency"
    assert detail["feedback"][-1]["verdict"] == "not_duplicate"
    assert {e["action"] for e in detail["audit"]} >= {"comment", "feedback"}


def test_escalation_moves_unreviewed_alerts_up_a_level(session) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC).replace(tzinfo=None)
    session.add_all(
        [
            models.Alert(
                alert_id="ESC-OLD",
                alert_type="high_risk_work",
                severity="High",
                state="Bihar",
                ida="PATNA(X)",
                district="PATNA",
                raised_at=now - timedelta(days=16),
                updated_at=now,
            ),
            models.Alert(
                alert_id="ESC-NEW",
                alert_type="high_risk_work",
                severity="High",
                state="Bihar",
                ida="PATNA(X)",
                district="PATNA",
                raised_at=now - timedelta(days=3),
                updated_at=now,
            ),
            models.Alert(
                alert_id="ESC-REVIEWED",
                alert_type="high_risk_work",
                severity="High",
                state="Bihar",
                ida="PATNA(X)",
                district="PATNA",
                status="Under Review",
                raised_at=now - timedelta(days=40),
                updated_at=now,
            ),
            models.Alert(
                alert_id="ESC-STATE",
                alert_type="high_risk_work",
                severity="High",
                state="Bihar",
                ida="PATNA(X)",
                district="PATNA",
                level="state",
                raised_at=now - timedelta(days=60),
                escalated_at=now - timedelta(days=31),
                updated_at=now,
            ),
        ]
    )
    session.commit()

    moved = {m["alert_id"]: m for m in escalate_due(session, now=now)}
    session.commit()

    assert moved["ESC-OLD"]["to"] == "state"
    assert moved["ESC-STATE"]["to"] == "ministry"
    assert "ESC-NEW" not in moved, "3 days is inside the 15-day district window"
    assert "ESC-REVIEWED" not in moved, "someone is already working on it"
    assert session.get(models.Alert, "ESC-OLD").level == "state"

    # A second run on the same clock does nothing: the state window restarts.
    assert "ESC-OLD" not in {m["alert_id"] for m in escalate_due(session, now=now)}
    events = session.query(models.AuditEvent).filter(models.AuditEvent.action == "escalate").all()
    assert {e.entity_id for e in events} >= {"ESC-OLD", "ESC-STATE"}
