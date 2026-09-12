"""Trends and money at risk: category mix over time, cost distributions, treemaps."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from backend.app import queries
from backend.app.deps import Context, context
from backend.app.redact import pseudonym
from backend.app.settings import get_settings

router = APIRouter(prefix="/analytics", tags=["analytics"])

_DIMENSIONS = {
    "state": "state",
    "district": "district",
    "vendor": "vendor_name",
    "work_type": "work_type",
}


@router.get("/money-at-risk")
def money_at_risk(
    ctx: Context = Depends(context),
    by: str = Query(default="state", pattern="^(state|district|vendor|work_type)$"),
    limit: int = Query(default=30, ge=1, le=500),
) -> dict[str, Any]:
    """Sanctioned value of High/Critical works, grouped, with a treemap-ready list."""
    rows = queries.group_risk(ctx.db, ctx.scope, _DIMENSIONS[by], limit=limit)
    if by == "vendor" and get_settings().presentation_mode:
        for row in rows:
            row["key"] = pseudonym("vendor", row["key"])
    totals = queries.totals(ctx.db, ctx.scope)
    return {
        "by": by,
        "total_money_at_risk": totals["money_at_risk"],
        "total_sanctioned": totals["sanctioned"],
        "rows": rows,
        "treemap": [
            {
                "name": r["key"],
                "value": r["money_at_risk"],
                "works": r["works"],
                "state": r["state"],
            }
            for r in rows
            if r["money_at_risk"] > 0
        ],
        "note": "Money at risk is the sanctioned value of works in the High and Critical bands.",
    }


@router.get("/monthly")
def monthly(ctx: Context = Depends(context)) -> list[dict[str, Any]]:
    return queries.monthly(ctx.db, ctx.scope)


@router.get("/category-mix")
def category_mix(
    ctx: Context = Depends(context), top: int = Query(default=8, ge=3, le=20)
) -> dict[str, Any]:
    """Sanctioned value by work type per month; smaller types folded into Other."""
    w = queries.scoped_works(ctx.scope)
    leaders = [
        t
        for (t,) in ctx.db.execute(
            select(w.c.work_type)
            .select_from(w)
            .group_by(w.c.work_type)
            .order_by(func.sum(w.c.sanction_amount).desc())
            .limit(top)
        ).all()
    ]
    month = queries.month_of(ctx.db, w.c.sanction_date)
    rows = ctx.db.execute(
        select(
            month, w.c.work_type, func.count(), func.coalesce(func.sum(w.c.sanction_amount), 0.0)
        )
        .select_from(w)
        .where(w.c.sanction_date.is_not(None))
        .group_by(month, w.c.work_type)
    ).all()
    series: dict[str, dict[str, float]] = {}
    for m, work_type, _n, amount in rows:
        if not m:
            continue
        label = work_type if work_type in leaders else "Other"
        bucket = series.setdefault(m, {})
        bucket[label] = bucket.get(label, 0.0) + float(amount)
    return {
        "categories": [*leaders, "Other"],
        "months": [{"month": m, **values} for m, values in sorted(series.items())],
    }


@router.get("/cost-distribution")
def cost_distribution(
    ctx: Context = Depends(context),
    work_type: str | None = None,
    top_states: int = Query(default=15, ge=3, le=40),
) -> dict[str, Any]:
    """Box-plot statistics of sanctioned amount per state for one work type."""
    w = queries.scoped_works(ctx.scope)
    if work_type is None:
        work_type = ctx.db.execute(
            select(w.c.work_type)
            .select_from(w)
            .group_by(w.c.work_type)
            .order_by(func.count().desc())
            .limit(1)
        ).scalar_one_or_none()
    rows = ctx.db.execute(
        select(w.c.state, w.c.sanction_amount).select_from(w).where(w.c.work_type == work_type)
    ).all()
    by_state: dict[str, list[float]] = {}
    for state, amount in rows:
        if amount:
            by_state.setdefault(state, []).append(float(amount))

    def _box(values: list[float]) -> dict[str, float]:
        values.sort()

        def q(p: float) -> float:
            return values[min(len(values) - 1, max(0, round(p * (len(values) - 1))))]

        return {"p10": q(0.1), "p25": q(0.25), "median": q(0.5), "p75": q(0.75), "p90": q(0.9)}

    states = sorted(by_state.items(), key=lambda kv: len(kv[1]), reverse=True)[:top_states]
    return {
        "work_type": work_type,
        "states": [{"state": s, "n": len(v), **_box(v)} for s, v in states if len(v) >= 10],
        "note": "States with fewer than 10 works of this type are omitted: a median of a handful is noise.",
    }
