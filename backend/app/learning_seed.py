"""Seed demo verdicts so the learning panel has something to learn from.

    python -m backend.app.learning_seed

What is seeded, and why it is honest:

* Positives are the planted synthetic cases (``planted_cases``), whose anomaly is
  known by construction. They need no verdict row at all. No real work is ever
  seeded as confirmed.
* Negatives are false-positive verdicts on REAL alerts that match a documented
  benign pattern, applied by rule and written as such in the note:
  purchased goods recorded complete within days, duplicate groups made only of
  catalogue items, and the named demo cases in ``configs/api.yaml``.

Seeded verdicts are ``is_seed`` and never change an alert's workflow status.
Re-running replaces the previous seeds; reviewers' own verdicts are untouched.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app import audit, models
from backend.app.db import session_scope
from backend.app.loader import partition_of
from backend.app.settings import get_settings

ACTOR = "seed-rule@system"


def _signals(work: models.Work) -> dict[str, float]:
    return {
        "rule": work.sig_rule,
        "supervised": work.sig_supervised,
        "unsupervised": work.sig_unsupervised,
        "cost": work.sig_cost,
        "duplicate": work.sig_duplicate,
        "delay": work.sig_delay,
        "risk_score": work.risk_score,
    }


def _add(db: Session, alert_id: str, work: models.Work, verdict: str, note: str) -> None:
    db.add(
        models.Feedback(
            alert_id=alert_id,
            work_id=work.work_id,
            reviewer_id=None,
            verdict=verdict,
            note=note,
            signals=_signals(work),
            is_seed=True,
            partition=partition_of(alert_id),
        )
    )


def seed(db: Session) -> dict[str, Any]:
    cfg = get_settings().api["learning"]["seed"]
    db.execute(delete(models.Feedback).where(models.Feedback.is_seed.is_(True)))
    counts: dict[str, int] = defaultdict(int)
    seen: set[str] = set()

    for item in cfg.get("demo_false_positives") or []:
        work = db.get(models.Work, item["work_id"])
        alert = db.get(models.Alert, item["work_id"])
        if work is None or alert is None:
            continue
        _add(db, alert.alert_id, work, "false_positive", f"Seeded demo verdict. {item['reason']}")
        seen.add(alert.alert_id)
        counts["demo_cases"] += 1

    purchases = list(cfg.get("purchase_work_types") or [])
    if purchases:
        rows = db.execute(
            select(models.Alert, models.Work)
            .join(models.Work, models.Work.work_id == models.Alert.alert_id)
            .where(
                models.Alert.alert_type == "high_risk_work",
                models.Alert.is_active.is_(True),
                models.Work.work_type.in_(purchases),
                models.Work.rule_fast_completion.is_(True),
                models.Work.sig_cost < 0.5,
                models.Work.sig_duplicate < 0.5,
            )
        ).all()
        for alert, work in rows:
            if alert.alert_id in seen:
                continue
            _add(
                db,
                alert.alert_id,
                work,
                "false_positive",
                f"Seeded by rule: {work.work_type} is a purchase, and goods recorded as "
                "delivered within days is expected, not a sign of a skipped work.",
            )
            seen.add(alert.alert_id)
            counts["purchase_fast_completion"] += 1

    if cfg.get("standard_item_duplicates"):
        pairs = db.execute(
            select(models.DuplicatePair.dup_group_id, models.DuplicatePair.is_standard_item).where(
                models.DuplicatePair.dup_group_id.is_not(None)
            )
        ).all()
        all_standard: dict[str, bool] = {}
        for group, standard in pairs:
            all_standard[group] = all_standard.get(group, True) and bool(standard)
        for group, standard in all_standard.items():
            alert = db.get(models.Alert, group)
            if not standard or alert is None or not alert.is_active or group in seen:
                continue
            member = db.execute(
                select(models.Work)
                .join(models.AlertWork, models.AlertWork.work_id == models.Work.work_id)
                .where(models.AlertWork.alert_id == group)
                .order_by(models.Work.risk_score.desc())
                .limit(1)
            ).scalar_one_or_none()
            if member is None:
                continue
            _add(
                db,
                group,
                member,
                "not_duplicate",
                "Seeded by rule: every pair in this group is a catalogue item ordered in many "
                "places, so similar wording is expected and is not evidence of a duplicate.",
            )
            seen.add(group)
            counts["standard_item_duplicates"] += 1

    planted_bands = list(cfg.get("planted_bands") or ["High", "Critical"])
    planted = db.execute(
        select(models.PlantedCase.partition).where(models.PlantedCase.band.in_(planted_bands))
    ).all()
    counts["planted_positives"] = len(planted)

    audit.append(
        db,
        actor=ACTOR,
        action="learning_seeded",
        entity_type="learning",
        entity_id="seed",
        payload=dict(counts),
    )
    return dict(counts)


def main() -> int:
    with session_scope() as db:
        print(json.dumps(seed(db), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
