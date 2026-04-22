"""Shared data models — disposition records, call events, payor config.

Pydantic models for structured data that flows between components.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class CallOutcome(str, Enum):
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"
    VOICEMAIL = "voicemail"
    NO_ANSWER = "no_answer"
    IVR_FAILURE = "ivr_failure"
    HOLD_TIMEOUT = "hold_timeout"


class Disposition(BaseModel):
    """Post-call disposition record. See TIER1_FEATURES.md §D1."""

    work_item_id: str
    use_case: str
    payor: str
    phone_number: str
    call_start: datetime
    call_end: datetime
    hold_duration_s: float = 0
    conversation_duration_s: float = 0
    outcome: CallOutcome
    extracted_entities: dict = Field(default_factory=dict)
    entities_verified: list[str] = Field(default_factory=list)
    escalation_reason: str | None = None
    rep_name: str | None = None
    reference_number: str | None = None
    confidence_score: float = 0.0
    recording_path: str | None = None
    retry_needed: bool = False
    next_action: str = "none"  # none | retry | human_review


class PayorProfile(BaseModel):
    """Per-payor configuration loaded from config/payors/*.yaml."""

    name: str
    phone_numbers: dict[str, str] = Field(
        default_factory=dict,
        description="Department → phone number mapping (claims, eligibility, auth, etc.)",
    )
    timezone: str = "America/New_York"
    business_hours: dict = Field(
        default_factory=lambda: {"start": "08:00", "end": "18:00", "days": "mon-fri"},
    )
    max_hold_minutes: int = 90
    max_concurrent_calls: int = 5
    ai_disclosure_required: bool = True
    ivr_map_file: str | None = None  # path to IVR state machine definition
    notes: str = ""  # known quirks
