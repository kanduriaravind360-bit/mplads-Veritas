"""Tamper-evident audit trail: an append-only SHA-256 hash chain.

Each event is serialised canonically (sorted keys, no whitespace) together with
its sequence number, and hashed with the previous event's hash:

    hash_n = sha256(hash_{n-1} || canonical(event_n))

Changing any field of any past event, deleting one, or swapping two, changes
that event's recomputed hash and therefore every hash after it. :func:`verify`
walks the chain and reports the first break. It cannot stop someone with direct
database access from rewriting the whole chain end to end; for that the latest
hash has to be anchored somewhere they cannot reach (a printed brief, an email,
a second system), which is what the PDF briefs record.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app import models

GENESIS = "0" * 64
_append_lock = threading.Lock()


def _canonical(event: dict[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_hash(prev_hash: str, event: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(event)).encode("utf-8")).hexdigest()


def _event_dict(row: models.AuditEvent) -> dict[str, Any]:
    return {
        "seq": row.seq,
        "ts": row.ts,
        "actor": row.actor,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "payload": row.payload,
    }


def append(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
) -> models.AuditEvent:
    """Append one event to the chain. The caller commits."""
    with _append_lock:
        last = db.execute(
            select(models.AuditEvent).order_by(models.AuditEvent.seq.desc()).limit(1)
        ).scalar_one_or_none()
        seq = (last.seq + 1) if last else 1
        prev_hash = last.hash if last else GENESIS
        event = {
            "seq": seq,
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "actor": actor,
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            # Round-trip through JSON so the stored payload and the hashed payload
            # are byte-for-byte the same thing.
            "payload": json.loads(_canonical(payload or {})),
        }
        row = models.AuditEvent(prev_hash=prev_hash, hash=compute_hash(prev_hash, event), **event)
        db.add(row)
        db.flush()
        return row


@dataclass
class ChainReport:
    ok: bool
    events_checked: int
    first_broken_seq: int | None
    head_hash: str | None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "events_checked": self.events_checked,
            "first_broken_seq": self.first_broken_seq,
            "head_hash": self.head_hash,
            "reason": self.reason,
        }


def verify(db: Session) -> ChainReport:
    """Recompute every hash in order and report the first inconsistency."""
    prev = GENESIS
    expected_seq = 1
    checked = 0
    head: str | None = None
    rows = db.execute(select(models.AuditEvent).order_by(models.AuditEvent.seq)).scalars()
    for row in rows:
        if row.seq != expected_seq:
            return ChainReport(
                False, checked, row.seq, head, f"sequence gap: expected {expected_seq}"
            )
        if row.prev_hash != prev:
            return ChainReport(False, checked, row.seq, head, "prev_hash does not match the chain")
        if compute_hash(prev, _event_dict(row)) != row.hash:
            return ChainReport(
                False, checked, row.seq, head, "event content does not match its hash"
            )
        prev = row.hash
        head = row.hash
        expected_seq += 1
        checked += 1
    return ChainReport(True, checked, None, head)


def trail_for(db: Session, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
    """Events for one entity, oldest first, with their hashes."""
    rows = db.execute(
        select(models.AuditEvent)
        .where(
            models.AuditEvent.entity_type == entity_type,
            models.AuditEvent.entity_id == str(entity_id),
        )
        .order_by(models.AuditEvent.seq)
    ).scalars()
    return [{**_event_dict(row), "hash": row.hash, "prev_hash": row.prev_hash} for row in rows]


def head(db: Session) -> tuple[int, str | None]:
    count = db.execute(select(func.count()).select_from(models.AuditEvent)).scalar_one()
    last = db.execute(
        select(models.AuditEvent.hash).order_by(models.AuditEvent.seq.desc()).limit(1)
    ).scalar_one_or_none()
    return int(count), last
