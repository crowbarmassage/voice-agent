"""Immutable audit log.

Append-only log of all call events: timestamps, work item IDs, PHI
fields accessed, PHI fields disclosed, outcomes, escalation events.

Backed by Postgres with append-only semantics (no UPDATE/DELETE on
audit rows). Queryable for compliance audits.

See docs/TIER1_FEATURES.md §E5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AuditEntry:
    """A single audit log entry."""

    timestamp: datetime
    work_item_id: str
    event_type: str  # call_started, phi_disclosed, entity_extracted, escalated, call_ended
    payor: str
    phi_fields_disclosed: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
