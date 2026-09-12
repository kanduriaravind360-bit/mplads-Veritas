"""Scoped aggregate queries shared by several routers.

Every function here starts from ``scope.apply(select(Work))``, so an aggregate
can never include a row the caller could not read individually.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Subquery

from backend.app import models
from backend.app.scoping import Scope

AT_RISK_BANDS = ("High", "Critical")


def scoped_works(scope: Scope, *conditions: Any) -> Subquery:
    stmt = scope.apply(select(models.Work), models.Work)
    for condition in conditions:
        stmt = stmt.where(condition)
    return stmt.subquery()


def totals(db: Session, scope: Scope) -> dict[str, Any]:
    w = scoped_works(scope)
    at_risk = case((w.c.band.in_(AT_RISK_BANDS), w.c.sanction_amount), else_=0.0)
    row = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(w.c.sanction_amount), 0.0),
            func.coalesce(func.sum(w.c.total_fund_disbursed), 0.0),
            func.sum(case((w.c.is_open.is_(False), 1), else_=0)),
            func.sum(case((w.c.band.in_(AT_RISK_BANDS), 1), else_=0)),
            func.coalesce(func.sum(at_risk), 0.0),
            func.count(func.distinct(w.c.mp_code)),
            func.count(func.distinct(w.c.district)),
            func.avg(w.c.risk_score),
        ).select_from(w)
    ).one()
    works, sanctioned, disbursed, completed, high_crit, money_at_risk, mps, districts, mean_risk = (
        row
    )
    works = int(works or 0)
    return {
        "works": works,
        "sanctioned": float(sanctioned),
        "disbursed": float(disbursed),
        "completed": int(completed or 0),
        "completion_rate": (int(completed or 0) / works) if works else 0.0,
        "utilisation": (float(disbursed) / float(sanctioned)) if sanctioned else 0.0,
        "high_or_critical": int(high_crit or 0),
        "money_at_risk": float(money_at_risk),
        "money_at_risk_share": (float(money_at_risk) / float(sanctioned)) if sanctioned else 0.0,
        "mps": int(mps or 0),
        "districts": int(districts or 0),
        "mean_risk": float(mean_risk or 0.0),
    }


def bands(db: Session, scope: Scope) -> list[dict[str, Any]]:
    w = scoped_works(scope)
    rows = db.execute(
        select(w.c.band, func.count(), func.coalesce(func.sum(w.c.sanction_amount), 0.0))
        .select_from(w)
        .group_by(w.c.band)
    ).all()
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    return sorted(
        ({"band": b, "works": int(n), "amount": float(a)} for b, n, a in rows),
        key=lambda r: order.get(r["band"], 9),
    )


def group_risk(
    db: Session,
    scope: Scope,
    dimension: str,
    limit: int | None = None,
    order: str = "money_at_risk",
) -> list[dict[str, Any]]:
    """Per-group works, value, money at risk and rates. Always carries the denominator."""
    w = scoped_works(scope)
    key = getattr(w.c, dimension)
    at_risk_amount = case((w.c.band.in_(AT_RISK_BANDS), w.c.sanction_amount), else_=0.0)
    at_risk_n = case((w.c.band.in_(AT_RISK_BANDS), 1), else_=0)
    open_delay = case((w.c.is_open.is_(True), w.c.delay_risk), else_=None)
    stmt = (
        select(
            key.label("key"),
            func.max(w.c.state).label("state"),
            func.count().label("works"),
            func.coalesce(func.sum(w.c.sanction_amount), 0.0).label("sanctioned"),
            func.coalesce(func.sum(w.c.total_fund_disbursed), 0.0).label("disbursed"),
            func.coalesce(func.sum(at_risk_amount), 0.0).label("money_at_risk"),
            func.sum(at_risk_n).label("high_or_critical"),
            func.avg(w.c.risk_score).label("mean_risk"),
            func.avg(open_delay).label("mean_delay_risk"),
            func.sum(case((w.c.is_open.is_(False), 1), else_=0)).label("completed"),
        )
        .select_from(w)
        .where(key.is_not(None), key != "")
        .group_by(key)
    )
    sort_col = {
        "money_at_risk": "money_at_risk",
        "mean_risk": "mean_risk",
        "works": "works",
        "sanctioned": "sanctioned",
        "mean_delay_risk": "mean_delay_risk",
    }.get(order, "money_at_risk")
    # Sorted in Python below: the result is one row per group, so it is small.
    rows = db.execute(stmt).mappings().all()
    out = []
    for r in rows:
        works = int(r["works"])
        sanctioned = float(r["sanctioned"])
        out.append(
            {
                "key": r["key"],
                "state": r["state"],
                "works": works,
                "sanctioned": sanctioned,
                "disbursed": float(r["disbursed"]),
                "money_at_risk": float(r["money_at_risk"]),
                "high_or_critical": int(r["high_or_critical"] or 0),
                "high_or_critical_share": (int(r["high_or_critical"] or 0) / works)
                if works
                else 0.0,
                "mean_risk": float(r["mean_risk"] or 0.0),
                "mean_delay_risk": None
                if r["mean_delay_risk"] is None
                else float(r["mean_delay_risk"]),
                "completion_rate": (int(r["completed"] or 0) / works) if works else 0.0,
                "utilisation": (float(r["disbursed"]) / sanctioned) if sanctioned else 0.0,
                # A group this small cannot support a rate; the UI marks it.
                "low_volume": works < 20,
            }
        )
    out.sort(key=lambda r: (r.get(sort_col) or 0.0), reverse=True)
    return out[:limit] if limit else out


def month_of(db: Session, column: Any) -> Any:
    """``YYYY-MM`` of a date column, in whichever SQL dialect is connected."""
    if db.get_bind().dialect.name == "postgresql":
        return func.to_char(column, "YYYY-MM")
    return func.strftime("%Y-%m", column)


def monthly(db: Session, scope: Scope) -> list[dict[str, Any]]:
    w = scoped_works(scope, models.Work.sanction_date.is_not(None))
    month = month_of(db, w.c.sanction_date)
    rows = db.execute(
        select(month, func.count(), func.coalesce(func.sum(w.c.sanction_amount), 0.0))
        .select_from(w)
        .group_by(month)
        .order_by(month)
    ).all()
    return [
        {"month": m, "works": int(n), "amount": float(a), "is_march": bool(m and m.endswith("-03"))}
        for m, n, a in rows
        if m
    ]


def ratio(numerator: Any, denominator: Any) -> Any:
    return cast(numerator, Float) / func.nullif(cast(denominator, Float), 0.0)
