"""Session state machine tests.

Validates that the session state machine enforces valid transitions
and rejects invalid ones.
"""
import pytest

from voice_agent.session import (
    InvalidSessionTransition,
    Session,
    SessionState,
    VALID_SESSION_TRANSITIONS,
)


def _make_session(**kwargs) -> Session:
    defaults = {
        "work_item_id": "wi_001",
        "use_case": "claim_status",
        "payor": "UHC",
        "phone_number": "+18005551234",
        "context": {"patient_name": "Jane Doe"},
    }
    defaults.update(kwargs)
    return Session(**defaults)


class TestSessionTransitionTable:
    """Verify the transition table is correct."""

    def test_pre_call_can_dial(self):
        assert SessionState.DIALING in VALID_SESSION_TRANSITIONS[SessionState.PRE_CALL]

    def test_pre_call_can_fail(self):
        assert SessionState.FAILED in VALID_SESSION_TRANSITIONS[SessionState.PRE_CALL]

    def test_pre_call_cannot_skip_to_conversation(self):
        assert SessionState.CONVERSATION not in VALID_SESSION_TRANSITIONS[SessionState.PRE_CALL]

    def test_dialing_can_reach_ivr_or_conversation(self):
        targets = VALID_SESSION_TRANSITIONS[SessionState.DIALING]
        assert SessionState.IVR in targets
        assert SessionState.CONVERSATION in targets

    def test_terminal_states_have_no_transitions(self):
        assert VALID_SESSION_TRANSITIONS[SessionState.DONE] == set()
        assert VALID_SESSION_TRANSITIONS[SessionState.FAILED] == set()

    def test_hold_can_return_to_conversation(self):
        assert SessionState.CONVERSATION in VALID_SESSION_TRANSITIONS[SessionState.HOLD]

    def test_conversation_can_go_to_hold(self):
        assert SessionState.HOLD in VALID_SESSION_TRANSITIONS[SessionState.CONVERSATION]

    def test_conversation_can_go_to_post_call(self):
        assert SessionState.POST_CALL in VALID_SESSION_TRANSITIONS[SessionState.CONVERSATION]


class TestSessionStateMachine:
    """Integration tests for the Session state machine."""

    def test_initial_state_is_pre_call(self):
        s = _make_session()
        assert s.state == SessionState.PRE_CALL

    def test_happy_path(self):
        """pre_call → dialing → ivr → hold → conversation → post_call → done"""
        s = _make_session()
        s.transition_to(SessionState.DIALING)
        s.transition_to(SessionState.IVR)
        s.transition_to(SessionState.HOLD)
        s.transition_to(SessionState.CONVERSATION)
        s.transition_to(SessionState.POST_CALL)
        s.transition_to(SessionState.DONE)
        assert s.state == SessionState.DONE
        assert s.is_terminal

    def test_direct_to_conversation(self):
        """Some calls skip IVR: dialing → conversation."""
        s = _make_session()
        s.transition_to(SessionState.DIALING)
        s.transition_to(SessionState.CONVERSATION)
        assert s.state == SessionState.CONVERSATION

    def test_invalid_transition_raises(self):
        s = _make_session()
        with pytest.raises(InvalidSessionTransition) as exc_info:
            s.transition_to(SessionState.CONVERSATION)
        assert exc_info.value.from_state == SessionState.PRE_CALL
        assert exc_info.value.to_state == SessionState.CONVERSATION

    def test_cannot_transition_from_terminal(self):
        s = _make_session()
        s.transition_to(SessionState.FAILED)
        with pytest.raises(InvalidSessionTransition):
            s.transition_to(SessionState.DIALING)

    def test_fail_method(self):
        s = _make_session()
        s.transition_to(SessionState.DIALING)
        s.fail("busy signal")
        assert s.state == SessionState.FAILED
        assert s.error == "busy signal"
        assert s.is_terminal

    def test_state_history_tracked(self):
        s = _make_session()
        s.transition_to(SessionState.DIALING)
        s.transition_to(SessionState.IVR)
        states = [st for st, _ in s.state_history]
        assert states == [SessionState.PRE_CALL, SessionState.DIALING, SessionState.IVR]

    def test_hold_duration_tracked(self):
        import time
        s = _make_session()
        s.transition_to(SessionState.DIALING)
        s.transition_to(SessionState.HOLD)
        time.sleep(0.05)
        s.transition_to(SessionState.CONVERSATION)
        assert s.total_hold_s >= 0.04  # at least 40ms

    def test_events_emitted(self):
        s = _make_session()
        s.transition_to(SessionState.DIALING)
        # SESSION_CREATED + SESSION_STATE_CHANGED
        assert len(s.events) >= 2
        event_types = [e.event_type.value for e in s.events]
        assert "session_created" in event_types
        assert "session_state_changed" in event_types

    def test_session_id_generated(self):
        s = _make_session()
        assert s.id.startswith("sess_")

    def test_custom_session_id(self):
        s = _make_session(session_id="custom_123")
        assert s.id == "custom_123"

    def test_hold_then_conversation_then_hold_again(self):
        """Rep can put us back on hold mid-conversation."""
        s = _make_session()
        s.transition_to(SessionState.DIALING)
        s.transition_to(SessionState.HOLD)
        s.transition_to(SessionState.CONVERSATION)
        s.transition_to(SessionState.HOLD)
        s.transition_to(SessionState.CONVERSATION)
        assert s.state == SessionState.CONVERSATION
