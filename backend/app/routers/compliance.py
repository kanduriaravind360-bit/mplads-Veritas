"""Compliance monitor: rule rates by district, and data completeness."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select

from backend.app import queries
from backend.app.deps import Context, context

router = APIRouter(prefix="/compliance", tags=["compliance"])

RULES = {
    "rule_sanction_delay": "Slow sanction",
    "rule_stuck_work": "Stalled in early stage",
    "rule_cost_outlier": "Cost outlier",
    "rule_fast_completion": "Unusually fast completion",
    "rule_round_amount": "Round amount",
    "rule_vendor_concentration": "Vendor concentration",
    "rule_payment_stuck": "Payment stuck",
}

_FIELDS = {
    "vendor_name": "Vendor recorded",
    "total_fund_disbursed": "Disbursement recorded",
    "latest_expenditure_date": "Expenditure date",
    "recommended_date": "Recommendation date",
    "work_description": "Description",
}


@router.get("/rules")
def rule_heatmap(
    ctx: Context = Depends(context),
    limit: int = Query(default=40, ge=5, le=800),
    min_works: int = Query(default=20, ge=1),
) -> dict[str, Any]:
    """Share of works tripping each rule, per district (largest districts first)."""
    w = queries.scoped_works(ctx.scope)
    columns = [
        func.sum(case((getattr(w.c, rule).is_(True), 1), else_=0)).label(rule) for rule in RULES
    ]
    rows = ctx.db.execute(
        select(w.c.district, func.max(w.c.state), func.count().label("works"), *columns)
        .select_from(w)
        .group_by(w.c.district)
        .having(func.count() >= min_works)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    matrix = []
    for row in rows:
        district, state, works = row[0], row[1], int(row[2])
        rates = {rule: (int(row[3 + i] or 0) / works) for i, rule in enumerate(RULES)}
        matrix.append({"district": district, "state": state, "works": works, "rates": rates})
    national = ctx.db.execute(select(func.count(), *columns).select_from(w)).one()
    total = int(national[0]) or 1
    return {
        "rules": [{"key": k, "label": v} for k, v in RULES.items()],
        "rows": matrix,
        "baseline": {rule: int(national[1 + i] or 0) / total for i, rule in enumerate(RULES)},
        "note": (
            "Round amount fires on about a third of all works and is weak evidence on "
            "its own. Districts below min_works are omitted rather than shown as rates."
        ),
    }


@router.get("/completeness")
def completeness(
    ctx: Context = Depends(context), limit: int = Query(default=40, ge=5, le=800)
) -> dict[str, Any]:
    """Share of works with each eSAKSHI field filled, per district.

    This is DATA completeness. The extract has no document fields, so the
    product does not claim to check documents.
    """
    w = queries.scoped_works(ctx.scope)
    present = [func.sum(case((getattr(w.c, f).is_not(None), 1), else_=0)).label(f) for f in _FIELDS]
    rows = ctx.db.execute(
        select(w.c.district, func.max(w.c.state), func.count(), *present)
        .select_from(w)
        .group_by(w.c.district)
        .having(func.count() >= 20)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return {
        "fields": [{"key": k, "label": v} for k, v in _FIELDS.items()],
        "rows": [
            {
                "district": r[0],
                "state": r[1],
                "works": int(r[2]),
                "shares": {f: int(r[3 + i] or 0) / int(r[2]) for i, f in enumerate(_FIELDS)},
            }
            for r in rows
        ],
        "note": "Data completeness of the eSAKSHI record, not document completeness.",
    }
