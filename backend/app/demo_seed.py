"""Guarantee the demo path: the three scenarios the demo script walks through.

    python -m backend.app.demo_seed               # ensure the scenarios, print a checklist
    python -m backend.app.demo_seed --reset       # also put the live-demo alerts back to Open

1. A split-work case in Madurai, opened with a summary built from the group's own
   measurements, so the Cases page and its PDF brief have a worked example.
2. The Bhatpara CCTV alerts, which a reviewer marks as a false positive live on
   stage. ``--reset`` returns them to Open, on the audit trail, so the walkthrough
   works every time.
3. A high-delay district (Bokaro) for the early-warning story.

Every scenario is looked up in the loaded data; nothing is invented. If one is
missing the seed exits non-zero rather than letting a demo drift.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.app import audit, models
from backend.app.db import create_all, session_scope
from backend.app.settings import get_settings

ACTOR = "demo-seed@system"


class DemoDataMissingError(RuntimeError):
    pass


def _ministry_user(db: Session) -> models.User:
    user = db.execute(select(models.User).where(models.User.role == "MINISTRY")).scalars().first()
    if user is None:
        raise DemoDataMissingError("no ministry user: run python -m backend.app.loader first")
    return user


def ensure_split_case(db: Session) -> dict[str, Any]:
    cfg = get_settings().api["demo"]["split_case"]
    district, work_type = str(cfg["district"]).upper(), str(cfg["work_type"])
    group = (
        db.execute(
            select(models.SplitGroup)
            .where(
                models.SplitGroup.ida.ilike(f"{district}(%"),
                models.SplitGroup.work_type == work_type,
            )
            .order_by(models.SplitGroup.split_score.desc(), models.SplitGroup.total_amount.desc())
        )
        .scalars()
        .first()
    )
    if group is None or db.get(models.Alert, group.split_group_id) is None:
        raise DemoDataMissingError(f"no {work_type} split group with an alert in {district}")

    title = f"Possible split work: {work_type} in {district}"
    case = db.execute(select(models.Case).where(models.Case.title == title)).scalars().first()
    created = False
    if case is None:
        detail = group.detail or {}
        summary = (
            f"{group.n_works} works of one type from one implementing agency, sanctioned between "
            f"{detail.get('first_sanction')} and {detail.get('last_sanction')}, "
            f"{float(detail.get('share_just_below_round', 0)):.0%} of them just below a round amount. "
            f"Together they come to {float(detail.get('total_vs_p90', 0)):.1f} times the "
            "90th-percentile cost of a single such work. Check whether they are parts of one "
            "project, and which authority should have sanctioned the combined value."
        )
        owner = _ministry_user(db)
        case = models.Case(
            title=title,
            kind="split_group",
            owner_id=owner.id,
            state=group.state,
            ida=group.ida,
            mp_code=None,
            summary=summary,
        )
        db.add(case)
        db.flush()
        db.add(models.CaseAlert(case_id=case.id, alert_id=group.split_group_id))
        db.add(
            models.CaseNote(
                case_id=case.id,
                author_id=owner.id,
                body="Requested the estimates and sanction orders for every work in the group "
                "from the implementing agency.",
            )
        )
        audit.append(
            db,
            actor=ACTOR,
            action="case_create",
            entity_type="case",
            entity_id=str(case.id),
            payload={"title": title, "kind": "split_group", "alert_ids": [group.split_group_id]},
        )
        created = True
    return {
        "case_id": case.id,
        "created": created,
        "split_group": group.split_group_id,
        "works": group.n_works,
        "total_amount": group.total_amount,
        "url": f"/cases?case={case.id}",
    }


def ensure_false_positive_path(db: Session, reset: bool) -> list[dict[str, Any]]:
    out = []
    for alert_id in get_settings().api["demo"]["false_positive_alerts"]:
        alert = db.get(models.Alert, alert_id)
        if alert is None:
            raise DemoDataMissingError(f"demo alert {alert_id} is not loaded")
        previous = alert.status
        if reset and alert.status != "Open":
            alert.status = "Open"
            audit.append(
                db,
                actor=ACTOR,
                action="demo_reset",
                entity_type="alert",
                entity_id=alert.alert_id,
                payload={"from": previous, "to": "Open"},
            )
        out.append(
            {
                "alert_id": alert.alert_id,
                "severity": alert.severity,
                "status": alert.status,
                "was": previous,
                "url": f"/alerts?id={alert.alert_id}",
            }
        )
    return out


def high_delay_district(db: Session) -> dict[str, Any]:
    name = str(get_settings().api["demo"]["high_delay_district"]).upper()
    threshold = float(get_settings().api["predictions"]["high_delay_risk"])
    open_works, mean_delay, high = db.execute(
        select(
            func.count(),
            func.avg(models.Work.delay_risk),
            func.sum(case((models.Work.delay_risk >= threshold, 1), else_=0)),
        ).where(models.Work.district == name, models.Work.is_open.is_(True))
    ).one()
    if not open_works:
        raise DemoDataMissingError(f"no open works in {name}")
    return {
        "district": name,
        "open_works": int(open_works),
        "mean_delay_risk": round(float(mean_delay or 0.0), 3),
        "high_delay_risk_works": int(high or 0),
        "url": f"/alerts?district={name}",
    }


def run(db: Session, reset: bool = False) -> dict[str, Any]:
    return {
        "split_case": ensure_split_case(db),
        "false_positive_walkthrough": ensure_false_positive_path(db, reset),
        "high_delay_district": high_delay_district(db),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ensure the demo scenarios exist.")
    parser.add_argument("--reset", action="store_true", help="put live-demo alerts back to Open")
    args = parser.parse_args(argv)
    create_all()
    try:
        with session_scope() as db:
            checklist = run(db, reset=args.reset)
    except DemoDataMissingError as missing:
        print(f"demo data missing: {missing}", file=sys.stderr)
        return 2
    print(json.dumps(checklist, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
