"""SQLAlchemy table definitions.

Tables:
    - work_items: call queue (pending → in_progress → completed/failed/retry)
    - call_sessions: one row per call attempt (tracks session state machine)
    - dispositions: post-call structured records
    - audit_log: immutable append-only compliance log (no UPDATE/DELETE)
    - payor_profiles: per-payor configuration (mirrors YAML for query access)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WorkItemRow(Base):
    """Work queue: each row is a claim/task needing an outbound call."""

    __tablename__ = "work_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    use_case: Mapped[str] = mapped_column(String(32), nullable=False)  # claim_status, etc.
    payor: Mapped[str] = mapped_column(String(128), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_work_items_status_priority", "status", "priority"),
        Index("ix_work_items_next_retry", "next_retry_at"),
    )


class CallSessionRow(Base):
    """One row per call attempt. Tracks the session state machine."""

    __tablename__ = "call_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    work_item_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    call_sid: Mapped[str | None] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pre_call")
    payor: Mapped[str] = mapped_column(String(128), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    from_number: Mapped[str | None] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold_duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    conversation_duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    recording_url: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class DispositionRow(Base):
    """Post-call disposition record. See TIER1_FEATURES.md §D1."""

    __tablename__ = "dispositions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    use_case: Mapped[str] = mapped_column(String(32), nullable=False)
    payor: Mapped[str] = mapped_column(String(128), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    extracted_entities: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    entities_verified: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    escalation_reason: Mapped[str | None] = mapped_column(String(64))
    rep_name: Mapped[str | None] = mapped_column(String(128))
    reference_number: Mapped[str | None] = mapped_column(String(64))
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    transcript: Mapped[str | None] = mapped_column(Text)
    recording_url: Mapped[str | None] = mapped_column(Text)
    retry_needed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_action: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    call_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    call_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold_duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    conversation_duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditLogRow(Base):
    """Immutable append-only audit log. No UPDATE or DELETE ever.

    See TIER1_FEATURES.md §E5.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    work_item_id: Mapped[str | None] = mapped_column(String(64), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    call_sid: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payor: Mapped[str | None] = mapped_column(String(128))
    phi_fields_disclosed: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_audit_log_ts_event", "timestamp", "event_type"),
    )


class PayorProfileRow(Base):
    """Per-payor configuration. Mirrors YAML for query access."""

    __tablename__ = "payor_profiles"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    phone_numbers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/New_York")
    business_hours: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    max_hold_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    max_concurrent_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    ai_disclosure_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ivr_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
