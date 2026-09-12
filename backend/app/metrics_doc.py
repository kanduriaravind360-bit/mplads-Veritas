"""Read the loaded models/metrics.json so no metric is ever typed into a response."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app import models


def metrics(db: Session) -> dict[str, Any]:
    doc = db.get(models.MetricDoc, "metrics")
    return doc.body if doc is not None else {}


def weakest_detector_note(db: Session) -> str | None:
    """The plain-language weak-spot sentence the pipeline wrote, if present."""
    return metrics(db).get("injection_test", {}).get("weakest_detector_plain_language")
