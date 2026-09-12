"""Alert workflow: status transitions, assignment, comments, feedback, escalation.

Every state change goes through here, and every one writes an audit event in
the same transaction. There is no path that changes an alert without leaving a
hash-chained record of who did it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import audit, models
from backend.app.scoping import MINISTRY, STATE, Scope, not_found
from backend.app.settings import get_settings


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def get_scoped_alert(db: Session, scope: Scope, alert_id: str) -> models.Alert:
    stmt = scope.apply(select(models.Alert).where(models.Alert.alert_id == alert_id), models.Alert)
    alert = db.execute(stmt).scalar_one_or_none()
    if alert is None:
        raise not_found("alert")
    return alert


def allowed_transitions(alert: models.Alert, role: str) -> list[str]:
    cfg = get_settings().api["alerts"]
    targets = list(cfg["transitions"].get(alert.status, []))
    closed = set(cfg["closed_statuses"])
    if alert.status in closed and role not in set(cfg["reopen_roles"]):
        # Reopening a closed alert is a supervisory act.
        targets = [t for t in targets if t in closed]
    return targets


def transition(
    db: Session, user: models.User, alert: models.Alert, to_status: str, note: str | None
) -> models.Alert:
    cfg = get_settings().api["alerts"]
    if to_status not in cfg["statuses"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown status '{to_status}'")
    if to_status not in allowed_transitions(alert, user.role):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"cannot move an alert from '{alert.status}' to '{to_status}' as {user.role}",
        )
    previous = alert.status
    alert.status = to_status
    alert.updated_at = _now()
    audit.append(
        db,
        actor=user.email,
        action="status_change",
        entity_type="alert",
        entity_id=alert.alert_id,
        payload={"from": previous, "to": to_status, "note": note or ""},
    )
    return alert


def assign(
    db: Session, user: models.User, scope: Scope, alert: models.Alert, email: str | None
) -> models.Alert:
    assignee: models.User | None = None
    if email:
        assignee = db.execute(
            select(models.User).where(models.User.email == email)
        ).scalar_one_or_none()
        if assignee is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "assignee not found")
        if assignee.role not in set(get_settings().api["alerts"]["reviewer_roles"]):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "assignee cannot review alerts"
            )
        # You cannot hand an alert to someone who is not allowed to see it.
        if not Scope.for_user(assignee).allows_row(alert):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "assignee's scope does not cover this alert"
            )
    previous = alert.assignee.email if alert.assignee else None
    alert.assignee_id = assignee.id if assignee else None
    alert.updated_at = _now()
    audit.append(
        db,
        actor=user.email,
        action="assign",
        entity_type="alert",
        entity_id=alert.alert_id,
        payload={"from": previous, "to": assignee.email if assignee else None},
    )
    return alert


def comment(db: Session, user: models.User, alert: models.Alert, body: str) -> models.Comment:
    row = models.Comment(alert_id=alert.alert_id, author_id=user.id, body=body)
    db.add(row)
    alert.updated_at = _now()
    audit.append(
        db,
        actor=user.email,
        action="comment",
        entity_type="alert",
        entity_id=alert.alert_id,
        payload={"body": body},
    )
    return row


def feedback(
    db: Session,
    user: models.User,
    alert: models.Alert,
    verdict: str,
    note: str | None,
    work_id: str | None,
) -> models.Feedback:
    cfg = get_settings().api["alerts"]
    if verdict not in cfg["verdicts"]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"verdict must be one of {cfg['verdicts']}"
        )
    member_ids = {link.work_id for link in alert.works}
    if work_id and work_id not in member_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "work is not part of this alert")
    target = work_id or (next(iter(member_ids)) if len(member_ids) == 1 else None)

    signals: dict[str, float] = {}
    if target:
        work = db.get(models.Work, target)
        if work is not None:
            signals = {
                "rule": work.sig_rule,
                "supervised": work.sig_supervised,
                "unsupervised": work.sig_unsupervised,
                "cost": work.sig_cost,
                "duplicate": work.sig_duplicate,
                "delay": work.sig_delay,
                "risk_score": work.risk_score,
            }
    row = models.Feedback(
        alert_id=alert.alert_id,
        work_id=target,
        reviewer_id=user.id,
        verdict=verdict,
        note=note,
        signals=signals,
    )
    db.add(row)
    audit.append(
        db,
        actor=user.email,
        action="feedback",
        entity_type="alert",
        entity_id=alert.alert_id,
        payload={"verdict": verdict, "work_id": target, "note": note or ""},
    )
    return row


def escalate_due(db: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    """Move Open alerts up a level once they have waited too long at their level.

    Days are counted from the later of when the alert was raised and when it was
    last escalated, so an alert gets the full window at each level.
    """
    cfg = get_settings().api["escalation"]
    now = now or _now()
    windows = {
        "district": ("state", timedelta(days=int(cfg["district_to_state_days"]))),
        "state": ("ministry", timedelta(days=int(cfg["state_to_ministry_days"]))),
    }
    moved: list[dict[str, Any]] = []
    for level, (next_level, window) in windows.items():
        candidates = db.execute(
            select(models.Alert).where(
                models.Alert.level == level,
                models.Alert.status == "Open",
                models.Alert.is_active.is_(True),
            )
        ).scalars()
        for alert in candidates:
            since = alert.escalated_at or alert.raised_at
            if since is None or now - since < window:
                continue
            alert.level = next_level
            alert.escalated_at = now
            alert.updated_at = now
            waited = (now - since).days
            audit.append(
                db,
                actor="system:escalation",
                action="escalate",
                entity_type="alert",
                entity_id=alert.alert_id,
                payload={"from_level": level, "to_level": next_level, "days_unreviewed": waited},
            )
            moved.append(
                {"alert_id": alert.alert_id, "from": level, "to": next_level, "days": waited}
            )
    return moved


def level_visible_to(role: str) -> set[str] | None:
    """Which escalation levels a role works on; None means all."""
    if role == MINISTRY:
        return None
    if role == STATE:
        return {"district", "state"}
    return {"district"}
