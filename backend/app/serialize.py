"""ORM rows to JSON-ready dicts, with presentation redaction applied last."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.app import models
from backend.app.redact import redact_record


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


def work_summary(work: models.Work) -> dict[str, Any]:
    return redact_record(
        {
            "work_id": work.work_id,
            "source": work.source,
            "state": work.state,
            "district": work.district,
            "ida": work.ida,
            "constituency": work.constituency,
            "mp_name": work.mp_name,
            "chamber": work.chamber,
            "work_type": work.work_type,
            "work_status": work.work_status,
            "work_description": work.work_description,
            "vendor_name": work.vendor_name,
            "sanction_date": _iso(work.sanction_date),
            "completion_date": _iso(work.completion_date),
            "sanction_amount": work.sanction_amount,
            "total_fund_disbursed": work.total_fund_disbursed,
            "risk_score": round(work.risk_score, 2),
            "band": work.band,
            "is_open": work.is_open,
            "delay_risk": round(work.delay_risk, 4),
            "severe_floor_applied": work.severe_floor_applied,
            "top_reason_en": (work.reasons_en or [None])[0],
            "top_reason_hi": (work.reasons_hi or [None])[0],
        }
    )


def work_detail(work: models.Work) -> dict[str, Any]:
    detail = work.detail or {}
    base = work_summary(work)
    base.update(
        {
            "recommended_date": _iso(work.recommended_date),
            "latest_expenditure_date": _iso(work.latest_expenditure_date),
            "num_payments": work.num_payments,
            "latest_payment_status": work.latest_payment_status,
            "days_to_sanction": work.days_to_sanction,
            "days_since_sanction": work.days_since_sanction,
            "duration_days": work.duration_days,
            "base_risk_score": round(work.base_risk_score, 2),
            "severe_rule_count": work.severe_rule_count,
            "signals": {
                "rule": work.sig_rule,
                "supervised": work.sig_supervised,
                "unsupervised": work.sig_unsupervised,
                "cost": work.sig_cost,
                "duplicate": work.sig_duplicate,
                "delay": work.sig_delay,
            },
            "cost": {
                "channel": work.cost_channel,
                "ratio": work.cost_ratio,
                "expected_amount": work.expected_cost_amount,
                "state_peer_label": work.state_peer_label,
                "state_peer_median": work.state_peer_median,
                "state_cost_ratio": work.state_cost_ratio,
                "state_channel_in_score": False,
            },
            "dup_score": work.dup_score,
            "split_score": work.split_score,
            "rule_score": work.rule_score,
            "reasons_en": work.reasons_en or [],
            "reasons_hi": work.reasons_hi or [],
            "rules": {
                k: v for k, v in detail.items() if k.startswith("rule_") and k != "rule_reasons"
            },
            "severe_rules": {k: v for k, v in detail.items() if k.startswith("severe_")},
            "attributions": {
                "unsupervised": detail.get("unsup_reasons", []),
                "supervised": detail.get("supervised_reasons", []),
                "delay": detail.get("delay_reasons", []),
            },
            "context": {
                k: detail.get(k)
                for k in (
                    "peer_group",
                    "peer_n",
                    "amount_vs_peer_median",
                    "cost_residual_z",
                    "quantity",
                    "unit_rate",
                    "disbursed_ratio",
                    "vendor_total_works",
                    "vendor_works_in_ida",
                    "vendor_share_of_ida",
                    "ida_works",
                    "ida_completion_rate",
                    "ida_vendor_hhi",
                    "has_date_error",
                )
            },
            "scored_at": _iso(work.scored_at),
        }
    )
    return base


def alert_summary(alert: models.Alert) -> dict[str, Any]:
    record = {
        "alert_id": alert.alert_id,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "risk_score": None if alert.risk_score is None else round(alert.risk_score, 2),
        "amount": alert.amount,
        "n_works": alert.n_works,
        "state": alert.state,
        "district": alert.district,
        "ida": alert.ida,
        "constituency": alert.constituency,
        "work_type": alert.work_type,
        "status": alert.status,
        "level": alert.level,
        "assignee": alert.assignee.email if alert.assignee else None,
        "raised_at": _iso(alert.raised_at),
        "updated_at": _iso(alert.updated_at),
        "escalated_at": _iso(alert.escalated_at),
        "source": alert.source,
        "is_active": alert.is_active,
        "top_reason_en": (alert.reasons_en or [None])[0],
        "top_reason_hi": (alert.reasons_hi or [None])[0],
    }
    return redact_record(record)


def alert_detail(alert: models.Alert) -> dict[str, Any]:
    out = alert_summary(alert)
    out.update(
        {
            "reasons_en": alert.reasons_en or [],
            "reasons_hi": alert.reasons_hi or [],
            "evidence": alert.evidence or {},
            "work_ids": [link.work_id for link in alert.works],
        }
    )
    return out


def split_group(group: models.SplitGroup) -> dict[str, Any]:
    return redact_record(
        {
            "split_group_id": group.split_group_id,
            "state": group.state,
            "ida": group.ida,
            "work_type": group.work_type,
            "vendor_name": group.vendor_name,
            "same_vendor": group.same_vendor,
            "n_works": group.n_works,
            "work_ids": group.work_ids,
            "total_amount": group.total_amount,
            "split_score": group.split_score,
            "detail": group.detail,
        }
    )
