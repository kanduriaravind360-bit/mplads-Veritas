"""Duplicate finder: ranked pairs, side-by-side comparison, reviewer decisions."""

from __future__ import annotations

import difflib
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from backend.app import audit, models
from backend.app.deps import Context, Page, context, page, reviewer
from backend.app.redact import enabled as presentation_mode
from backend.app.redact import redact_record
from backend.app.schemas import PairDecisionRequest
from backend.app.scoping import not_found
from backend.app.serialize import work_detail, work_summary
from ml.config import load_config

router = APIRouter(prefix="/duplicates", tags=["duplicates"])


def _scoped_pairs(ctx: Context) -> Any:
    """Pairs where BOTH works are inside the caller's scope."""
    a = aliased(models.Work)
    b = aliased(models.Work)
    stmt = (
        select(models.DuplicatePair)
        .join(a, a.work_id == models.DuplicatePair.work_id_a)
        .join(b, b.work_id == models.DuplicatePair.work_id_b)
    )
    stmt = ctx.scope.apply(stmt, a)
    return ctx.scope.apply(stmt, b)


def _with_works(fields: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Attach both works. In presentation mode the shared words are limited to words
    still visible in both masked descriptions, so a masked name cannot leak here."""
    out = {**fields, "work_a": a, "work_b": b}
    words = out.get("shared_location_words")
    if presentation_mode() and words:
        visible_a = set((a.get("work_description") or "").lower().split())
        visible_b = set((b.get("work_description") or "").lower().split())
        out["shared_location_words"] = " ".join(
            w for w in str(words).split() if w.lower() in visible_a and w.lower() in visible_b
        )
    return out


@router.get("")
def list_pairs(
    ctx: Context = Depends(context),
    min_score: float = Query(default=0.0, ge=0.0, le=1.0),
    decision: str | None = Query(default=None, pattern="^(duplicate|not_duplicate|undecided)$"),
    district: str | None = None,
    pg: Page = Depends(page),
) -> dict[str, Any]:
    stmt = _scoped_pairs(ctx).where(models.DuplicatePair.pair_score >= min_score)
    if decision == "undecided":
        stmt = stmt.where(models.DuplicatePair.decision.is_(None))
    elif decision:
        stmt = stmt.where(models.DuplicatePair.decision == decision)
    if district:
        stmt = stmt.where(models.DuplicatePair.ida.ilike(f"{district.upper()}%"))
    total = ctx.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    pairs = (
        ctx.db.execute(
            stmt.order_by(models.DuplicatePair.pair_score.desc()).limit(pg.limit).offset(pg.offset)
        )
        .scalars()
        .all()
    )
    ids = {p.work_id_a for p in pairs} | {p.work_id_b for p in pairs}
    works = {
        w.work_id: w
        for w in ctx.db.execute(select(models.Work).where(models.Work.work_id.in_(ids))).scalars()
    }
    items = [
        _with_works(
            _pair_fields(p), work_summary(works[p.work_id_a]), work_summary(works[p.work_id_b])
        )
        for p in pairs
        if p.work_id_a in works and p.work_id_b in works
    ]
    return {"total": total, "limit": pg.limit, "offset": pg.offset, "items": items}


def _pair_fields(pair: models.DuplicatePair) -> dict[str, Any]:
    # The same weights the pipeline scored with, read from its config.
    configured = load_config("ml")["duplicates"]["score_weights"]
    weights = {
        "cosine": float(configured["cosine"]),
        "token_set": float(configured["fuzzy"]),
        "location_overlap": float(configured["location"]),
        "amount_similarity": float(configured["amount"]),
    }
    return {
        "pair_id": pair.id,
        "pair_score": pair.pair_score,
        "dup_group_id": pair.dup_group_id,
        "decision": pair.decision,
        "days_apart": pair.days_apart,
        "is_standard_item": pair.is_standard_item,
        "shared_location_words": pair.shared_location_words,
        "breakdown": [
            {
                "component": "Meaning (embedding cosine)",
                "key": "cosine",
                "value": pair.cosine,
                "weight": weights["cosine"],
            },
            {
                "component": "Wording (fuzzy token set)",
                "key": "token_set",
                "value": pair.token_set / 100.0,
                "weight": weights["token_set"],
            },
            {
                "component": "Place names in common",
                "key": "location_overlap",
                "value": pair.location_overlap,
                "weight": weights["location_overlap"],
            },
            {
                "component": "Amount similarity",
                "key": "amount_similarity",
                "value": pair.amount_similarity,
                "weight": weights["amount_similarity"],
            },
        ],
    }


def _word_diff(a: str, b: str) -> list[dict[str, str]]:
    """Word-level diff: equal / removed (only in A) / added (only in B)."""
    left, right = (a or "").split(), (b or "").split()
    out: list[dict[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
        a=left, b=right, autojunk=False
    ).get_opcodes():
        if op == "equal":
            out.append({"op": "equal", "text": " ".join(left[i1:i2])})
        else:
            if i2 > i1:
                out.append({"op": "removed", "text": " ".join(left[i1:i2])})
            if j2 > j1:
                out.append({"op": "added", "text": " ".join(right[j1:j2])})
    return out


def _get_pair(ctx: Context, pair_id: int) -> models.DuplicatePair:
    pair = ctx.db.execute(
        _scoped_pairs(ctx).where(models.DuplicatePair.id == pair_id)
    ).scalar_one_or_none()
    if pair is None:
        raise not_found("duplicate pair")
    return pair


@router.get("/{pair_id}")
def get_pair(pair_id: int, ctx: Context = Depends(context)) -> dict[str, Any]:
    pair = _get_pair(ctx, pair_id)
    a = ctx.db.get(models.Work, pair.work_id_a)
    b = ctx.db.get(models.Work, pair.work_id_b)
    assert a is not None and b is not None
    detail_a, detail_b = work_detail(a), work_detail(b)
    return redact_record(
        {
            **_with_works(_pair_fields(pair), detail_a, detail_b),
            "diff": _word_diff(
                detail_a.get("work_description") or "", detail_b.get("work_description") or ""
            ),
            "audit": audit.trail_for(ctx.db, "duplicate_pair", str(pair.id)),
        }
    )


@router.post("/{pair_id}/decision")
def decide(
    pair_id: int, body: PairDecisionRequest, ctx: Context = Depends(reviewer)
) -> dict[str, Any]:
    pair = _get_pair(ctx, pair_id)
    previous = pair.decision
    pair.decision = body.decision
    audit.append(
        ctx.db,
        actor=ctx.user.email,
        action="duplicate_decision",
        entity_type="duplicate_pair",
        entity_id=str(pair.id),
        payload={
            "from": previous,
            "to": body.decision,
            "work_ids": [pair.work_id_a, pair.work_id_b],
            "note": body.note or "",
        },
    )
    # The decision is also reviewer feedback on the group alert, if there is one.
    if pair.dup_group_id:
        alert = ctx.db.get(models.Alert, pair.dup_group_id)
        if alert is not None:
            ctx.db.add(
                models.Feedback(
                    alert_id=alert.alert_id,
                    work_id=pair.work_id_a,
                    reviewer_id=ctx.user.id,
                    verdict="confirmed" if body.decision == "duplicate" else "not_duplicate",
                    note=body.note,
                    signals={"duplicate": pair.pair_score},
                )
            )
    ctx.db.commit()
    return {"pair_id": pair.id, "decision": pair.decision}
