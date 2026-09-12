"""Command-palette search across works, alerts and districts, inside the caller's scope."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from backend.app import models
from backend.app.deps import Context, context
from backend.app.redact import redact_record

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(
    ctx: Context = Depends(context),
    q: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=6, ge=1, le=20),
) -> dict[str, Any]:
    like = f"%{q.strip()}%"
    works = ctx.db.execute(
        ctx.scope.apply(select(models.Work), models.Work)
        .where(or_(models.Work.work_id.ilike(like), models.Work.work_description.ilike(like)))
        .order_by(models.Work.risk_score.desc())
        .limit(limit)
    ).scalars()
    alerts = ctx.db.execute(
        ctx.scope.apply(select(models.Alert), models.Alert)
        .where(models.Alert.is_active.is_(True), models.Alert.alert_id.ilike(like))
        .order_by(models.Alert.risk_score.desc())
        .limit(limit)
    ).scalars()
    district_rows = ctx.db.execute(
        ctx.scope.apply(select(models.Work.district, models.Work.state, func.count()), models.Work)
        .where(models.Work.district.ilike(f"{q.strip()}%"))
        .group_by(models.Work.district, models.Work.state)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return {
        "works": [
            redact_record(
                {
                    "work_id": w.work_id,
                    "work_description": (w.work_description or "")[:140],
                    "district": w.district,
                    "state": w.state,
                    "band": w.band,
                    "risk_score": round(w.risk_score, 2),
                    "sanction_amount": w.sanction_amount,
                }
            )
            for w in works
        ],
        "alerts": [
            {
                "alert_id": a.alert_id,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "district": a.district,
                "amount": a.amount,
                "status": a.status,
            }
            for a in alerts
        ],
        "districts": [{"district": d, "state": s, "works": int(n)} for d, s, n in district_rows],
    }
