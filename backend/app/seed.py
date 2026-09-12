"""Demo users, resolved against the data actually loaded.

Scopes come from configs/api.yaml. A district is named by a fragment of its IDA
string ("LUCKNOW") and resolved to the exact IDA in the works table, so the demo
user's scope is guaranteed to match real rows rather than a guessed spelling.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.security import hash_password
from backend.app.settings import get_settings


def _resolve_ida(db: Session, fragment: str) -> str | None:
    """The most common IDA containing ``fragment``."""
    row = db.execute(
        select(models.Work.ida, func.count())
        .where(models.Work.ida.ilike(f"%{fragment}%"))
        .group_by(models.Work.ida)
        .order_by(func.count().desc())
        .limit(1)
    ).first()
    return row[0] if row else None


def ensure_demo_users(db: Session) -> list[dict[str, Any]]:
    """Create or update the demo users. Idempotent."""
    cfg = get_settings().api["demo_users"]
    password_hash: str | None = None
    out: list[dict[str, Any]] = []

    for spec in cfg["users"]:
        ida = _resolve_ida(db, spec["ida_contains"]) if spec.get("ida_contains") else None
        user = db.execute(
            select(models.User).where(models.User.email == spec["email"])
        ).scalar_one_or_none()
        if user is None:
            password_hash = password_hash or hash_password(str(cfg["password"]))
            user = models.User(
                email=spec["email"],
                password_hash=password_hash,
                name=spec["name"],
                role=spec["role"],
            )
            db.add(user)
        user.name = spec["name"]
        user.role = spec["role"]
        user.state = spec.get("state")
        user.ida = ida
        user.mp_code = spec.get("mp_code")
        db.flush()
        out.append(
            {
                "email": user.email,
                "role": user.role,
                "state": user.state,
                "ida": user.ida,
                "mp_code": user.mp_code,
            }
        )
    return out
