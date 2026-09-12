"""PDF briefs: alert, case, district."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select

from backend.app import audit, models, queries
from backend.app.deps import Context, reviewer
from backend.app.redact import redact_record
from backend.app.scoping import not_found
from backend.app.serialize import work_detail, work_summary
from backend.app.services import alerts as alert_svc
from backend.app.services.reports import Brief, inr, render

router = APIRouter(prefix="/reports", tags=["reports"])


def _pdf(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/alerts/{alert_id:path}.pdf")
def alert_brief(alert_id: str, ctx: Context = Depends(reviewer)) -> Response:
    alert = alert_svc.get_scoped_alert(ctx.db, ctx.scope, alert_id)
    works = (
        ctx.db.execute(
            ctx.scope.apply(
                select(models.Work).where(
                    models.Work.work_id.in_([link.work_id for link in alert.works])
                ),
                models.Work,
            )
        )
        .scalars()
        .all()
    )
    pdf = Brief(
        f"Alert {alert.alert_id}", f"{alert.alert_type.replace('_', ' ')} | {ctx.scope.label}"
    )
    pdf.title_block()
    pdf.section("Summary")
    pdf.fields(
        [
            ("Severity", f"{alert.severity} (risk score {alert.risk_score or 0:.1f})"),
            ("Status / level", f"{alert.status} at {alert.level} level"),
            ("Where", f"{alert.district}, {alert.state}"),
            ("Value", inr(alert.amount)),
            ("Works", alert.n_works),
        ]
    )
    pdf.section("Why this was flagged")
    pdf.bullets(alert.reasons_en or ["No reason recorded."])
    pdf.section("Works")
    pdf.table(
        ["Work id", "Type", "Sanctioned", "Amount", "Band", "Risk"],
        [
            [
                w.work_id,
                w.work_type,
                w.sanction_date or "-",
                inr(w.sanction_amount),
                w.band,
                f"{w.risk_score:.1f}",
            ]
            for w in works
        ],
        [52, 42, 22, 30, 16, 16],
    )
    if len(works) == 1:
        detail = work_detail(works[0])
        pdf.section("Evidence")
        signals = detail["signals"]
        pdf.fields(
            [
                (
                    "Description",
                    redact_record({"work_description": works[0].work_description})[
                        "work_description"
                    ],
                ),
                ("Signals (0-1)", ", ".join(f"{k} {v:.2f}" for k, v in signals.items())),
                (
                    "Cost",
                    f"{inr(works[0].sanction_amount)} against about {inr(works[0].expected_cost_amount)} predicted",
                ),
                (
                    "State peers",
                    f"{works[0].state_peer_label or '-'}: median {inr(works[0].state_peer_median)}",
                ),
            ]
        )
    pdf.chain(audit.trail_for(ctx.db, "alert", alert.alert_id), audit.verify(ctx.db).as_dict())
    audit.append(
        ctx.db,
        actor=ctx.user.email,
        action="brief_generated",
        entity_type="alert",
        entity_id=alert.alert_id,
    )
    ctx.db.commit()
    return _pdf(render(pdf), f"brief_{alert.alert_id.replace('/', '_')}.pdf")


@router.get("/cases/{case_id}.pdf")
def case_brief(case_id: int, ctx: Context = Depends(reviewer)) -> Response:
    case = ctx.db.execute(
        ctx.scope.apply(select(models.Case).where(models.Case.id == case_id), models.Case)
    ).scalar_one_or_none()
    if case is None:
        raise not_found("case")
    alert_ids = [link.alert_id for link in case.alerts]
    alerts = (
        ctx.db.execute(
            ctx.scope.apply(
                select(models.Alert).where(models.Alert.alert_id.in_(alert_ids)), models.Alert
            )
        )
        .scalars()
        .all()
    )
    pdf = Brief(
        f"Case {case.id}: {case.title}",
        f"{case.kind.replace('_', ' ')} | status {case.status} | owner {case.owner.email}",
    )
    pdf.title_block()
    pdf.section("Summary")
    pdf.bullets([case.summary or "No summary written."])
    pdf.fields(
        [("Linked alerts", len(alerts)), ("Combined value", inr(sum(a.amount for a in alerts)))]
    )
    pdf.section("Linked alerts")
    pdf.table(
        ["Alert", "Type", "Severity", "Status", "Value"],
        [
            [a.alert_id, a.alert_type.replace("_", " "), a.severity, a.status, inr(a.amount)]
            for a in alerts
        ],
        [60, 36, 22, 30, 30],
    )
    for a in alerts[:10]:
        pdf.section(f"Evidence: {a.alert_id}")
        pdf.bullets((a.reasons_en or [])[:4])
    if case.notes:
        pdf.section("Case notes")
        pdf.bullets([f"{n.created_at:%Y-%m-%d} {n.author.email}: {n.body}" for n in case.notes])
    trail = audit.trail_for(ctx.db, "case", str(case.id))
    for a in alerts:
        trail += audit.trail_for(ctx.db, "alert", a.alert_id)
    trail.sort(key=lambda e: e["seq"])
    pdf.chain(trail, audit.verify(ctx.db).as_dict())
    audit.append(
        ctx.db,
        actor=ctx.user.email,
        action="brief_generated",
        entity_type="case",
        entity_id=str(case.id),
    )
    ctx.db.commit()
    return _pdf(render(pdf), f"case_{case.id}_brief.pdf")


@router.get("/district.pdf")
def district_brief(
    district: str = Query(min_length=2), ctx: Context = Depends(reviewer)
) -> Response:
    name = district.upper()
    rows = [r for r in queries.group_risk(ctx.db, ctx.scope, "district") if r["key"] == name]
    if not rows:
        raise not_found("district")
    r = rows[0]
    top = (
        ctx.db.execute(
            ctx.scope.apply(select(models.Work), models.Work)
            .where(models.Work.district == name)
            .order_by(models.Work.risk_score.desc())
            .limit(15)
        )
        .scalars()
        .all()
    )
    pdf = Brief(f"District brief: {name}", f"{r['state']} | {ctx.scope.label}")
    pdf.title_block()
    pdf.section("Portfolio")
    pdf.fields(
        [
            ("Works", r["works"]),
            ("Sanctioned", inr(r["sanctioned"])),
            ("Disbursed", f"{inr(r['disbursed'])} ({r['utilisation']:.0%} utilisation)"),
            ("Completion rate", f"{r['completion_rate']:.0%}"),
            ("High or Critical", f"{r['high_or_critical']} works, {inr(r['money_at_risk'])}"),
        ]
    )
    pdf.section("Highest-risk works")
    pdf.table(
        ["Work id", "Type", "Amount", "Band", "Top reason"],
        [
            [
                w.work_id,
                w.work_type,
                inr(w.sanction_amount),
                w.band,
                work_summary(w)["top_reason_en"] or "",
            ]
            for w in top
        ],
        [48, 34, 26, 16, 54],
    )
    pdf.chain([], audit.verify(ctx.db).as_dict())
    return _pdf(render(pdf), f"district_{name.replace(' ', '_')}.pdf")
