"""Session manager — orchestrates the lifecycle of a single outbound call.

One Session instance per active call. Manages the state machine:
    pre_call → dialing → ivr → hold → conversation → post_call → done | failed

Holds: claim context, conversation history, extracted entities, script state,
telephony handle, audio streams.

State machine transitions are guarded — only valid transitions are allowed.
Events (from events.py) drive transitions.

See docs/TIER1_FEATURES.md §F1.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from voice_agent.events import CallEvent, EventType
from voice_agent.logging import get_logger
from voice_agent.metrics import metrics

log = get_logger(__name__)


class SessionState(str, Enum):
    PRE_CALL = "pre_call"
    DIALING = "dialing"
    IVR = "ivr"
    HOLD = "hold"
    CONVERSATION = "conversation"
    POST_CALL = "post_call"
    DONE = "done"
    FAILED = "failed"


# Valid state transitions: {from_state: {to_states}}
VALID_SESSION_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.PRE_CALL: {SessionState.DIALING, SessionState.FAILED},
    SessionState.DIALING: {
        SessionState.IVR,
        SessionState.HOLD,
        SessionState.CONVERSATION,
        SessionState.FAILED,
    },
    SessionState.IVR: {
        SessionState.HOLD,
        SessionState.CONVERSATION,
        SessionState.FAILED,
    },
    SessionState.HOLD: {
        SessionState.CONVERSATION,
        SessionState.IVR,  # transfer back to IVR
        SessionState.FAILED,
    },
    SessionState.CONVERSATION: {
        SessionState.HOLD,  # rep puts us on hold mid-conversation
        SessionState.POST_CALL,
        SessionState.FAILED,
    },
    SessionState.POST_CALL: {SessionState.DONE, SessionState.FAILED},
    # Terminal states — no transitions out
    SessionState.DONE: set(),
    SessionState.FAILED: set(),
}


class InvalidSessionTransition(Exception):
    def __init__(self, session_id: str, from_state: SessionState, to_state: SessionState):
        self.session_id = session_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid session transition {session_id}: {from_state.value} → {to_state.value}"
        )


class Session:
    """Single-call session orchestrator with guarded state machine."""

    def __init__(
        self,
        work_item_id: str,
        use_case: str,
        payor: str,
        phone_number: str,
        context: dict,
        *,
        from_number: str | None = None,
        session_id: str | None = None,
    ):
        self.id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        self.work_item_id = work_item_id
        self.use_case = use_case
        self.payor = payor
        self.phone_number = phone_number
        self.from_number = from_number
        self.context = context

        self._state = SessionState.PRE_CALL
        self._state_history: list[tuple[SessionState, datetime]] = [
            (SessionState.PRE_CALL, datetime.now(timezone.utc))
        ]

        # Call metadata
        self.call_sid: str | None = None
        self.started_at: datetime = datetime.now(timezone.utc)
        self.answered_at: datetime | None = None
        self.ended_at: datetime | None = None
        self.hold_start: datetime | None = None
        self.total_hold_s: float = 0
        self.conversation_start: datetime | None = None
        self.total_conversation_s: float = 0
        self.recording_url: str | None = None
        self.error: str | None = None

        # Conversation state
        self.history: list[dict] = []
        self.extracted_entities: list[dict] = []
        self.events: list[CallEvent] = []

        self._log = log.bind(session_id=self.id, work_item_id=work_item_id)
        self._emit_event(EventType.SESSION_CREATED)

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in (SessionState.DONE, SessionState.FAILED)

    @property
    def state_history(self) -> list[tuple[SessionState, datetime]]:
        return list(self._state_history)

    def transition_to(self, new_state: SessionState, *, reason: str = "") -> None:
        """Transition to a new state. Raises if the transition is invalid."""
        allowed = VALID_SESSION_TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            raise InvalidSessionTransition(self.id, self._state, new_state)

        old_state = self._state
        now = datetime.now(timezone.utc)

        # Track hold/conversation durations on exit
        if old_state == SessionState.HOLD and self.hold_start:
            self.total_hold_s += (now - self.hold_start).total_seconds()
            self.hold_start = None
        if old_state == SessionState.CONVERSATION and self.conversation_start:
            self.total_conversation_s += (now - self.conversation_start).total_seconds()
            self.conversation_start = None

        # Track timing on entry
        if new_state == SessionState.HOLD:
            self.hold_start = now
        if new_state == SessionState.CONVERSATION:
            self.conversation_start = now
            if self.answered_at is None:
                self.answered_at = now
        if new_state in (SessionState.DONE, SessionState.FAILED):
            self.ended_at = now

        self._state = new_state
        self._state_history.append((new_state, now))

        self._log.info(
            "session_state_changed",
            from_state=old_state.value,
            to_state=new_state.value,
            reason=reason,
        )
        self._emit_event(
            EventType.SESSION_STATE_CHANGED,
            details={
                "from_state": old_state.value,
                "to_state": new_state.value,
                "reason": reason,
            },
        )
        metrics.inc("session_transitions", from_state=old_state.value, to_state=new_state.value)

    def fail(self, error: str) -> None:
        """Transition to FAILED state with an error message."""
        self.error = error
        self.transition_to(SessionState.FAILED, reason=error)

    def _emit_event(self, event_type: EventType, details: dict | None = None) -> CallEvent:
        event = CallEvent(
            event_type=event_type,
            session_id=self.id,
            work_item_id=self.work_item_id,
            call_sid=self.call_sid,
            details=details or {},
        )
        self.events.append(event)
        return event

    def duration_s(self) -> float:
        """Total session duration in seconds."""
        end = self.ended_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()
