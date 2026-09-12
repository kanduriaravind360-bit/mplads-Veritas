"""Operations: reviewers for assignment, escalation and re-score triggers, job log."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from backend.app import audit, models
from backend.app.deps import Context, require_roles, reviewer
from backend.app.scoping import Scope
from backend.app.settings import get_settings

router = APIRouter(prefix="/admin", tags=["admin"])
_ministry = require_roles("MINISTRY")
_supervisors = require_roles("MINISTRY", "STATE")


@router.get("/reviewers")
def reviewers(ctx: Context = Depends(reviewer)) -> list[dict[str, Any]]:
    """Reviewers whose scope overlaps the caller's, for the assignment picker."""
    roles = set(get_settings().api["alerts"]["reviewer_roles"])
    users = ctx.db.execute(
        select(models.User).where(models.User.role.in_(roles), models.User.is_active.is_(True))
    ).scalars()
    out = []
    for user in users:
        scope = Scope.for_user(user)
        overlaps = (
            ctx.scope.role == "MINISTRY"
            or scope.role == "MINISTRY"
            or (ctx.scope.state and scope.state == ctx.scope.state)
            or (ctx.scope.ida and scope.ida == ctx.scope.ida)
            or (ctx.scope.role == "STATE" and scope.role == "DISTRICT")
        )
        if overlaps:
            out.append(
                {"email": user.email, "name": user.name, "role": user.role, "scope": scope.label}
            )
    return out


@router.post("/escalate")
def escalate_now(ctx: Context = Depends(_ministry)) -> dict[str, Any]:
    from backend.app.services.alerts import escalate_due

    moved = escalate_due(ctx.db)
    audit.append(
        ctx.db,
        actor=ctx.user.email,
        action="escalation_run",
        entity_type="job",
        entity_id="escalation",
        payload={"moved": len(moved)},
    )
    ctx.db.commit()
    return {"escalated": len(moved), "alerts": moved[:100]}


@router.post("/rescore")
def rescore_now(ctx: Context = Depends(_ministry)) -> dict[str, Any]:
    """Start a re-score in the background; progress appears in /admin/runs."""
    from backend.app.scheduler import run_rescore

    audit.append(
        ctx.db,
        actor=ctx.user.email,
        action="rescore_requested",
        entity_type="job",
        entity_id="rescore",
    )
    ctx.db.commit()
    threading.Thread(target=run_rescore, kwargs={"kind": "manual"}, daemon=True).start()
    return {"started": True}


@router.get("/runs")
def runs(ctx: Context = Depends(_supervisors)) -> dict[str, Any]:
    from backend.app.scheduler import jobs

    rows = ctx.db.execute(
        select(models.ScoringRun).order_by(models.ScoringRun.started_at.desc()).limit(30)
    ).scalars()
    count, head = audit.head(ctx.db)
    return {
        "runs": [
            {
                "id": r.id,
                "kind": r.kind,
                "status": r.status,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "works_loaded": r.works_loaded,
                "alerts_new": r.alerts_new,
                "alerts_retired": r.alerts_retired,
                "message": r.message,
            }
            for r in rows
        ],
        "scheduled_jobs": jobs(),
        "audit_events": count,
        "audit_head_hash": head,
    }
