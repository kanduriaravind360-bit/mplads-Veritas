"""Alerts: triage list, detail, lifecycle, assignment, comments, feedback, bulk, export, audit."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from backend.app import audit, models
from backend.app.deps import Context, Page, context, page, require_roles, reviewer
from backend.app.redact import redact_record
from backend.app.schemas import (
    AssignRequest,
    BulkRequest,
    ChainOut,
    CommentRequest,
    FeedbackRequest,
    TransitionRequest,
)
from backend.app.serialize import alert_detail, alert_summary, work_summary
from backend.app.services import alerts as svc

router = APIRouter(prefix="/alerts", tags=["alerts"])
audit_router = APIRouter(prefix="/audit", tags=["audit"])
_supervisors = require_roles("MINISTRY", "STATE")

_SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _filtered(
    ctx: Context,
    alert_type: list[str] | None,
    severity: list[str] | None,
    status_: list[str] | None,
    level: str | None,
    district: str | None,
    state: str | None,
    q: str | None,
    assignee: str | None,
    include_inactive: bool,
) -> Select[Any]:
    stmt = ctx.scope.apply(select(models.Alert), models.Alert)
    if not include_inactive:
        stmt = stmt.where(models.Alert.is_active.is_(True))
    if alert_type:
        stmt = stmt.where(models.Alert.alert_type.in_(alert_type))
    if severity:
        stmt = stmt.where(models.Alert.severity.in_(severity))
    if status_:
        stmt = stmt.where(models.Alert.status.in_(status_))
    if level:
        stmt = stmt.where(models.Alert.level == level)
    if district:
        stmt = stmt.where(models.Alert.district == district.upper())
    if state:
        stmt = stmt.where(models.Alert.state == state)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                models.Alert.alert_id.ilike(like),
                models.Alert.district.ilike(like),
                models.Alert.work_type.ilike(like),
            )
        )
    if assignee == "me":
        stmt = stmt.where(models.Alert.assignee_id == ctx.user.id)
    elif assignee == "unassigned":
        stmt = stmt.where(models.Alert.assignee_id.is_(None))
    return stmt


def _params(
    alert_type: list[str] | None = Query(default=None),
    severity: list[str] | None = Query(default=None),
    status_: list[str] | None = Query(default=None, alias="status"),
    level: str | None = None,
    district: str | None = None,
    state: str | None = None,
    q: str | None = None,
    assignee: str | None = Query(default=None, pattern="^(me|unassigned)$"),
    include_inactive: bool = False,
) -> dict[str, Any]:
    return locals()


@router.get("")
def list_alerts(
    ctx: Context = Depends(context),
    params: dict[str, Any] = Depends(_params),
    sort: str = Query(default="severity", pattern="^(severity|risk|amount|raised|updated)$"),
    pg: Page = Depends(page),
) -> dict[str, Any]:
    stmt = _filtered(ctx, **params)
    total = ctx.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    order = {
        "severity": [
            models.Alert.severity.in_(["Critical"]).desc(),
            models.Alert.severity.in_(["High"]).desc(),
            models.Alert.risk_score.desc(),
        ],
        "risk": [models.Alert.risk_score.desc()],
        "amount": [models.Alert.amount.desc()],
        "raised": [models.Alert.raised_at.desc()],
        "updated": [models.Alert.updated_at.desc()],
    }[sort]
    rows = ctx.db.execute(
        stmt.options(selectinload(models.Alert.assignee))
        .order_by(*order, models.Alert.alert_id)
        .limit(pg.limit)
        .offset(pg.offset)
    ).scalars()
    return {
        "total": total,
        "limit": pg.limit,
        "offset": pg.offset,
        "items": [alert_summary(a) for a in rows],
    }


@router.get("/summary")
def summary(ctx: Context = Depends(context)) -> dict[str, Any]:
    base = ctx.scope.apply(
        select(models.Alert).where(models.Alert.is_active.is_(True)), models.Alert
    ).subquery()

    def _counts(column: Any) -> dict[str, int]:
        return {
            k: int(v)
            for k, v in ctx.db.execute(
                select(column, func.count()).select_from(base).group_by(column)
            ).all()
        }

    money = ctx.db.execute(
        select(base.c.severity, func.coalesce(func.sum(base.c.amount), 0.0))
        .select_from(base)
        .group_by(base.c.severity)
    ).all()
    return {
        "by_severity": _counts(base.c.severity),
        "by_status": _counts(base.c.status),
        "by_type": _counts(base.c.alert_type),
        "by_level": _counts(base.c.level),
        "amount_by_severity": {k: float(v) for k, v in money},
    }


@router.get("/export.csv")
def export_alerts(
    ctx: Context = Depends(context), params: dict[str, Any] = Depends(_params)
) -> StreamingResponse:
    stmt = (
        _filtered(ctx, **params)
        .options(selectinload(models.Alert.assignee))
        .order_by(models.Alert.risk_score.desc())
        .limit(50_000)
    )
    columns = [
        "alert_id",
        "alert_type",
        "severity",
        "status",
        "level",
        "risk_score",
        "amount",
        "n_works",
        "state",
        "district",
        "work_type",
        "assignee",
        "raised_at",
        "top_reason_en",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    count = 0
    for alert in ctx.db.execute(stmt).scalars():
        writer.writerow(alert_summary(alert))
        count += 1
    audit.append(
        ctx.db,
        actor=ctx.user.email,
        action="export",
        entity_type="alerts",
        entity_id="csv",
        payload={"rows": count},
    )
    ctx.db.commit()
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="alerts_export.csv"'},
    )


@router.post("/bulk")
def bulk(body: BulkRequest, ctx: Context = Depends(reviewer)) -> dict[str, Any]:
    """Apply one action to many alerts. Each alert is scope-checked individually."""
    done: list[str] = []
    failed: list[dict[str, str]] = []
    for alert_id in dict.fromkeys(body.alert_ids):
        try:
            alert = svc.get_scoped_alert(ctx.db, ctx.scope, alert_id)
            if body.action == "transition":
                if not body.to_status:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY, "to_status is required"
                    )
                svc.transition(ctx.db, ctx.user, alert, body.to_status, body.note)
            else:
                svc.assign(ctx.db, ctx.user, ctx.scope, alert, body.assignee_email)
            done.append(alert_id)
        except HTTPException as error:
            failed.append({"alert_id": alert_id, "error": str(error.detail)})
    ctx.db.commit()
    return {"done": done, "failed": failed}


@router.post("/{alert_id:path}/transition")
def transition(
    alert_id: str, body: TransitionRequest, ctx: Context = Depends(reviewer)
) -> dict[str, Any]:
    alert = svc.get_scoped_alert(ctx.db, ctx.scope, alert_id)
    svc.transition(ctx.db, ctx.user, alert, body.to_status, body.note)
    ctx.db.commit()
    return alert_summary(alert)


@router.post("/{alert_id:path}/assign")
def assign(alert_id: str, body: AssignRequest, ctx: Context = Depends(reviewer)) -> dict[str, Any]:
    alert = svc.get_scoped_alert(ctx.db, ctx.scope, alert_id)
    svc.assign(ctx.db, ctx.user, ctx.scope, alert, body.assignee_email)
    ctx.db.commit()
    ctx.db.refresh(alert)
    return alert_summary(alert)


@router.post("/{alert_id:path}/comments")
def add_comment(
    alert_id: str, body: CommentRequest, ctx: Context = Depends(reviewer)
) -> dict[str, Any]:
    alert = svc.get_scoped_alert(ctx.db, ctx.scope, alert_id)
    row = svc.comment(ctx.db, ctx.user, alert, body.body)
    ctx.db.commit()
    return {
        "id": row.id,
        "author": ctx.user.email,
        "body": row.body,
        "created_at": row.created_at.isoformat(),
    }


@router.post("/{alert_id:path}/feedback")
def add_feedback(
    alert_id: str, body: FeedbackRequest, ctx: Context = Depends(reviewer)
) -> dict[str, Any]:
    alert = svc.get_scoped_alert(ctx.db, ctx.scope, alert_id)
    row = svc.feedback(ctx.db, ctx.user, alert, body.verdict, body.note, body.work_id)
    ctx.db.commit()
    return {"id": row.id, "verdict": row.verdict, "work_id": row.work_id}


@router.get("/{alert_id:path}/audit")
def alert_audit(alert_id: str, ctx: Context = Depends(context)) -> list[dict[str, Any]]:
    alert = svc.get_scoped_alert(ctx.db, ctx.scope, alert_id)
    return audit.trail_for(ctx.db, "alert", alert.alert_id)


# Registered last: the path converter would otherwise swallow the sub-routes.
@router.get("/{alert_id:path}")
def get_alert(alert_id: str, ctx: Context = Depends(context)) -> dict[str, Any]:
    alert = svc.get_scoped_alert(ctx.db, ctx.scope, alert_id)
    out = alert_detail(alert)
    work_ids = out["work_ids"]
    works = (
        ctx.db.execute(
            ctx.scope.apply(
                select(models.Work).where(models.Work.work_id.in_(work_ids)), models.Work
            )
        )
        .scalars()
        .all()
    )
    out["works"] = [work_summary(w) for w in works]
    if len(works) == 1:
        from backend.app.serialize import work_detail

        out["work"] = work_detail(works[0])
    out["allowed_transitions"] = (
        svc.allowed_transitions(alert, ctx.user.role) if ctx.user.role != "MP" else []
    )
    comments = ctx.db.execute(
        select(models.Comment)
        .options(selectinload(models.Comment.author))
        .where(models.Comment.alert_id == alert.alert_id)
        .order_by(models.Comment.created_at)
    ).scalars()
    out["comments"] = [
        {
            "id": c.id,
            "author": c.author.email,
            "body": c.body,
            "created_at": c.created_at.isoformat(),
        }
        for c in comments
    ]
    feedback = ctx.db.execute(
        select(models.Feedback)
        .where(models.Feedback.alert_id == alert.alert_id)
        .order_by(models.Feedback.created_at)
    ).scalars()
    out["feedback"] = [
        {
            "verdict": f.verdict,
            "note": f.note,
            "work_id": f.work_id,
            "is_seed": f.is_seed,
            "created_at": f.created_at.isoformat(),
        }
        for f in feedback
    ]
    out["audit"] = audit.trail_for(ctx.db, "alert", alert.alert_id)
    out["suggested_action"] = _suggested_action(alert)
    return redact_record(out)


def _suggested_action(alert: models.Alert) -> str:
    """What a reviewer should check first. Wording frames a check, never a finding."""
    if alert.alert_type == "split_work_group":
        return "Check whether these works are parts of one project, and whether the combined value needed a higher sanctioning authority."
    if alert.alert_type == "duplicate_group":
        return "Compare the works side by side; confirm with the implementing agency whether they are one physical asset recorded twice."
    reasons = " ".join(alert.reasons_en or []).lower()
    if "cost" in reasons:
        return "Request the estimate and bill of quantities; compare the rate with the state schedule of rates."
    if "stage" in reasons or "chance of running past" in reasons:
        return "Ask the implementing agency for a status update and a revised completion date."
    if "fully paid" in reasons or "unusually fast" in reasons:
        return "Verify completion on the ground (photo or inspection) before relying on the recorded dates."
    return "Review the evidence below and record a verdict."


@audit_router.get("/verify", response_model=ChainOut)
def verify_chain(ctx: Context = Depends(_supervisors)) -> ChainOut:
    report = audit.verify(ctx.db)
    return ChainOut(**report.as_dict(), checked_at=datetime.now(UTC))
