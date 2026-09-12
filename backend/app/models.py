"""ORM models.

Two kinds of table live here, and the distinction matters on reload:

* **Pipeline-derived** (works, alerts' scores, duplicate and split groups,
  metrics) are rebuilt from the ML outputs whenever the pipeline re-runs.
* **Workflow** (alert status, assignments, comments, feedback, cases, the audit
  trail) is human work. A reload must never erase it, so the loader upserts
  pipeline fields and leaves workflow fields alone.

Every scoped table carries ``state``, ``ida`` and ``mp_code`` so row-level
scoping can be applied uniformly (see ``backend.app.scoping``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


def _now() -> datetime:
    # Naive UTC: SQLite has no time zones, so every stored time is UTC by rule.
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), index=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ida: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mp_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Work(Base):
    """One MPLADS work with its scores. Pipeline-derived."""

    __tablename__ = "works"

    work_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), index=True)  # training | holdout | ingest
    chamber: Mapped[str | None] = mapped_column(String(10))
    work_category: Mapped[str | None] = mapped_column(String(60))
    state: Mapped[str] = mapped_column(String(100), index=True)
    ida: Mapped[str] = mapped_column(String(200), index=True)
    district: Mapped[str] = mapped_column(String(120), index=True)
    constituency: Mapped[str] = mapped_column(String(200), index=True)
    mp_code: Mapped[str | None] = mapped_column(String(20), index=True)
    mp_name: Mapped[str | None] = mapped_column(String(200))
    vendor_name: Mapped[str | None] = mapped_column(String(300), index=True)
    work_description: Mapped[str | None] = mapped_column(Text)
    work_type: Mapped[str] = mapped_column(String(120), index=True)
    work_status: Mapped[str | None] = mapped_column(String(60), index=True)

    recommended_date: Mapped[date | None] = mapped_column(Date)
    sanction_date: Mapped[date | None] = mapped_column(Date, index=True)
    completion_date: Mapped[date | None] = mapped_column(Date)
    latest_expenditure_date: Mapped[date | None] = mapped_column(Date)

    sanction_amount: Mapped[float] = mapped_column(Float, default=0.0)
    total_fund_disbursed: Mapped[float | None] = mapped_column(Float)
    num_payments: Mapped[int | None] = mapped_column(Integer)
    latest_payment_status: Mapped[str | None] = mapped_column(String(60))
    days_to_sanction: Mapped[float | None] = mapped_column(Float)
    days_since_sanction: Mapped[float | None] = mapped_column(Float)
    duration_days: Mapped[float | None] = mapped_column(Float)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    risk_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    base_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    band: Mapped[str] = mapped_column(String(10), index=True)
    severe_rule_count: Mapped[int] = mapped_column(Integer, default=0)
    severe_floor_applied: Mapped[bool] = mapped_column(Boolean, default=False)

    # The six fusion channels, 0-1 each.
    sig_rule: Mapped[float] = mapped_column(Float, default=0.0)
    sig_supervised: Mapped[float] = mapped_column(Float, default=0.0)
    sig_unsupervised: Mapped[float] = mapped_column(Float, default=0.0)
    sig_cost: Mapped[float] = mapped_column(Float, default=0.0)
    sig_duplicate: Mapped[float] = mapped_column(Float, default=0.0)
    sig_delay: Mapped[float] = mapped_column(Float, default=0.0)

    cost_channel: Mapped[str | None] = mapped_column(String(20))
    cost_ratio: Mapped[float | None] = mapped_column(Float)
    expected_cost_amount: Mapped[float | None] = mapped_column(Float)
    state_peer_label: Mapped[str | None] = mapped_column(String(200))
    state_peer_median: Mapped[float | None] = mapped_column(Float)
    state_cost_ratio: Mapped[float | None] = mapped_column(Float)
    dup_score: Mapped[float] = mapped_column(Float, default=0.0)
    split_score: Mapped[float] = mapped_column(Float, default=0.0)
    delay_risk: Mapped[float] = mapped_column(Float, default=0.0)
    rule_score: Mapped[float] = mapped_column(Float, default=0.0)

    # The seven recomputed rules, as columns so compliance views aggregate in SQL.
    rule_sanction_delay: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_stuck_work: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_cost_outlier: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_fast_completion: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_round_amount: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_vendor_concentration: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_payment_stuck: Mapped[bool] = mapped_column(Boolean, default=False)

    reasons_en: Mapped[list] = mapped_column(JSON, default=list)
    reasons_hi: Mapped[list] = mapped_column(JSON, default=list)
    # Rule flags, severe flags, SHAP/deviation attributions, peer context.
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (
        Index("ix_works_scope_band", "state", "ida", "band"),
        Index("ix_works_ida_type_date", "ida", "work_type", "sanction_date"),
    )


class Alert(Base):
    """A review item: one high-risk work, a duplicate group or a split group."""

    __tablename__ = "alerts"

    alert_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(30), index=True)
    severity: Mapped[str] = mapped_column(String(10), index=True)
    risk_score: Mapped[float | None] = mapped_column(Float, index=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    n_works: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(100), index=True)
    ida: Mapped[str] = mapped_column(String(200), index=True)
    district: Mapped[str] = mapped_column(String(120), index=True)
    constituency: Mapped[str | None] = mapped_column(String(200))
    mp_code: Mapped[str | None] = mapped_column(String(20), index=True)
    work_type: Mapped[str | None] = mapped_column(String(120))
    reasons_en: Mapped[list] = mapped_column(JSON, default=list)
    reasons_hi: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(20), default="pipeline")

    # Workflow fields: never overwritten by a reload.
    status: Mapped[str] = mapped_column(String(30), default="Open", index=True)
    level: Mapped[str] = mapped_column(String(20), default="district", index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    raised_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    works: Mapped[list[AlertWork]] = relationship(cascade="all, delete-orphan")
    assignee: Mapped[User | None] = relationship()


class AlertWork(Base):
    __tablename__ = "alert_works"

    alert_id: Mapped[str] = mapped_column(
        ForeignKey("alerts.alert_id", ondelete="CASCADE"), primary_key=True
    )
    work_id: Mapped[str] = mapped_column(ForeignKey("works.work_id"), primary_key=True)


class DuplicatePair(Base):
    """One candidate duplicate pair with its similarity breakdown."""

    __tablename__ = "duplicate_pairs"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id_a: Mapped[str] = mapped_column(ForeignKey("works.work_id"), index=True)
    work_id_b: Mapped[str] = mapped_column(ForeignKey("works.work_id"), index=True)
    dup_group_id: Mapped[str | None] = mapped_column(String(40), index=True)
    state: Mapped[str] = mapped_column(String(100), index=True)
    ida: Mapped[str] = mapped_column(String(200), index=True)
    mp_code: Mapped[str | None] = mapped_column(String(20), index=True)
    work_type: Mapped[str | None] = mapped_column(String(120))
    pair_score: Mapped[float] = mapped_column(Float, index=True)
    cosine: Mapped[float] = mapped_column(Float)
    token_set: Mapped[float] = mapped_column(Float)
    location_overlap: Mapped[float] = mapped_column(Float)
    amount_similarity: Mapped[float] = mapped_column(Float)
    days_apart: Mapped[float] = mapped_column(Float)
    shared_location_words: Mapped[str | None] = mapped_column(Text)
    is_standard_item: Mapped[bool] = mapped_column(Boolean, default=False)
    # Reviewer decision on this pair: None | duplicate | not_duplicate
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (UniqueConstraint("work_id_a", "work_id_b"),)


class SplitGroup(Base):
    __tablename__ = "split_groups"

    split_group_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    state: Mapped[str] = mapped_column(String(100), index=True)
    ida: Mapped[str] = mapped_column(String(200), index=True)
    mp_code: Mapped[str | None] = mapped_column(String(20), index=True)
    work_type: Mapped[str] = mapped_column(String(120))
    vendor_name: Mapped[str | None] = mapped_column(String(300))
    same_vendor: Mapped[bool] = mapped_column(Boolean, default=False)
    n_works: Mapped[int] = mapped_column(Integer)
    work_ids: Mapped[list] = mapped_column(JSON, default=list)
    total_amount: Mapped[float] = mapped_column(Float)
    split_score: Mapped[float] = mapped_column(Float, index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class MetricDoc(Base):
    """Documents such as models/metrics.json, stored whole."""

    __tablename__ = "metric_docs"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    body: Mapped[dict] = mapped_column(JSON, default=dict)
    loaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuditEvent(Base):
    """Append-only, hash-chained audit trail.

    ``hash = sha256(prev_hash + canonical_json(event))``, where the event
    includes its own sequence number. Editing, deleting or reordering any row
    breaks every hash after it, which ``backend.app.audit.verify`` detects.
    """

    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    ts: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(30), index=True)
    entity_id: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.alert_id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    author: Mapped[User] = relationship()


class Feedback(Base):
    """A reviewer verdict. Feeds the learning panel (Phase D)."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.alert_id"), index=True)
    work_id: Mapped[str | None] = mapped_column(String(80), index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verdict: Mapped[str] = mapped_column(String(30), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    # The channel values at the time of the verdict, so learning uses what the
    # reviewer actually saw.
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # "learn" or "evaluate": seeded verdicts are split so the learning panel
    # reports precision on verdicts it did not learn from.
    partition: Mapped[str] = mapped_column(String(10), default="learn")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Case(Base):
    """An investigation case grouping related alerts (Phase D)."""

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(
        String(30)
    )  # split_group | vendor | district_pattern | custom
    status: Mapped[str] = mapped_column(String(30), default="Open", index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    state: Mapped[str | None] = mapped_column(String(100), index=True)
    ida: Mapped[str | None] = mapped_column(String(200), index=True)
    mp_code: Mapped[str | None] = mapped_column(String(20), index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    owner: Mapped[User] = relationship()
    alerts: Mapped[list[CaseAlert]] = relationship(cascade="all, delete-orphan")
    notes: Mapped[list[CaseNote]] = relationship(cascade="all, delete-orphan")


class CaseAlert(Base):
    __tablename__ = "case_alerts"

    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True
    )
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.alert_id"), primary_key=True)


class CaseNote(Base):
    __tablename__ = "case_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    author: Mapped[User] = relationship()


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    committed: Mapped[bool] = mapped_column(Boolean, default=False)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ScoringRun(Base):
    """One pipeline load or nightly re-score, for "what changed" and the job log."""

    __tablename__ = "scoring_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # initial_load | nightly | manual
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    works_loaded: Mapped[int] = mapped_column(Integer, default=0)
    alerts_new: Mapped[int] = mapped_column(Integer, default=0)
    alerts_retired: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
