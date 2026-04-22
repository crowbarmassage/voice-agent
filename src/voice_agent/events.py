"""Typed domain events for the call lifecycle.

Events flow from subsystems (telephony, audio, IVR, hold handler, brain)
to the session manager, which uses them to drive state transitions.

All events carry a timestamp and session_id for correlation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventType(str, Enum):
    # Telephony
    CALL_STARTED = "call_started"
    CALL_ANSWERED = "call_answered"
    CALL_ENDED = "call_ended"
    CALL_FAILED = "call_failed"
    DTMF_SENT = "dtmf_sent"
    VOICEMAIL_DETECTED = "voicemail_detected"

    # IVR
    IVR_PROMPT_DETECTED = "ivr_prompt_detected"
    IVR_ACTION_TAKEN = "ivr_action_taken"
    IVR_NAVIGATION_COMPLETE = "ivr_navigation_complete"
    IVR_LOOP_DETECTED = "ivr_loop_detected"
    IVR_TIMEOUT = "ivr_timeout"

    # Hold
    HOLD_STARTED = "hold_started"
    HOLD_MESSAGE_DETECTED = "hold_message_detected"
    HOLD_TIMEOUT = "hold_timeout"
    HUMAN_DETECTED = "human_detected"

    # Transfer
    TRANSFER_DETECTED = "transfer_detected"
    TRANSFER_COMPLETED = "transfer_completed"

    # Conversation
    COUNTERPARTY_UTTERANCE = "counterparty_utterance"
    AGENT_UTTERANCE = "agent_utterance"
    ENTITY_EXTRACTED = "entity_extracted"
    ENTITY_VERIFIED = "entity_verified"
    BARGE_IN = "barge_in"

    # Script
    SCRIPT_GOAL_COMPLETED = "script_goal_completed"
    SCRIPT_COMPLETED = "script_completed"

    # Escalation
    ESCALATION_TRIGGERED = "escalation_triggered"

    # Compliance
    PHI_DISCLOSED = "phi_disclosed"

    # Session lifecycle
    SESSION_CREATED = "session_created"
    SESSION_STATE_CHANGED = "session_state_changed"


@dataclass
class CallEvent:
    """Base domain event. All events in the system inherit from this."""

    event_type: EventType
    session_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    work_item_id: str | None = None
    call_sid: str | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "work_item_id": self.work_item_id,
            "call_sid": self.call_sid,
            "details": self.details,
        }
