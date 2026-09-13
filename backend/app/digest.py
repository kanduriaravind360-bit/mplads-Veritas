"""Weekly digest: one self-contained HTML page per scope, written to ``outbox/``.

    python -m backend.app.digest                  # the ministry, all India
    python -m backend.app.digest --state "Uttar Pradesh"

Nothing is emailed. The page is a file for a reviewer to open or forward, and the
scheduler writes the ministry's copy every Monday morning. It carries the same
framing and caveats as the dashboard, and names no MP or vendor.
"""

from __future__ import annotations

import argparse
import html
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app import metrics_doc, models, queries
from backend.app.db import session_scope
from backend.app.routers.overview import what_changed
from backend.app.scoping import MINISTRY, STATE, Scope
from backend.app.settings import PROJECT_ROOT

OUTBOX = PROJECT_ROOT / "outbox"


def _inr(amount: float) -> str:
    if amount >= 1e7:
        return f"&#8377;{amount / 1e7:,.2f} crore"
    if amount >= 1e5:
        return f"&#8377;{amount / 1e5:,.2f} lakh"
    return f"&#8377;{amount:,.0f}"


class _Ctx:
    """The shape ``what_changed`` expects, without a request."""

    def __init__(self, db: Session, scope: Scope) -> None:
        self.db = db
        self.scope = scope


def build(db: Session, scope: Scope) -> dict[str, Any]:
    totals = queries.totals(db, scope)
    alerts = scope.apply(
        select(models.Alert).where(models.Alert.is_active.is_(True)), models.Alert
    ).subquery()
    by_status = dict(
        db.execute(select(alerts.c.status, func.count()).group_by(alerts.c.status)).all()
    )
    by_severity = dict(
        db.execute(select(alerts.c.severity, func.count()).group_by(alerts.c.severity)).all()
    )
    districts = [r for r in queries.group_risk(db, scope, "district") if not r["low_volume"]][:10]
    changed = what_changed(_Ctx(db, scope))  # type: ignore[arg-type]
    metrics = metrics_doc.metrics(db)
    return {
        "scope": scope.label,
        "totals": totals,
        "by_status": by_status,
        "by_severity": by_severity,
        "districts": districts,
        "changed": changed,
        "weak_spot": metrics.get("injection_test", {}).get("weakest_detector_plain_language"),
    }


def render(data: dict[str, Any]) -> str:
    t = data["totals"]
    c = data["changed"]
    esc = html.escape
    rows = "".join(
        f"<tr><td>{esc(r['key'])}<br><small>{esc(r['state'] or '')}</small></td>"
        f"<td class=n>{_inr(r['money_at_risk'])}<br><small>of {_inr(r['sanctioned'])}</small></td>"
        f"<td class=n>{r['high_or_critical']:,} of {r['works']:,}</td></tr>"
        for r in data["districts"]
    )
    statuses = " &middot; ".join(f"{esc(k)} {v:,}" for k, v in sorted(data["by_status"].items()))
    severities = " &middot; ".join(
        f"{esc(k)} {data['by_severity'].get(k, 0):,}" for k in ("Critical", "High", "Medium")
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>MPLADS Sentinel weekly digest</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;background:#f4f6fa;color:#0b1f3a;margin:0;padding:32px}}
main{{max-width:760px;margin:auto;background:#fff;border-radius:12px;padding:32px;border:1px solid #dee4ed}}
h1{{font-size:24px;margin:0}} h2{{font-size:16px;margin:28px 0 8px}}
.eyebrow{{color:#4a5b73;font-size:12px;text-transform:uppercase;letter-spacing:.08em}}
.kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:20px}}
.kpi{{border:1px solid #dee4ed;border-radius:8px;padding:12px}} .kpi b{{display:block;font-size:20px}}
table{{width:100%;border-collapse:collapse}} td,th{{padding:8px;border-bottom:1px solid #eef1f6;text-align:left;vertical-align:top}}
.n{{text-align:right;font-variant-numeric:tabular-nums}} small{{color:#4a5b73}}
.note{{background:#eef4ff;border-radius:8px;padding:12px;margin-top:20px;font-size:13px}}
</style></head><body><main>
<div class=eyebrow>MPLADS Sentinel &middot; weekly digest &middot; {esc(data["scope"])}</div>
<h1>Week to {esc(str(c.get("data_cutoff", "")))}</h1>
<div class=kpis>
<div class=kpi><small>Works</small><b>{t["works"]:,}</b></div>
<div class=kpi><small>Sanctioned</small><b>{_inr(t["sanctioned"])}</b></div>
<div class=kpi><small>Money at risk</small><b>{_inr(t["money_at_risk"])}</b><small>{t["money_at_risk_share"]:.1%} of sanctioned</small></div>
</div>
<h2>What changed</h2>
<p>{c.get("works_sanctioned", 0):,} works sanctioned ({_inr(c.get("amount_sanctioned", 0.0))}),
{c.get("works_completed", 0):,} completed, and {c.get("new_high_or_critical", 0):,} new works in the High
or Critical bands, in {esc(str(c.get("window", "")))}.</p>
<h2>Open alerts</h2><p>{severities}<br><small>By status: {statuses}</small></p>
<h2>Districts with the most money at risk</h2>
<table><tr><th>District</th><th class=n>Money at risk</th><th class=n>High or Critical</th></tr>{rows}</table>
<div class=note><b>Risk indicators for review. Nothing here is a finding of fraud.</b>
{esc(data.get("weak_spot") or "")} Districts with fewer than 20 works are left out of the table.
{esc(c.get("note", ""))}</div>
</main></body></html>"""


def write(db: Session, scope: Scope, today: date | None = None) -> Path:
    today = today or date.today()
    OUTBOX.mkdir(parents=True, exist_ok=True)
    slug = scope.label.lower().replace(" ", "-").replace(":", "")
    path = OUTBOX / f"digest-{today.isoformat()}-{slug}.html"
    path.write_text(render(build(db, scope)), encoding="utf-8")
    return path


def weekly_job() -> str:
    with session_scope() as db:
        return str(write(db, Scope(role=MINISTRY)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a weekly digest to outbox/.")
    parser.add_argument("--state", help="a state's digest instead of the national one")
    args = parser.parse_args(argv)
    scope = Scope(role=STATE, state=args.state) if args.state else Scope(role=MINISTRY)
    with session_scope() as db:
        path = write(db, scope)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
