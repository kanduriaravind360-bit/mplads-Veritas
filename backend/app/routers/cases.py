"""Investigation cases: group related alerts, own them, annotate them, brief on them."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from backend.app import audit, models
from backend.app.deps import Context, reviewer
from backend.app.redact import redact_record
from backend.app.schemas import CaseCreate, CaseUpdate, NoteRequest
from backend.app.scoping import MINISTRY, not_found
from backend.app.serialize import alert_summary
from backend.app.services import alerts as alert_svc

router = APIRouter(prefix="/cases", tags=["cases"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _scoped_case(ctx: Context, case_id: int) -> models.Case:
    stmt = ctx.scope.apply(
        select(models.Case)
        .options(selectinload(models.Case.alerts), selectinload(models.Case.notes))
        .where(models.Case.id == case_id),
        models.Case,
    )
    case = ctx.db.execute(stmt).scalar_one_or_none()
    if case is None:
        raise not_found("case")
    return case


def _case_scope(ctx: Context, alerts: list[models.Alert]) -> dict[str, str | None]:
    """A case lives where its alerts live, so the right reviewers can see it.

    If every alert shares one district the case is a district case; one state, a
    state case; otherwise it takes the creator's own scope.
    """
    idas = {a.ida for a in alerts}
    states = {a.state for a in alerts}
    if alerts and len(idas) == 1:
        return {"state": next(iter(states)), "ida": next(iter(idas)), "mp_code": None}
    if alerts and len(states) == 1:
        return {"state": next(iter(states)), "ida": None, "mp_code": None}
    return {"state": ctx.scope.state, "ida": ctx.scope.ida, "mp_code": ctx.scope.mp_code}


def _summary(case: models.Case, db: Any) -> dict[str, Any]:
    alert_ids = [link.alert_id for link in case.alerts]
    value = 0.0
    if alert_ids:
        value = float(
            db.execute(
                select(func.coalesce(func.sum(models.Alert.amount), 0.0)).where(
                    models.Alert.alert_id.in_(alert_ids)
                )
            ).scalar_one()
        )
    return redact_record(
        {
            "id": case.id,
            "title": case.title,
            "kind": case.kind,
            "status": case.status,
            "owner": case.owner.email,
            "state": case.state,
            "ida": case.ida,
            "summary": case.summary,
            "alerts": len(alert_ids),
            "value": value,
            "created_at": case.created_at.isoformat(),
            "updated_at": case.updated_at.isoformat(),
        }
    )


@router.get("")
def list_cases(ctx: Context = Depends(reviewer)) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        ctx.scope.apply(
            select(models.Case).options(
                selectinload(models.Case.alerts), selectinload(models.Case.owner)
            ),
            models.Case,
        ).order_by(models.Case.updated_at.desc())
    ).scalars()
    return [_summary(c, ctx.db) for c in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_case(body: CaseCreate, ctx: Context = Depends(reviewer)) -> dict[str, Any]:
    alerts = [
        alert_svc.get_scoped_alert(ctx.db, ctx.scope, a) for a in dict.fromkeys(body.alert_ids)
    ]
    scope = _case_scope(ctx, alerts)
    if ctx.user.role != MINISTRY and not ctx.scope.allows_values(
        scope["state"], scope["ida"], scope["mp_code"]
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "case would fall outside your scope")
    case = models.Case(
        title=body.title, kind=body.kind, owner_id=ctx.user.id, summary=body.summary, **scope
    )
    ctx.db.add(case)
    ctx.db.flush()
    for alert in alerts:
        ctx.db.add(models.CaseAlert(case_id=case.id, alert_id=alert.alert_id))
    audit.append(
        ctx.db,
        actor=ctx.user.email,
        action="case_create",
        entity_type="case",
        entity_id=str(case.id),
        payload={"title": body.title, "kind": body.kind, "alert_ids": [a.alert_id for a in alerts]},
    )
    ctx.db.commit()
    ctx.db.refresh(case)
    return _summary(case, ctx.db)


@router.get("/suggestions")
def suggestions(ctx: Context = Depends(reviewer)) -> dict[str, Any]:
    """Ready-made groupings a reviewer can turn into a case in one click."""
    in_cases = select(models.CaseAlert.alert_id)
    splits = ctx.db.execute(
        ctx.scope.apply(select(models.Alert), models.Alert)
        .where(
            models.Alert.alert_type == "split_work_group",
            models.Alert.is_active.is_(True),
            models.Alert.alert_id.not_in(in_cases),
        )
        .order_by(models.Alert.amount.desc())
        .limit(8)
    ).scalars()
    district_rows = ctx.db.execute(
        ctx.scope.apply(
            select(
                models.Alert.district,
                models.Alert.state,
                func.count(),
                func.sum(models.Alert.amount),
            ),
            models.Alert,
        )
        .where(models.Alert.is_active.is_(True), models.Alert.severity.in_(["High", "Critical"]))
        .group_by(models.Alert.district, models.Alert.state)
        .order_by(func.count().desc())
        .limit(8)
    ).all()
    return {
        "split_groups": [
            {
                "title": f"Possible split work: {a.work_type} in {a.district}",
                "kind": "split_group",
                "alert_ids": [a.alert_id],
                "value": a.amount,
                "n_works": a.n_works,
            }
            for a in splits
        ],
        "district_patterns": [
            {
                "title": f"High-risk pattern in {d}",
                "kind": "district_pattern",
                "district": d,
                "state": s,
                "alerts": int(n),
                "value": float(v or 0.0),
            }
            for d, s, n, v in district_rows
        ],
    }


@router.get("/{case_id}")
def get_case(case_id: int, ctx: Context = Depends(reviewer)) -> dict[str, Any]:
    case = _scoped_case(ctx, case_id)
    out = _summary(case, ctx.db)
    alert_ids = [link.alert_id for link in case.alerts]
    alerts = (
        ctx.db.execute(
            ctx.scope.apply(
                select(models.Alert)
                .options(selectinload(models.Alert.assignee))
                .where(models.Alert.alert_id.in_(alert_ids)),
                models.Alert,
            )
        )
        .scalars()
        .all()
    )
    work_ids = sorted({link.work_id for a in alerts for link in a.works})
    out["linked_alerts"] = [alert_summary(a) for a in alerts]
    out["work_ids"] = work_ids
    out["notes"] = [
        {
            "id": n.id,
            "author": n.author.email,
            "body": n.body,
            "created_at": n.created_at.isoformat(),
        }
        for n in case.notes
    ]
    out["audit"] = audit.trail_for(ctx.db, "case", str(case.id))
    return out


@router.patch("/{case_id}")
def update_case(case_id: int, body: CaseUpdate, ctx: Context = Depends(reviewer)) -> dict[str, Any]:
    case = _scoped_case(ctx, case_id)
    changes: dict[str, Any] = {}
    if body.status and body.status != case.status:
        changes["status"] = {"from": case.status, "to": body.status}
        case.status = body.status
    if body.summary is not None and body.summary != case.summary:
        changes["summary"] = "updated"
        case.summary = body.summary
    existing = {link.alert_id for link in case.alerts}
    for alert_id in dict.fromkeys(body.add_alert_ids):
        alert = alert_svc.get_scoped_alert(ctx.db, ctx.scope, alert_id)
        if alert.alert_id not in existing:
            ctx.db.add(models.CaseAlert(case_id=case.id, alert_id=alert.alert_id))
            changes.setdefault("added", []).append(alert.alert_id)
    for alert_id in body.remove_alert_ids:
        link = next((lk for lk in case.alerts if lk.alert_id == alert_id), None)
        if link is not None:
            case.alerts.remove(link)
            changes.setdefault("removed", []).append(alert_id)
    if changes:
        case.updated_at = _now()
        audit.append(
            ctx.db,
            actor=ctx.user.email,
            action="case_update",
            entity_type="case",
            entity_id=str(case.id),
            payload=changes,
        )
    ctx.db.commit()
    ctx.db.refresh(case)
    return _summary(case, ctx.db)


@router.post("/{case_id}/notes", status_code=status.HTTP_201_CREATED)
def add_note(case_id: int, body: NoteRequest, ctx: Context = Depends(reviewer)) -> dict[str, Any]:
    case = _scoped_case(ctx, case_id)
    note = models.CaseNote(case_id=case.id, author_id=ctx.user.id, body=body.body)
    ctx.db.add(note)
    case.updated_at = _now()
    audit.append(
        ctx.db,
        actor=ctx.user.email,
        action="case_note",
        entity_type="case",
        entity_id=str(case.id),
        payload={"body": body.body},
    )
    ctx.db.commit()
    return {
        "id": note.id,
        "author": ctx.user.email,
        "body": note.body,
        "created_at": note.created_at.isoformat(),
    }
