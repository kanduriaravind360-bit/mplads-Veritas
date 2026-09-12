"""Pydantic v2 request and response models for the public contract.

Large read endpoints return plain JSON built from ORM rows (after presentation
redaction); these schemas pin the shapes that clients write or that the
frontend depends on structurally.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    role: str
    state: str | None = None
    ida: str | None = None
    mp_code: str | None = None
    scope_label: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


class WorkSummary(BaseModel):
    work_id: str
    state: str
    district: str
    ida: str
    constituency: str | None = None
    mp_name: str | None = None
    work_type: str
    work_status: str | None = None
    work_description: str | None = None
    sanction_date: date | None = None
    sanction_amount: float
    risk_score: float
    band: str
    source: str
    vendor_name: str | None = None
    reasons_en: list[str] = []


class PageOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[dict[str, Any]]


class TransitionRequest(BaseModel):
    to_status: str
    note: str | None = Field(default=None, max_length=4000)


class AssignRequest(BaseModel):
    assignee_email: str | None = None


class CommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class FeedbackRequest(BaseModel):
    verdict: str
    note: str | None = Field(default=None, max_length=4000)
    work_id: str | None = None


class BulkRequest(BaseModel):
    alert_ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["transition", "assign"]
    to_status: str | None = None
    assignee_email: str | None = None
    note: str | None = Field(default=None, max_length=4000)


class PairDecisionRequest(BaseModel):
    decision: Literal["duplicate", "not_duplicate"]
    note: str | None = Field(default=None, max_length=4000)


class CaseCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    kind: Literal["split_group", "vendor", "district_pattern", "custom"] = "custom"
    alert_ids: list[str] = Field(default_factory=list, max_length=500)
    summary: str | None = Field(default=None, max_length=8000)


class CaseUpdate(BaseModel):
    status: Literal["Open", "In progress", "Referred", "Closed"] | None = None
    summary: str | None = Field(default=None, max_length=8000)
    add_alert_ids: list[str] = Field(default_factory=list, max_length=500)
    remove_alert_ids: list[str] = Field(default_factory=list, max_length=500)


class NoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


class AuditEventOut(BaseModel):
    seq: int
    ts: str
    actor: str
    action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    hash: str
    prev_hash: str


class ChainOut(BaseModel):
    ok: bool
    events_checked: int
    first_broken_seq: int | None
    head_hash: str | None
    reason: str | None = None
    checked_at: datetime | None = None
