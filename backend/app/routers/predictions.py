"""Delay early warning and a fund-lapse estimate."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select

from backend.app import models, queries
from backend.app.deps import Context, Page, context, page
from backend.app.serialize import work_summary

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("/delay")
def delay(
    ctx: Context = Depends(context),
    min_probability: float = Query(default=0.0, ge=0.0, le=1.0),
    district: str | None = None,
    pg: Page = Depends(page),
) -> dict[str, Any]:
    stmt = ctx.scope.apply(select(models.Work), models.Work).where(
        models.Work.is_open.is_(True), models.Work.delay_risk >= min_probability
    )
    if district:
        stmt = stmt.where(models.Work.district == district.upper())
    total = ctx.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    works = ctx.db.execute(
        stmt.order_by(models.Work.delay_risk.desc()).limit(pg.limit).offset(pg.offset)
    ).scalars()
    items = []
    for work in works:
        row = work_summary(work)
        drivers = (work.detail or {}).get("delay_reasons", [])
        row["delay_drivers"] = drivers[:3]
        row["delay_reason_en"] = next(
            (r for r in (work.reasons_en or []) if "chance of running past" in r), None
        )
        items.append(row)

    w = queries.scoped_works(ctx.scope, models.Work.is_open.is_(True))
    high = ctx.db.execute(
        select(func.count(), func.coalesce(func.sum(w.c.sanction_amount), 0.0))
        .select_from(w)
        .where(w.c.delay_risk >= 0.7)
    ).one()
    open_count = ctx.db.execute(select(func.count()).select_from(w)).scalar_one()
    return {
        "total": total,
        "limit": pg.limit,
        "offset": pg.offset,
        "items": items,
        "summary": {
            "open_works": int(open_count),
            "high_delay_risk_works": int(high[0]),
            "high_delay_risk_value": float(high[1]),
            "threshold": 0.7,
        },
        "note": "Probability of an open work running past a year without completion (delay model, holdout ROC-AUC 0.909).",
    }


@router.get("/fund-lapse")
def fund_lapse(
    ctx: Context = Depends(context), limit: int = Query(default=30, ge=1, le=800)
) -> dict[str, Any]:
    """Undisbursed value on open works, weighted by each work's delay probability.

    An estimate, and labelled as one: the extract has no fund-release or balance
    figures, so this is the value most likely to stay unspent if delays run as
    predicted, not an accounting of lapsed funds.
    """
    w = queries.scoped_works(ctx.scope, models.Work.is_open.is_(True))
    gap = w.c.sanction_amount - func.coalesce(w.c.total_fund_disbursed, 0.0)
    undisbursed = case((gap > 0, gap), else_=0.0)
    rows = ctx.db.execute(
        select(
            w.c.district,
            func.max(w.c.state),
            func.count(),
            func.coalesce(func.sum(undisbursed), 0.0),
            func.coalesce(func.sum(undisbursed * w.c.delay_risk), 0.0),
            func.sum(case((w.c.delay_risk >= 0.7, 1), else_=0)),
        )
        .select_from(w)
        .group_by(w.c.district)
    ).all()
    out = [
        {
            "district": d,
            "state": s,
            "open_works": int(n),
            "undisbursed": float(u),
            "expected_unspent": float(e),
            "high_delay_risk_works": int(h or 0),
            "low_volume": int(n) < 20,
        }
        for d, s, n, u, e, h in rows
        if d
    ]
    out.sort(key=lambda r: r["expected_unspent"], reverse=True)
    return {
        "rows": out[:limit],
        "total_expected_unspent": sum(r["expected_unspent"] for r in out),
        "estimate": True,
        "note": (
            "Estimate: undisbursed value on open works x predicted delay probability. The "
            "eSAKSHI extract has no release or balance data, so this is not a lapse ledger."
        ),
    }
