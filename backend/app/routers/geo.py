"""Map metrics per district and state, keyed by normalised district name."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.app import queries
from backend.app.deps import Context, context
from backend.app.geo import map_key

router = APIRouter(prefix="/geo", tags=["geo"])


@router.get("/districts")
def districts(
    ctx: Context = Depends(context),
    state: str | None = None,
    metric: str = Query(default="risk", pattern="^(risk|utilisation|delay|money_at_risk)$"),
) -> dict[str, Any]:
    rows = queries.group_risk(ctx.db, ctx.scope, "district")
    if state:
        rows = [r for r in rows if r["state"] == state]
    value_of = {
        "risk": lambda r: r["mean_risk"],
        "utilisation": lambda r: r["utilisation"],
        "delay": lambda r: r["mean_delay_risk"],
        "money_at_risk": lambda r: r["money_at_risk"],
    }[metric]
    return {
        "metric": metric,
        "rows": [
            {
                **r,
                "district": r["key"],
                "map_key": map_key(r["state"], r["key"]),
                "value": value_of(r),
            }
            for r in rows
        ],
        "note": (
            "Districts are taken from the implementing agency (IDA) name. A district "
            "with fewer than 20 works is marked low_volume and should not be ranked."
        ),
    }


@router.get("/states")
def states(ctx: Context = Depends(context)) -> dict[str, Any]:
    rows = queries.group_risk(ctx.db, ctx.scope, "state")
    return {"rows": [{**r, "state": r["key"]} for r in rows]}
