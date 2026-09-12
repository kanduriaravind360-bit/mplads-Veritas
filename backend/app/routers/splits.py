"""Split-work groups: list and detail with the member works on a timeline."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from backend.app import models
from backend.app.deps import Context, Page, context, page
from backend.app.metrics_doc import weakest_detector_note
from backend.app.scoping import not_found
from backend.app.serialize import split_group, work_summary

router = APIRouter(prefix="/splits", tags=["splits"])


@router.get("")
def list_splits(
    ctx: Context = Depends(context),
    min_score: float = Query(default=0.0, ge=0.0, le=1.0),
    district: str | None = None,
    pg: Page = Depends(page),
) -> dict[str, Any]:
    stmt = ctx.scope.apply(select(models.SplitGroup), models.SplitGroup).where(
        models.SplitGroup.split_score >= min_score
    )
    if district:
        stmt = stmt.where(models.SplitGroup.ida.ilike(f"{district.upper()}%"))
    total = ctx.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = ctx.db.execute(
        stmt.order_by(models.SplitGroup.split_score.desc(), models.SplitGroup.total_amount.desc())
        .limit(pg.limit)
        .offset(pg.offset)
    ).scalars()
    return {
        "total": total,
        "limit": pg.limit,
        "offset": pg.offset,
        "items": [split_group(g) for g in rows],
        "note": weakest_detector_note(ctx.db),
    }


@router.get("/{group_id}")
def get_split(group_id: str, ctx: Context = Depends(context)) -> dict[str, Any]:
    group = ctx.db.execute(
        ctx.scope.apply(
            select(models.SplitGroup).where(models.SplitGroup.split_group_id == group_id),
            models.SplitGroup,
        )
    ).scalar_one_or_none()
    if group is None:
        raise not_found("split group")
    works = (
        ctx.db.execute(
            ctx.scope.apply(
                select(models.Work).where(models.Work.work_id.in_(group.work_ids)), models.Work
            ).order_by(models.Work.sanction_date)
        )
        .scalars()
        .all()
    )
    alert = ctx.db.get(models.Alert, group.split_group_id)
    return {
        **split_group(group),
        "works": [work_summary(w) for w in works],
        "alert_id": alert.alert_id if alert is not None else None,
        "alert_status": alert.status if alert is not None else None,
    }
