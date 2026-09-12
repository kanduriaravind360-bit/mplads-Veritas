"""Vendor network: force graph, concentration (HHI, win share), Benford first digits.

Honest limits, stated in every response:

* The extract identifies vendors only by a free-text name. There is no PAN,
  GSTIN, address or bank account, so "shared identifier" edges can only be NAME
  SIMILARITY. Two similar names may be one firm or two unrelated firms.
* Benford's law is weak evidence on public-works amounts, which are often
  rounded to a lakh by design. The response reports the round-amount share and a
  version excluding them.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from fastapi import APIRouter, Depends, Query
from rapidfuzz import fuzz
from sqlalchemy import case, func, select

from backend.app import models, queries
from backend.app.deps import Context, context
from backend.app.redact import pseudonym
from backend.app.settings import get_settings

router = APIRouter(prefix="/network", tags=["network"])


def _node_id(name: str) -> str:
    """Opaque node id, so a pseudonymised graph does not carry real names in its ids."""
    return "v:" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]


def _label(name: str | None) -> str | None:
    return pseudonym("vendor", name) if get_settings().presentation_mode else name


@router.get("/vendors")
def vendor_graph(
    ctx: Context = Depends(context),
    limit: int = Query(default=60, ge=5, le=250),
    similarity: int = Query(default=92, ge=80, le=100),
) -> dict[str, Any]:
    w = queries.scoped_works(ctx.scope, models.Work.vendor_name.is_not(None))
    at_risk = func.sum(case((w.c.band.in_(queries.AT_RISK_BANDS), 1), else_=0))
    vendor_rows = ctx.db.execute(
        select(
            w.c.vendor_name,
            func.count(),
            func.coalesce(func.sum(w.c.sanction_amount), 0.0),
            func.avg(w.c.risk_score),
            at_risk,
        )
        .select_from(w)
        .group_by(w.c.vendor_name)
        .order_by(func.sum(w.c.sanction_amount).desc())
        .limit(limit)
    ).all()
    names = [r[0] for r in vendor_rows]
    edges_rows = ctx.db.execute(
        select(
            w.c.vendor_name,
            w.c.district,
            func.count(),
            func.coalesce(func.sum(w.c.sanction_amount), 0.0),
        )
        .select_from(w)
        .where(w.c.vendor_name.in_(names))
        .group_by(w.c.vendor_name, w.c.district)
    ).all()

    nodes: list[dict[str, Any]] = []
    for name, works, value, mean_risk, high in vendor_rows:
        nodes.append(
            {
                "id": _node_id(name),
                "type": "vendor",
                "label": _label(name),
                "works": int(works),
                "value": float(value),
                "mean_risk": float(mean_risk or 0.0),
                "high_or_critical": int(high or 0),
            }
        )
    districts: dict[str, float] = {}
    edges: list[dict[str, Any]] = []
    for name, district, works, value in edges_rows:
        districts[district] = districts.get(district, 0.0) + float(value)
        edges.append(
            {
                "source": _node_id(name),
                "target": f"d:{district}",
                "type": "works_in",
                "works": int(works),
                "value": float(value),
            }
        )
    nodes += [
        {"id": f"d:{d}", "type": "district", "label": d, "value": v} for d, v in districts.items()
    ]

    # Similar names among the shown vendors: a lead to check, not an identity match.
    similar = 0
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            score = fuzz.token_sort_ratio(a, b)
            if similarity <= score < 100:
                edges.append(
                    {
                        "source": _node_id(a),
                        "target": _node_id(b),
                        "type": "similar_name",
                        "similarity": score / 100.0,
                    }
                )
                similar += 1

    return {
        "nodes": nodes,
        "edges": edges,
        "similar_name_edges": similar,
        "note": (
            "Vendors are identified only by name in the eSAKSHI extract (no PAN, GSTIN, "
            "address or bank). Highlighted edges are near-identical NAMES, which may be "
            "one firm or two unrelated firms; they are leads to check, not matches."
        ),
    }


@router.get("/concentration")
def concentration(
    ctx: Context = Depends(context),
    min_works: int = Query(default=20, ge=1),
    limit: int = Query(default=40, ge=5, le=800),
) -> dict[str, Any]:
    """Per district: Herfindahl-Hirschman index of vendor value shares, and the top vendor's share."""
    w = queries.scoped_works(ctx.scope, models.Work.vendor_name.is_not(None))
    rows = ctx.db.execute(
        select(
            w.c.district,
            w.c.state,
            w.c.vendor_name,
            func.count(),
            func.coalesce(func.sum(w.c.sanction_amount), 0.0),
        )
        .select_from(w)
        .group_by(w.c.district, w.c.state, w.c.vendor_name)
    ).all()
    by_district: dict[str, dict[str, Any]] = {}
    for district, state, vendor, works, value in rows:
        entry = by_district.setdefault(
            district, {"state": state, "works": 0, "value": 0.0, "vendors": []}
        )
        entry["works"] += int(works)
        entry["value"] += float(value)
        entry["vendors"].append((vendor, float(value), int(works)))

    out = []
    for district, entry in by_district.items():
        if entry["works"] < min_works or entry["value"] <= 0:
            continue
        shares = sorted(
            ((v / entry["value"], name, n) for name, v, n in entry["vendors"]), reverse=True
        )
        hhi = sum(s * s for s, _, _ in shares) * 10_000
        top_share, top_name, top_works = shares[0]
        out.append(
            {
                "district": district,
                "state": entry["state"],
                "works": entry["works"],
                "value": entry["value"],
                "vendors": len(shares),
                "hhi": round(hhi, 1),
                "concentration": "high" if hhi >= 2500 else "moderate" if hhi >= 1500 else "low",
                "top_vendor": _label(top_name),
                "top_vendor_share": top_share,
                "top_vendor_works": top_works,
            }
        )
    out.sort(key=lambda r: r["hhi"], reverse=True)
    return {
        "rows": out[:limit],
        "note": "HHI on vendor value share: above 2,500 is highly concentrated (US DoJ convention). Works without a recorded vendor are excluded.",
    }


_BENFORD = {d: math.log10(1 + 1 / d) for d in range(1, 10)}


def _first_digit_profile(amounts: list[float]) -> dict[str, Any]:
    counts = dict.fromkeys(range(1, 10), 0)
    for amount in amounts:
        if amount >= 10:
            counts[int(str(int(amount))[0])] += 1
    total = sum(counts.values())
    if total == 0:
        return {"n": 0, "digits": [], "mad": None, "conformity": None}
    digits = [
        {"digit": d, "observed": counts[d] / total, "expected": _BENFORD[d], "count": counts[d]}
        for d in range(1, 10)
    ]
    mad = sum(abs(x["observed"] - x["expected"]) for x in digits) / 9
    # Nigrini's first-digit MAD thresholds.
    conformity = (
        "close"
        if mad < 0.006
        else "acceptable"
        if mad < 0.012
        else "marginal"
        if mad < 0.015
        else "nonconformity"
    )
    return {"n": total, "digits": digits, "mad": round(mad, 5), "conformity": conformity}


@router.get("/benford")
def benford(ctx: Context = Depends(context), district: str | None = None) -> dict[str, Any]:
    conditions = [models.Work.district == district.upper()] if district else []
    w = queries.scoped_works(ctx.scope, *conditions)
    amounts = [
        float(a) for (a,) in ctx.db.execute(select(w.c.sanction_amount).select_from(w)).all() if a
    ]
    unit = float(get_settings().api.get("benford_round_unit", 100_000))
    round_share = sum(1 for a in amounts if a % unit == 0) / len(amounts) if amounts else 0.0
    return {
        "all_amounts": _first_digit_profile(amounts),
        "excluding_round_lakh": _first_digit_profile([a for a in amounts if a % unit != 0]),
        "round_lakh_share": round_share,
        "note": (
            "Weak evidence on its own: public-works amounts are often estimates rounded "
            "to a lakh, which distorts first digits without any wrongdoing. Compare the "
            "version excluding round amounts."
        ),
    }
