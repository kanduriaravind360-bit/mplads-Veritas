"""Command Centre: role-aware KPIs, fund flow, money at risk, what changed."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from backend.app import models, queries
from backend.app.deps import Context, context
from backend.app.redact import pseudonym
from backend.app.settings import get_settings

router = APIRouter(prefix="/overview", tags=["overview"])


def _data_cutoff(ctx: Context) -> Any:
    """Latest date in the loaded data: "this week" means the week before it."""
    return ctx.db.execute(
        select(func.max(models.Work.sanction_date)).where(models.Work.source != "ingest")
    ).scalar_one()


@router.get("")
def overview(ctx: Context = Depends(context)) -> dict[str, Any]:
    totals = queries.totals(ctx.db, ctx.scope)
    scheme = get_settings().api["scheme"]
    years = len(scheme["financial_years_covered"])
    entitlement = totals["mps"] * float(scheme["entitlement_per_mp_per_year"]) * years

    alerts_base = ctx.scope.apply(
        select(models.Alert).where(models.Alert.is_active.is_(True)), models.Alert
    ).subquery()
    by_severity = dict(
        ctx.db.execute(
            select(alerts_base.c.severity, func.count())
            .select_from(alerts_base)
            .group_by(alerts_base.c.severity)
        ).all()
    )
    by_status = dict(
        ctx.db.execute(
            select(alerts_base.c.status, func.count())
            .select_from(alerts_base)
            .group_by(alerts_base.c.status)
        ).all()
    )

    districts = queries.group_risk(ctx.db, ctx.scope, "district", limit=10)
    vendors = queries.group_risk(ctx.db, ctx.scope, "vendor_name", limit=10)
    if get_settings().presentation_mode:
        for row in vendors:
            row["key"] = pseudonym("vendor", row["key"])

    return {
        "scope": ctx.scope.label,
        "role": ctx.user.role,
        "kpis": totals,
        "fund_flow": [
            {
                "stage": "Entitlement (estimate)",
                "amount": entitlement,
                "estimate": True,
                "note": (
                    f"{totals['mps']} MPs x Rs 5 crore x {years} financial years; the "
                    "extract carries no entitlement or release figures"
                ),
            },
            {"stage": "Sanctioned", "amount": totals["sanctioned"], "estimate": False},
            {"stage": "Disbursed", "amount": totals["disbursed"], "estimate": False},
        ],
        "bands": queries.bands(ctx.db, ctx.scope),
        "alerts": {"by_severity": by_severity, "by_status": by_status},
        "top_districts": districts,
        "top_vendors": vendors,
        "what_changed": what_changed(ctx),
        "framing": "Risk indicators for review. Nothing here is a finding of fraud.",
    }


def what_changed(ctx: Context) -> dict[str, Any]:
    """The last seven days before the data cut-off, plus recent review activity.

    The eSAKSHI extract is a single snapshot, so "this week" is measured against
    its latest date rather than today, and says so.
    """
    cutoff = _data_cutoff(ctx)
    if cutoff is None:
        return {"cutoff": None}
    since = cutoff - timedelta(days=7)
    w = queries.scoped_works(ctx.scope)
    sanctioned = ctx.db.execute(
        select(func.count(), func.coalesce(func.sum(w.c.sanction_amount), 0.0))
        .select_from(w)
        .where(w.c.sanction_date > since)
    ).one()
    completed = ctx.db.execute(
        select(func.count()).select_from(w).where(w.c.completion_date > since)
    ).scalar_one()
    new_high = ctx.db.execute(
        select(func.count())
        .select_from(w)
        .where(w.c.sanction_date > since, w.c.band.in_(queries.AT_RISK_BANDS))
    ).scalar_one()

    last_run = ctx.db.execute(
        select(models.ScoringRun).order_by(models.ScoringRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()

    return {
        "data_cutoff": cutoff.isoformat(),
        "window": f"{since.isoformat()} to {cutoff.isoformat()}",
        "works_sanctioned": int(sanctioned[0]),
        "amount_sanctioned": float(sanctioned[1]),
        "works_completed": int(completed),
        "new_high_or_critical": int(new_high),
        "last_scoring_run": None
        if last_run is None
        else {
            "kind": last_run.kind,
            "finished_at": last_run.finished_at.isoformat() if last_run.finished_at else None,
            "alerts_new": last_run.alerts_new,
            "alerts_retired": last_run.alerts_retired,
            "message": last_run.message,
        },
        "note": "Measured against the latest date in the eSAKSHI extract, which is a snapshot.",
    }


@router.get("/monthly")
def monthly(ctx: Context = Depends(context)) -> list[dict[str, Any]]:
    return queries.monthly(ctx.db, ctx.scope)
