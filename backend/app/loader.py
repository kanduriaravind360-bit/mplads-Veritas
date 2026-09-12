"""Load the ML pipeline's outputs into the application database.

    python -m backend.app.loader            # load or refresh
    python -m backend.app.loader --reset    # drop everything, including workflow

A refresh rebuilds pipeline-derived tables (works, scores, duplicate pairs, split
groups, metrics) and UPSERTS alerts: an alert that still exists keeps its
status, assignee, comments and audit history; one that no longer fires is
marked inactive rather than deleted, because human work was attached to it.

Group alerts get ids derived from their member works, not from the pipeline's
row counter. The pipeline numbers groups afresh on every run, so "SPL00001"
today can be a different group tomorrow, and a reviewer's verdict would
silently move to the wrong works.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.db import Base, get_engine, session_scope
from backend.app.geo import district_from_ida, mp_code_from_work_id
from backend.app.settings import PROJECT_ROOT

PROCESSED = PROJECT_ROOT / "data" / "processed"
METRICS = PROJECT_ROOT / "models" / "metrics.json"

_DETAIL_COLUMNS = (
    "rule_sanction_delay",
    "rule_stuck_work",
    "rule_cost_outlier",
    "rule_fast_completion",
    "rule_round_amount",
    "rule_vendor_concentration",
    "rule_payment_stuck",
    "severe_fast_completion",
    "severe_stuck_work",
    "severe_payment_stuck",
    "rule_reasons",
    "peer_group",
    "peer_n",
    "amount_vs_peer_median",
    "cost_robust_z",
    "cost_pct_in_type",
    "cost_residual_z",
    "expected_cost_signal",
    "state_peer_scope",
    "state_cost_z",
    "state_cost_signal",
    "state_channel_would_fire",
    "quantity",
    "unit_rate",
    "disbursed_ratio",
    "stage_ordinal",
    "vendor_total_works",
    "vendor_works_in_ida",
    "vendor_share_of_ida",
    "vendor_n_mps",
    "vendor_n_states",
    "ida_works",
    "ida_completion_rate",
    "ida_vendor_hhi",
    "mp_completion_rate",
    "days_since_sanction_open",
    "duration_pct_in_type",
    "days_to_sanction_z",
    "has_date_error",
)
_JSON_LIST_COLUMNS = ("unsup_reasons", "supervised_reasons", "delay_reasons")
RULE_COLUMNS = (
    "rule_sanction_delay",
    "rule_stuck_work",
    "rule_cost_outlier",
    "rule_fast_completion",
    "rule_round_amount",
    "rule_vendor_concentration",
    "rule_payment_stuck",
)


def _clean(value: Any) -> Any:
    """Convert numpy/pandas scalars to plain JSON-safe Python values."""
    if value is None:
        return None
    if isinstance(value, float | np.floating):
        number = float(value)
        return None if math.isnan(number) or math.isinf(number) else number
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_ | bool):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.date()
    if isinstance(value, np.ndarray):
        return [_clean(v) for v in value.tolist()]
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    if isinstance(value, np.ndarray | list | tuple):
        return [_clean(v) for v in list(value)]
    return []


def _date(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    stamp = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(stamp) else stamp.date()


def stable_group_id(prefix: str, work_ids: list[str]) -> str:
    digest = hashlib.sha1(",".join(sorted(work_ids)).encode("utf-8")).hexdigest()[:10].upper()
    return f"{prefix}-{digest}"


def _work_rows(frame: pd.DataFrame, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now = datetime.now(UTC).replace(tzinfo=None)
    records = frame.to_dict("records")
    for rec in records:
        work_id = str(rec["work_id"])
        detail = {col: _clean(rec.get(col)) for col in _DETAIL_COLUMNS if col in rec}
        for col in _JSON_LIST_COLUMNS:
            if col in rec:
                detail[col] = _as_list(rec.get(col))
        rows.append(
            {
                "work_id": work_id,
                "source": source,
                "chamber": _clean(rec.get("chamber")),
                "work_category": _clean(rec.get("work_category")),
                "state": str(rec.get("state") or ""),
                "ida": str(rec.get("ida") or ""),
                "district": district_from_ida(rec.get("ida")),
                "constituency": str(rec.get("constituency") or ""),
                "mp_code": mp_code_from_work_id(work_id),
                "mp_name": _clean(rec.get("mp_name")),
                "vendor_name": _clean(rec.get("vendor_name")),
                "work_description": _clean(rec.get("work_description")),
                "work_type": str(rec.get("work_type") or "Others"),
                "work_status": _clean(rec.get("work_status")),
                "recommended_date": _date(rec.get("recommended_date")),
                "sanction_date": _date(rec.get("sanction_date")),
                "completion_date": _date(rec.get("completion_date")),
                "latest_expenditure_date": _date(rec.get("latest_expenditure_date")),
                "sanction_amount": _clean(rec.get("sanction_amount")) or 0.0,
                "total_fund_disbursed": _clean(rec.get("total_fund_disbursed")),
                "num_payments": _clean(rec.get("num_payments")),
                "latest_payment_status": _clean(rec.get("latest_payment_status")),
                "days_to_sanction": _clean(rec.get("days_to_sanction")),
                "days_since_sanction": _clean(rec.get("days_since_sanction")),
                "duration_days": _clean(rec.get("duration_days")),
                "is_open": _date(rec.get("completion_date")) is None,
                "risk_score": _clean(rec.get("risk_score")) or 0.0,
                "base_risk_score": _clean(rec.get("base_risk_score"))
                or _clean(rec.get("risk_score"))
                or 0.0,
                "band": str(rec.get("band") or "Low"),
                "severe_rule_count": int(_clean(rec.get("severe_rule_count")) or 0),
                "severe_floor_applied": bool(_clean(rec.get("severe_floor_applied")) or False),
                "sig_rule": _clean(rec.get("rule")) or 0.0,
                "sig_supervised": _clean(rec.get("supervised")) or 0.0,
                "sig_unsupervised": _clean(rec.get("unsupervised")) or 0.0,
                "sig_cost": _clean(rec.get("cost")) or 0.0,
                "sig_duplicate": _clean(rec.get("duplicate")) or 0.0,
                "sig_delay": _clean(rec.get("delay")) or 0.0,
                "cost_channel": _clean(rec.get("cost_channel")) or None,
                "cost_ratio": _clean(rec.get("cost_ratio")),
                "expected_cost_amount": _clean(rec.get("expected_cost_amount")),
                "state_peer_label": _clean(rec.get("state_peer_label")) or None,
                "state_peer_median": _clean(rec.get("state_peer_median")),
                "state_cost_ratio": _clean(rec.get("state_cost_ratio")),
                "dup_score": _clean(rec.get("dup_score")) or 0.0,
                "split_score": _clean(rec.get("split_score")) or 0.0,
                "delay_risk": _clean(rec.get("delay_risk")) or 0.0,
                "rule_score": _clean(rec.get("rule_score")) or 0.0,
                **{rule: bool(_clean(rec.get(rule)) or False) for rule in RULE_COLUMNS},
                "reasons_en": _as_list(rec.get("reasons_en")),
                "reasons_hi": _as_list(rec.get("reasons_hi")),
                "detail": detail,
                "scored_at": now,
            }
        )
    return rows


def _chunks(rows: list[dict[str, Any]], size: int = 4000) -> list[list[dict[str, Any]]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def _read_scored() -> tuple[pd.DataFrame, pd.DataFrame | None]:
    scored = pd.read_parquet(PROCESSED / "scored_works.parquet")
    holdout_path = PROCESSED / "holdout_scored.parquet"
    holdout = pd.read_parquet(holdout_path) if holdout_path.exists() else None
    return scored, holdout


def load_works(db: Session) -> dict[str, dict[str, Any]]:
    """Replace pipeline works. Returns a lookup of work_id -> scope fields."""
    scored, holdout = _read_scored()
    rows = _work_rows(scored, "training")
    if holdout is not None:
        rows += _work_rows(holdout, "holdout")

    db.execute(delete(models.DuplicatePair))
    db.execute(delete(models.AlertWork))
    db.execute(delete(models.Work).where(models.Work.source.in_(["training", "holdout"])))
    for chunk in _chunks(rows):
        db.execute(insert(models.Work), chunk)
    db.flush()
    return {
        r["work_id"]: {
            "state": r["state"],
            "ida": r["ida"],
            "district": r["district"],
            "mp_code": r["mp_code"],
            "constituency": r["constituency"],
            "band": r["band"],
            "risk_score": r["risk_score"],
            "sanction_amount": r["sanction_amount"],
            "work_type": r["work_type"],
            "reasons_en": r["reasons_en"],
            "reasons_hi": r["reasons_hi"],
            "source": r["source"],
        }
        for r in rows
    }


def _group_scope(work_ids: list[str], lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    members = [lookup[w] for w in work_ids if w in lookup]
    if not members:
        return {"state": "", "ida": "", "district": "", "mp_code": None, "constituency": None}
    first = members[0]
    return {
        "state": first["state"],
        "ida": first["ida"],
        "district": first["district"],
        "mp_code": first["mp_code"],
        "constituency": first["constituency"],
    }


def _alert_rows(lookup: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Alerts from the pipeline plus High/Critical holdout works.

    Returns the rows and a map from the pipeline's group id to the stable id.
    """
    frame = pd.read_parquet(PROCESSED / "alerts.parquet")
    remap: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for rec in frame.to_dict("records"):
        work_ids = [w for w in str(rec["work_ids"]).split(",") if w]
        kind = str(rec["alert_type"])
        if kind == "high_risk_work":
            alert_id = work_ids[0]
        else:
            prefix = "DUP" if kind == "duplicate_group" else "SPL"
            alert_id = stable_group_id(prefix, work_ids)
            remap[str(rec["alert_id"])] = alert_id
        scope = _group_scope(work_ids, lookup)
        risk = _clean(rec.get("risk_score"))
        if risk is None and work_ids:
            risk = max((lookup[w]["risk_score"] for w in work_ids if w in lookup), default=None)
        out.append(
            {
                "alert_id": alert_id,
                "alert_type": kind,
                "severity": str(rec["severity"]),
                "risk_score": risk,
                "amount": _clean(rec.get("amount")) or 0.0,
                "n_works": int(_clean(rec.get("n_works")) or len(work_ids)),
                "work_type": _clean(rec.get("work_type")),
                "reasons_en": _as_list(rec.get("reasons_en")),
                "reasons_hi": _as_list(rec.get("reasons_hi")),
                "evidence": {"work_ids": work_ids, "pipeline_id": str(rec["alert_id"])},
                "source": "pipeline",
                "_work_ids": work_ids,
                **scope,
            }
        )

    # The holdout is scored like an upload, so its High/Critical works get the
    # same single-work alerts as training works.
    seen = {row["alert_id"] for row in out}
    for work_id, info in lookup.items():
        if (
            info["source"] != "holdout"
            or info["band"] not in {"High", "Critical"}
            or work_id in seen
        ):
            continue
        out.append(
            {
                "alert_id": work_id,
                "alert_type": "high_risk_work",
                "severity": info["band"],
                "risk_score": info["risk_score"],
                "amount": info["sanction_amount"],
                "n_works": 1,
                "work_type": info["work_type"],
                "reasons_en": info["reasons_en"],
                "reasons_hi": info["reasons_hi"],
                "evidence": {"work_ids": [work_id], "pipeline_id": work_id},
                "source": "holdout",
                "_work_ids": [work_id],
                "state": info["state"],
                "ida": info["ida"],
                "district": info["district"],
                "mp_code": info["mp_code"],
                "constituency": info["constituency"],
            }
        )
    return out, remap


_WORKFLOW_FIELDS = {"status", "level", "assignee_id", "raised_at", "updated_at", "escalated_at"}


def load_alerts(db: Session, lookup: dict[str, dict[str, Any]]) -> tuple[int, int, dict[str, str]]:
    """Upsert alerts, preserving workflow fields. Returns (new, retired, remap)."""
    rows, remap = _alert_rows(lookup)
    existing = {a for (a,) in db.execute(select(models.Alert.alert_id)).all()}
    incoming = {r["alert_id"] for r in rows}
    now = datetime.now(UTC).replace(tzinfo=None)

    new_rows: list[dict[str, Any]] = []
    links: list[dict[str, str]] = []
    for row in rows:
        work_ids = row.pop("_work_ids")
        links.extend(
            {"alert_id": row["alert_id"], "work_id": w}
            for w in dict.fromkeys(work_ids)
            if w in lookup
        )
        if row["alert_id"] in existing:
            fields = {k: v for k, v in row.items() if k not in _WORKFLOW_FIELDS and k != "alert_id"}
            db.execute(
                update(models.Alert)
                .where(models.Alert.alert_id == row["alert_id"])
                .values(**fields, is_active=True)
            )
        else:
            new_rows.append(
                {**row, "status": "Open", "level": "district", "raised_at": now, "updated_at": now}
            )

    for chunk in _chunks(new_rows):
        db.execute(insert(models.Alert), chunk)

    retired = existing - incoming
    if retired:
        db.execute(
            update(models.Alert)
            .where(models.Alert.alert_id.in_(retired), models.Alert.source != "ingest")
            .values(is_active=False)
        )
    for chunk in _chunks(links):
        db.execute(insert(models.AlertWork), chunk)
    db.flush()
    return len(new_rows), len(retired), remap


def load_duplicate_pairs(db: Session, lookup: dict[str, dict[str, Any]]) -> int:
    path = PROCESSED / "duplicate_pairs.parquet"
    clusters_path = PROCESSED / "duplicates.parquet"
    if not path.exists():
        return 0
    pairs = pd.read_parquet(path)

    group_of: dict[str, str] = {}
    if clusters_path.exists():
        for ids in pd.read_parquet(clusters_path)["work_ids"]:
            members = [w for w in str(ids).split(",") if w]
            stable = stable_group_id("DUP", members)
            for w in members:
                group_of[w] = stable

    rows: list[dict[str, Any]] = []
    for rec in pairs.to_dict("records"):
        a, b = str(rec["work_id_a"]), str(rec["work_id_b"])
        if a not in lookup or b not in lookup:
            continue
        rows.append(
            {
                "work_id_a": a,
                "work_id_b": b,
                "dup_group_id": group_of.get(a),
                "state": lookup[a]["state"],
                "ida": lookup[a]["ida"],
                "mp_code": lookup[a]["mp_code"],
                "work_type": _clean(rec.get("work_type")),
                "pair_score": float(rec["pair_score"]),
                "cosine": float(rec["cosine"]),
                "token_set": float(rec["token_set"]),
                "location_overlap": float(rec["location_overlap"]),
                "amount_similarity": float(rec["amount_similarity"]),
                "days_apart": float(rec["days_apart"]),
                "shared_location_words": _clean(rec.get("shared_location_words")),
                "is_standard_item": bool(rec.get("is_standard_item", False)),
            }
        )
    for chunk in _chunks(rows):
        db.execute(insert(models.DuplicatePair), chunk)
    db.flush()
    return len(rows)


def load_split_groups(db: Session, lookup: dict[str, dict[str, Any]]) -> int:
    path = PROCESSED / "split_groups.parquet"
    db.execute(delete(models.SplitGroup))
    if not path.exists():
        return 0
    rows: list[dict[str, Any]] = []
    for rec in pd.read_parquet(path).to_dict("records"):
        work_ids = [w for w in str(rec["work_ids"]).split(",") if w]
        scope = _group_scope(work_ids, lookup)
        rows.append(
            {
                "split_group_id": stable_group_id("SPL", work_ids),
                "state": scope["state"],
                "ida": scope["ida"],
                "mp_code": scope["mp_code"],
                "work_type": str(rec["work_type"]),
                "vendor_name": _clean(rec.get("vendor_name")) or None,
                "same_vendor": bool(rec.get("same_vendor", False)),
                "n_works": int(rec["n_works"]),
                "work_ids": work_ids,
                "total_amount": float(rec["total_amount"]),
                "split_score": float(rec["split_score"]),
                "detail": {
                    k: _clean(rec.get(k))
                    for k in (
                        "peer_median",
                        "peer_p90",
                        "total_vs_p90",
                        "span_days",
                        "location_overlap",
                        "share_just_below_round",
                        "first_sanction",
                        "last_sanction",
                    )
                },
            }
        )
    for row in rows:
        for key in ("first_sanction", "last_sanction"):
            if isinstance(row["detail"].get(key), date):
                row["detail"][key] = row["detail"][key].isoformat()
    for chunk in _chunks(rows):
        db.execute(insert(models.SplitGroup), chunk)
    db.flush()
    return len(rows)


def load_metrics(db: Session) -> None:
    if not METRICS.exists():
        return
    body = json.loads(METRICS.read_text(encoding="utf-8"))
    db.merge(
        models.MetricDoc(key="metrics", body=body, loaded_at=datetime.now(UTC).replace(tzinfo=None))
    )
    db.flush()


def run(kind: str = "initial_load", reset: bool = False) -> dict[str, Any]:
    """Load everything. Returns a summary."""
    engine = get_engine()
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with session_scope() as db:
        record = models.ScoringRun(kind=kind)
        db.add(record)
        db.flush()

        lookup = load_works(db)
        new, retired, _ = load_alerts(db, lookup)
        pairs = load_duplicate_pairs(db, lookup)
        groups = load_split_groups(db, lookup)
        load_metrics(db)

        from backend.app.seed import ensure_demo_users

        users = ensure_demo_users(db)

        record.works_loaded = len(lookup)
        record.alerts_new = new
        record.alerts_retired = retired
        record.status = "ok"
        record.finished_at = datetime.now(UTC).replace(tzinfo=None)
        record.message = f"{len(lookup)} works, {new} new alerts, {retired} retired, {pairs} pairs, {groups} split groups"

        return {
            "works": len(lookup),
            "alerts_new": new,
            "alerts_retired": retired,
            "duplicate_pairs": pairs,
            "split_groups": groups,
            "demo_users": users,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load pipeline outputs into the app database.")
    parser.add_argument(
        "--reset", action="store_true", help="drop all tables first, including workflow"
    )
    args = parser.parse_args(argv)
    summary = run(reset=args.reset)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
