"""Citizen view: public, read-only, no login.

What it shows: per district, how many works, how much was sanctioned and spent,
how many are complete, and what kinds of asset they are.

What it never shows: any per-work risk score or flag, any MP or vendor name, or
any district too small to describe without singling out individual works.
Risk scores exist for official review; publishing them per work against named
people would turn a statistical hint into a public accusation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.app import models, queries
from backend.app.db import get_db
from backend.app.settings import get_settings

router = APIRouter(prefix="/public", tags=["public"])

NOTE = (
    "Risk scores are produced for official review and are not published per work. "
    "This page shows what was sanctioned, spent and completed."
)


def _min_works() -> int:
    return int(get_settings().api["public"]["min_works_to_show_district"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(models.Work.sanction_amount), 0.0),
            func.coalesce(func.sum(models.Work.total_fund_disbursed), 0.0),
            func.sum(case((models.Work.is_open.is_(False), 1), else_=0)),
            func.count(func.distinct(models.Work.district)),
            func.count(func.distinct(models.Work.state)),
        ).where(models.Work.source != "ingest")
    ).one()
    works = int(row[0] or 0)
    return {
        "works": works,
        "sanctioned": float(row[1]),
        "disbursed": float(row[2]),
        "completed": int(row[3] or 0),
        "completion_rate": (int(row[3] or 0) / works) if works else 0.0,
        "districts": int(row[4] or 0),
        "states": int(row[5] or 0),
        "note": NOTE,
    }


@router.get("/districts")
def search_districts(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, max_length=80),
    state: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Districts, one per implementing agency.

    The ``state`` column is the recommending MP's state, and a Rajya Sabha member
    can fund works in another state, so grouping by (district, state) listed
    Agra under four states. The implementing agency is the district's own office,
    so it is the right unit; its state is where most of its works sit.
    """
    stmt = (
        select(models.Work.ida, models.Work.district, models.Work.state, func.count())
        .where(models.Work.source != "ingest", models.Work.district != "")
        .group_by(models.Work.ida, models.Work.district, models.Work.state)
    )
    if q:
        stmt = stmt.where(models.Work.district.ilike(f"%{q.strip()}%"))
    agencies: dict[str, dict[str, Any]] = {}
    for ida, name, st, n in db.execute(stmt).all():
        entry = agencies.setdefault(ida, {"ida": ida, "district": name, "works": 0, "_states": {}})
        entry["works"] += int(n)
        entry["_states"][st] = entry["_states"].get(st, 0) + int(n)
    rows = []
    for entry in agencies.values():
        entry["state"] = max(entry.pop("_states").items(), key=lambda kv: kv[1])[0]
        if entry["works"] >= _min_works() and (not state or entry["state"] == state):
            rows.append(entry)
    rows.sort(key=lambda r: (r["district"], r["state"] or ""))
    states = [
        s
        for (s,) in db.execute(
            select(models.Work.state).distinct().order_by(models.Work.state)
        ).all()
        if s
    ]
    return {"districts": rows[:limit], "states": states, "note": NOTE}


@router.get("/districts/{district}")
def district(
    district: str,
    db: Session = Depends(get_db),
    ida: str | None = Query(default=None, max_length=300),
) -> dict[str, Any]:
    name = district.strip().upper()
    base = [models.Work.district == name, models.Work.source != "ingest"]
    # District names repeat across states; the implementing agency is unique.
    if ida:
        base.append(models.Work.ida == ida)
    row = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(models.Work.sanction_amount), 0.0),
            func.coalesce(func.sum(models.Work.total_fund_disbursed), 0.0),
            func.sum(case((models.Work.is_open.is_(False), 1), else_=0)),
            func.max(models.Work.state),
        ).where(*base)
    ).one()
    works = int(row[0] or 0)
    if works < _min_works():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "district not found or too small to publish")
    majority_state = db.execute(
        select(models.Work.state)
        .where(*base)
        .group_by(models.Work.state)
        .order_by(func.count().desc())
        .limit(1)
    ).scalar_one_or_none()

    types = db.execute(
        select(
            models.Work.work_type,
            func.count(),
            func.coalesce(func.sum(models.Work.sanction_amount), 0.0),
        )
        .where(*base)
        .group_by(models.Work.work_type)
        .order_by(func.count().desc())
        .limit(12)
    ).all()
    statuses = db.execute(
        select(models.Work.work_status, func.count()).where(*base).group_by(models.Work.work_status)
    ).all()
    month = queries.month_of(db, models.Work.sanction_date)
    trend = db.execute(
        select(month, func.count(), func.coalesce(func.sum(models.Work.sanction_amount), 0.0))
        .where(*base, models.Work.sanction_date.is_not(None))
        .group_by(month)
        .order_by(month)
    ).all()
    return {
        "district": name,
        "state": majority_state,
        "works": works,
        "sanctioned": float(row[1]),
        "disbursed": float(row[2]),
        "completed": int(row[3] or 0),
        "completion_rate": int(row[3] or 0) / works,
        "asset_types": [
            {"work_type": t, "works": int(n), "sanctioned": float(a)} for t, n, a in types
        ],
        "status_mix": [{"status": s or "Unknown", "works": int(n)} for s, n in statuses],
        "monthly": [
            {"month": m, "works": int(n), "sanctioned": float(a)} for m, n, a in trend if m
        ],
        "note": NOTE,
    }
