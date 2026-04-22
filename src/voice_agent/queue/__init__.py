"""Work queue manager.

Manages the lifecycle of work items: pending → in_progress → completed/failed/retry.
Each work item is a claim or task that needs an outbound call.

Backed by Postgres for durability. Supports: pull next item, mark in_progress,
log disposition, schedule retry with backoff, idempotent completion.

See docs/TIER1_FEATURES.md §A1, §D3, §D5.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class WorkItemStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"
    HUMAN_REQUIRED = "human_required"


@dataclass
class WorkItem:
    """A single item in the call queue."""

    id: str
    use_case: str  # claim_status, eligibility, auth_status, fax_lookup
    payor: str
    phone_number: str
    context: dict  # claim context payload (patient, claim #, etc.)
    status: WorkItemStatus
    retry_count: int = 0
    max_retries: int = 3
    next_retry_at: datetime | None = None
    created_at: datetime | None = None
