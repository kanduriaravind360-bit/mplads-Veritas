"""Works: filter, search, paginate, detail, peers, CSV export."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, or_, select

from backend.app import audit, models
from backend.app.deps import Context, Page, context, page
from backend.app.redact import redact_record
from backend.app.scoping import not_found
from backend.app.serialize import alert_summary, work_detail, work_summary

router = APIRouter(prefix="/works", tags=["works"])

_SORTS = {
    "risk": models.Work.risk_score.desc(),
    "-risk": models.Work.risk_score.asc(),
    "amount": models.Work.sanction_amount.desc(),
    "sanction_date": models.Work.sanction_date.desc(),
    "delay": models.Work.delay_risk.desc(),
}


def filtered_works(
    ctx: Context,
    q: str | None = None,
    state: str | None = None,
    district: str | None = None,
    ida: str | None = None,
    work_type: str | None = None,
    band: list[str] | None = None,
    status: str | None = None,
    source: str | None = None,
    vendor: str | None = None,
    min_risk: float | None = None,
    open_only: bool = False,
) -> Select[Any]:
    """The scoped, filtered works query. User filters narrow the scope; never widen it."""
    stmt = ctx.scope.apply(select(models.Work), models.Work)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                models.Work.work_id.ilike(like),
                models.Work.work_description.ilike(like),
                models.Work.district.ilike(like),
            )
        )
    if state:
        stmt = stmt.where(models.Work.state == state)
    if district:
        stmt = stmt.where(models.Work.district == district.upper())
    if ida:
        stmt = stmt.where(models.Work.ida == ida)
    if work_type:
        stmt = stmt.where(models.Work.work_type == work_type)
    if band:
        stmt = stmt.where(models.Work.band.in_(band))
    if status:
        stmt = stmt.where(models.Work.work_status == status)
    if source:
        stmt = stmt.where(models.Work.source == source)
    if vendor:
        stmt = stmt.where(models.Work.vendor_name.ilike(f"%{vendor.strip()}%"))
    if min_risk is not None:
        stmt = stmt.where(models.Work.risk_score >= min_risk)
    if open_only:
        stmt = stmt.where(models.Work.is_open.is_(True))
    return stmt


def _query_params(
    q: str | None = None,
    state: str | None = None,
    district: str | None = None,
    ida: str | None = None,
    work_type: str | None = None,
    band: list[str] | None = Query(default=None),
    status: str | None = None,
    source: str | None = None,
    vendor: str | None = None,
    min_risk: float | None = Query(default=None, ge=0, le=100),
    open_only: bool = False,
) -> dict[str, Any]:
    return locals()


@router.get("")
def list_works(
    ctx: Context = Depends(context),
    params: dict[str, Any] = Depends(_query_params),
    sort: str = Query(default="risk", pattern="^-?(risk|amount|sanction_date|delay)$"),
    pg: Page = Depends(page),
) -> dict[str, Any]:
    stmt = filtered_works(ctx, **params)
    total = ctx.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = ctx.db.execute(
        stmt.order_by(_SORTS.get(sort, _SORTS["risk"])).limit(pg.limit).offset(pg.offset)
    ).scalars()
    return {
        "total": total,
        "limit": pg.limit,
        "offset": pg.offset,
        "items": [work_summary(w) for w in rows],
    }


@router.get("/facets")
def facets(ctx: Context = Depends(context)) -> dict[str, Any]:
    """Filter options inside the caller's scope."""
    base = ctx.scope.apply(select(models.Work), models.Work).subquery()

    def _values(column: Any) -> list[dict[str, Any]]:
        rows = ctx.db.execute(
            select(column, func.count())
            .select_from(base)
            .group_by(column)
            .order_by(func.count().desc())
        ).all()
        return [{"value": v, "count": c} for v, c in rows if v]

    return {
        "states": _values(base.c.state),
        "districts": _values(base.c.district),
        "work_types": _values(base.c.work_type),
        "bands": _values(base.c.band),
        "statuses": _values(base.c.work_status),
        "sources": _values(base.c.source),
    }


def get_scoped_work(ctx: Context, work_id: str) -> models.Work:
    stmt = ctx.scope.apply(select(models.Work).where(models.Work.work_id == work_id), models.Work)
    work = ctx.db.execute(stmt).scalar_one_or_none()
    if work is None:
        raise not_found("work")
    return work


@router.get("/export.csv")
def export_works(
    ctx: Context = Depends(context),
    params: dict[str, Any] = Depends(_query_params),
) -> StreamingResponse:
    """The same scoped, filtered set as the list, as CSV. Capped at 50,000 rows."""
    stmt = filtered_works(ctx, **params).order_by(models.Work.risk_score.desc()).limit(50_000)
    columns = [
        "work_id",
        "state",
        "district",
        "constituency",
        "mp_name",
        "work_type",
        "work_status",
        "vendor_name",
        "sanction_date",
        "sanction_amount",
        "risk_score",
        "band",
        "top_reason_en",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    count = 0
    for work in ctx.db.execute(stmt).scalars():
        writer.writerow(work_summary(work))
        count += 1
    audit.append(
        ctx.db,
        actor=ctx.user.email,
        action="export",
        entity_type="works",
        entity_id="csv",
        payload={"rows": count, "filters": {k: v for k, v in params.items() if v}},
    )
    ctx.db.commit()
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="works_export.csv"'},
    )


@router.get("/{work_id:path}/counterfactual")
def counterfactual(work_id: str, ctx: Context = Depends(context)) -> dict[str, Any]:
    """What evidence would have to change for this work to leave the review queue."""
    from backend.app.services.fusion import counterfactual as explain

    return explain(ctx.db, get_scoped_work(ctx, work_id))


@router.get("/{work_id:path}/peers")
def peers(work_id: str, ctx: Context = Depends(context)) -> dict[str, Any]:
    """This work's cost against the same work type in the same state, and in its district."""
    work = get_scoped_work(ctx, work_id)
    # Peer statistics are aggregates, so they are computed over ALL works of the
    # type, not just the caller's scope: a district user comparing against their
    # own dozen works would get a meaningless median.
    same_state = select(models.Work.sanction_amount).where(
        models.Work.work_type == work.work_type, models.Work.state == work.state
    )
    amounts = sorted(a for (a,) in ctx.db.execute(same_state).all() if a)
    national = sorted(
        a
        for (a,) in ctx.db.execute(
            select(models.Work.sanction_amount).where(models.Work.work_type == work.work_type)
        ).all()
        if a
    )

    def _quantiles(values: list[float]) -> dict[str, float] | None:
        if not values:
            return None

        def q(p: float) -> float:
            idx = min(len(values) - 1, max(0, round(p * (len(values) - 1))))
            return float(values[idx])

        return {
            "n": len(values),
            "p10": q(0.10),
            "p25": q(0.25),
            "median": q(0.5),
            "p75": q(0.75),
            "p90": q(0.9),
        }

    return {
        "work_id": work.work_id,
        "work_type": work.work_type,
        "state": work.state,
        "amount": work.sanction_amount,
        "expected_amount": work.expected_cost_amount,
        "state_peers": _quantiles(amounts),
        "national_peers": _quantiles(national),
        "ratio_to_state_median": work.state_cost_ratio,
        "note": "Peer figures are aggregates across all works of this type; they name no one.",
    }


@router.get("/{work_id:path}")
def get_work(work_id: str, ctx: Context = Depends(context)) -> dict[str, Any]:
    work = get_scoped_work(ctx, work_id)
    out = work_detail(work)

    alerts = ctx.db.execute(
        ctx.scope.apply(
            select(models.Alert)
            .join(models.AlertWork, models.AlertWork.alert_id == models.Alert.alert_id)
            .where(models.AlertWork.work_id == work.work_id),
            models.Alert,
        )
    ).scalars()
    out["alerts"] = [alert_summary(a) for a in alerts]

    pairs = ctx.db.execute(
        select(models.DuplicatePair)
        .where(
            or_(
                models.DuplicatePair.work_id_a == work.work_id,
                models.DuplicatePair.work_id_b == work.work_id,
            )
        )
        .order_by(models.DuplicatePair.pair_score.desc())
        .limit(10)
    ).scalars()
    similar: list[dict[str, Any]] = []
    for pair in pairs:
        other_id = pair.work_id_b if pair.work_id_a == work.work_id else pair.work_id_a
        other = ctx.db.execute(
            ctx.scope.apply(select(models.Work).where(models.Work.work_id == other_id), models.Work)
        ).scalar_one_or_none()
        if other is None:
            continue
        similar.append(
            redact_record(
                {
                    "pair_id": pair.id,
                    "work_id": other.work_id,
                    "work_description": other.work_description,
                    "sanction_amount": other.sanction_amount,
                    "sanction_date": other.sanction_date.isoformat()
                    if other.sanction_date
                    else None,
                    "pair_score": pair.pair_score,
                    "decision": pair.decision,
                }
            )
        )
    out["similar_works"] = similar
    out["audit"] = audit.trail_for(ctx.db, "work", work.work_id)
    out["data_completeness"] = _completeness(work)
    return out


_COMPLETENESS_FIELDS = (
    ("recommended_date", "Recommendation date"),
    ("sanction_date", "Sanction date"),
    ("sanction_amount", "Sanctioned amount"),
    ("vendor_name", "Vendor"),
    ("total_fund_disbursed", "Disbursement recorded"),
    ("latest_expenditure_date", "Latest expenditure date"),
    ("completion_date", "Completion date"),
    ("work_description", "Description"),
)


def _completeness(work: models.Work) -> list[dict[str, Any]]:
    """Which eSAKSHI fields are filled for this work.

    This is data completeness, not document completeness: the extract carries no
    document fields, so the product does not pretend to check documents.
    """
    out: list[dict[str, Any]] = []
    for field, label in _COMPLETENESS_FIELDS:
        value = getattr(work, field)
        applicable = not (field == "completion_date" and work.is_open)
        out.append(
            {
                "field": field,
                "label": label,
                "present": value not in (None, "", 0),
                "applicable": applicable,
            }
        )
    return out
