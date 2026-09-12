"""MP Portfolio: implementation risk of works recommended in one constituency.

Framing matters here. MPLADS works are recommended by the Member and executed by
district implementing agencies, so every figure on this page describes how the
works are being implemented, never a judgement of the Member. The constituency
list is alphabetical and carries no risk figures, so it cannot be read as a
ranking of Members.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, case, func, select

from backend.app import models, queries
from backend.app.deps import Context, context
from backend.app.redact import constituency_label, pseudonym
from backend.app.scoping import MP, Scope, not_found
from backend.app.serialize import work_summary
from backend.app.settings import get_settings

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

FRAMING = (
    "Implementation risk of works recommended in this constituency. It describes how "
    "executing agencies are delivering the works, not a judgement of the Member."
)


@dataclass(frozen=True)
class OneConstituency:
    """The caller's scope narrowed to one MP code. It narrows only; it never widens."""

    base: Scope
    mp_code: str

    @property
    def label(self) -> str:
        return f"{self.base.label} / MP code {self.mp_code}"

    def apply(self, stmt: Select[Any], model: type) -> Select[Any]:
        return self.base.apply(stmt, model).where(model.mp_code == self.mp_code)


def _presentable(constituency: str | None, member: str | None) -> tuple[str | None, str | None]:
    if not get_settings().presentation_mode:
        return constituency, member
    return constituency_label(constituency), pseudonym("mp", member)


@router.get("/constituencies")
def constituencies(ctx: Context = Depends(context), state: str | None = None) -> dict[str, Any]:
    stmt = ctx.scope.apply(
        select(
            models.Work.mp_code,
            func.max(models.Work.constituency),
            func.max(models.Work.mp_name),
            func.max(models.Work.chamber),
            func.max(models.Work.state),
            func.count(),
        ),
        models.Work,
    ).where(models.Work.mp_code.is_not(None))
    if state:
        stmt = stmt.where(models.Work.state == state)
    items = []
    for code, constituency, member, chamber, st, works in ctx.db.execute(
        stmt.group_by(models.Work.mp_code)
    ).all():
        label, name = _presentable(constituency, member)
        items.append(
            {
                "mp_code": code,
                "constituency": label,
                "member": name,
                "chamber": chamber,
                "state": st,
                "works": int(works),
            }
        )
    items.sort(key=lambda r: (r["state"] or "", r["constituency"] or ""))
    return {
        "items": items,
        "note": "Listed alphabetically by state and constituency. This list is not a ranking.",
    }


@router.get("")
def portfolio(
    ctx: Context = Depends(context), mp_code: str | None = Query(default=None, max_length=12)
) -> dict[str, Any]:
    if ctx.user.role == MP:
        if mp_code not in (None, ctx.scope.mp_code):
            raise not_found("constituency")
        mp_code = ctx.scope.mp_code
    if not mp_code:
        raise not_found("constituency")

    scope = OneConstituency(ctx.scope, mp_code)
    header = ctx.db.execute(
        scope.apply(
            select(
                func.max(models.Work.constituency),
                func.max(models.Work.mp_name),
                func.max(models.Work.chamber),
                func.max(models.Work.state),
                func.count(),
            ),
            models.Work,
        )
    ).one()
    if not header[4]:
        raise not_found("constituency")
    constituency, member = _presentable(header[0], header[1])

    high_delay_risk = float(get_settings().api["predictions"]["high_delay_risk"])
    scheme = get_settings().api["scheme"]
    per_year = float(scheme["entitlement_per_mp_per_year"])
    years = list(scheme["financial_years_covered"])

    w = queries.scoped_works(scope)  # type: ignore[arg-type]
    status_rows = ctx.db.execute(
        select(w.c.work_status, func.count(), func.coalesce(func.sum(w.c.sanction_amount), 0.0))
        .select_from(w)
        .group_by(w.c.work_status)
        .order_by(func.count().desc())
    ).all()
    type_rows = ctx.db.execute(
        select(w.c.work_type, func.count(), func.coalesce(func.sum(w.c.sanction_amount), 0.0))
        .select_from(w)
        .group_by(w.c.work_type)
        .order_by(func.sum(w.c.sanction_amount).desc())
        .limit(8)
    ).all()
    open_works, open_high_delay = ctx.db.execute(
        select(
            func.count(),
            func.sum(case((w.c.delay_risk >= high_delay_risk, 1), else_=0)),
        )
        .select_from(w)
        .where(w.c.is_open.is_(True))
    ).one()
    attention = ctx.db.execute(
        scope.apply(select(models.Work), models.Work)
        .where(models.Work.band.in_(queries.AT_RISK_BANDS))
        .order_by(models.Work.risk_score.desc())
        .limit(10)
    ).scalars()

    return {
        "mp_code": mp_code,
        "constituency": constituency,
        "member": member,
        "chamber": header[2],
        "state": header[3],
        "framing": FRAMING,
        "kpis": queries.totals(ctx.db, scope),  # type: ignore[arg-type]
        "entitlement_estimate": {
            "amount": per_year * len(years),
            "per_year": per_year,
            "years": years,
            "estimate": True,
            "note": (
                "Scheme rule of Rs 5 crore a year across the financial years in the extract. "
                "The extract has no release figures, so this is not a ledger."
            ),
        },
        "bands": queries.bands(ctx.db, scope),  # type: ignore[arg-type]
        "status_mix": [
            {"status": s, "works": int(n), "amount": float(a)} for s, n, a in status_rows
        ],
        "work_types": [
            {"work_type": t, "works": int(n), "amount": float(a)} for t, n, a in type_rows
        ],
        "agencies": queries.group_risk(ctx.db, scope, "ida", order="works"),  # type: ignore[arg-type]
        "monthly": queries.monthly(ctx.db, scope),  # type: ignore[arg-type]
        "open_works": int(open_works or 0),
        "open_high_delay_risk": int(open_high_delay or 0),
        "high_delay_risk_threshold": high_delay_risk,
        "attention": [work_summary(x) for x in attention],
    }
