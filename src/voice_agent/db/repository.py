"""Queue repository — state machine for work items with guarded transitions.

Valid transitions:
    pending       → in_progress
    in_progress   → completed | failed | retry_scheduled
    retry_scheduled → in_progress
    failed        → retry_scheduled | human_required
    retry_scheduled → human_required  (when max retries exhausted)

All writes go through this layer to enforce transition rules.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from voice_agent.db.tables import (
    AuditLogRow,
    CallSessionRow,
    DispositionRow,
    WorkItemRow,
)

# Valid state transitions: {from_state: {to_states}}
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress"},
    "in_progress": {"completed", "failed", "retry_scheduled"},
    "retry_scheduled": {"in_progress", "human_required"},
    "failed": {"retry_scheduled", "human_required"},
}

# Backoff schedule: retry_count → delay
BACKOFF_SCHEDULE = {
    0: timedelta(minutes=30),
    1: timedelta(hours=2),
    2: timedelta(days=1),
    3: timedelta(days=2),
}


class InvalidTransitionError(Exception):
    """Raised when a work item state transition is not allowed."""

    def __init__(self, work_item_id: str, from_status: str, to_status: str):
        self.work_item_id = work_item_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Invalid transition for work_item {work_item_id}: "
            f"{from_status} → {to_status}"
        )


class QueueRepository:
    """Work queue operations with guarded state transitions."""

    def __init__(self, session: Session):
        self._session = session

    def pull_next(self, use_case: str | None = None) -> WorkItemRow | None:
        """Pull the next pending work item (highest priority, oldest first).

        Atomically sets status to in_progress so no other agent picks it up.
        """
        stmt = (
            select(WorkItemRow)
            .where(WorkItemRow.status == "pending")
            .order_by(WorkItemRow.priority.desc(), WorkItemRow.created_at.asc())
        )
        if use_case:
            stmt = stmt.where(WorkItemRow.use_case == use_case)
        stmt = stmt.limit(1).with_for_update(skip_locked=True)

        item = self._session.execute(stmt).scalar_one_or_none()
        if item:
            self._transition(item, "in_progress")
            self._session.commit()
        return item

    def pull_retries_due(self) -> list[WorkItemRow]:
        """Pull all retry_scheduled items whose next_retry_at has passed."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(WorkItemRow)
            .where(
                WorkItemRow.status == "retry_scheduled",
                WorkItemRow.next_retry_at <= now,
            )
            .order_by(WorkItemRow.priority.desc(), WorkItemRow.next_retry_at.asc())
            .with_for_update(skip_locked=True)
        )
        items = list(self._session.execute(stmt).scalars().all())
        for item in items:
            self._transition(item, "in_progress")
        if items:
            self._session.commit()
        return items

    def complete(self, work_item_id: str) -> None:
        """Mark a work item as completed."""
        item = self._get(work_item_id)
        self._transition(item, "completed")
        self._session.commit()

    def fail(self, work_item_id: str) -> None:
        """Mark a work item as failed. Schedules retry if under max_retries."""
        item = self._get(work_item_id)
        self._transition(item, "failed")
        self._session.commit()

        # Auto-schedule retry if under limit
        if item.retry_count < item.max_retries:
            self.schedule_retry(work_item_id)
        else:
            self._transition(item, "human_required")
            self._session.commit()

    def schedule_retry(self, work_item_id: str) -> None:
        """Schedule a retry with backoff."""
        item = self._get(work_item_id)
        if item.status not in ("failed", "retry_scheduled"):
            # Allow scheduling from failed state
            if item.status == "in_progress":
                self._transition(item, "failed")

        if item.retry_count >= item.max_retries:
            self._transition(item, "human_required")
            self._session.commit()
            return

        delay = BACKOFF_SCHEDULE.get(
            item.retry_count, timedelta(days=2)
        )
        item.retry_count += 1
        item.next_retry_at = datetime.now(timezone.utc) + delay
        item.status = "retry_scheduled"
        self._session.commit()

    def mark_human_required(self, work_item_id: str) -> None:
        """Escalate to human — no more retries."""
        item = self._get(work_item_id)
        self._transition(item, "human_required")
        self._session.commit()

    def _get(self, work_item_id: str) -> WorkItemRow:
        item = self._session.get(WorkItemRow, work_item_id)
        if not item:
            raise ValueError(f"Work item not found: {work_item_id}")
        return item

    def _transition(self, item: WorkItemRow, to_status: str) -> None:
        allowed = VALID_TRANSITIONS.get(item.status, set())
        if to_status not in allowed:
            raise InvalidTransitionError(item.id, item.status, to_status)
        item.status = to_status


class AuditRepository:
    """Append-only audit log writer. No update or delete methods."""

    def __init__(self, session: Session):
        self._session = session

    def append(
        self,
        event_type: str,
        *,
        work_item_id: str | None = None,
        session_id: str | None = None,
        call_sid: str | None = None,
        payor: str | None = None,
        phi_fields_disclosed: list[str] | None = None,
        details: dict | None = None,
    ) -> AuditLogRow:
        """Append an audit entry. Returns the created row."""
        row = AuditLogRow(
            event_type=event_type,
            work_item_id=work_item_id,
            session_id=session_id,
            call_sid=call_sid,
            payor=payor,
            phi_fields_disclosed=phi_fields_disclosed or [],
            details=details or {},
        )
        self._session.add(row)
        self._session.commit()
        return row


class DispositionRepository:
    """Disposition record writer."""

    def __init__(self, session: Session):
        self._session = session

    def create(self, **kwargs) -> DispositionRow:
        row = DispositionRow(**kwargs)
        self._session.add(row)
        self._session.commit()
        return row


class SessionRepository:
    """Call session record writer."""

    def __init__(self, session: Session):
        self._session = session

    def create(self, **kwargs) -> CallSessionRow:
        row = CallSessionRow(**kwargs)
        self._session.add(row)
        self._session.commit()
        return row

    def update_state(self, session_id: str, state: str, **kwargs) -> CallSessionRow:
        row = self._session.get(CallSessionRow, session_id)
        if not row:
            raise ValueError(f"Call session not found: {session_id}")
        row.state = state
        for k, v in kwargs.items():
            setattr(row, k, v)
        self._session.commit()
        return row
