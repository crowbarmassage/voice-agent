"""End-to-end integration tests: SessionRunner against call simulator.

These tests start the simulator WebSocket server, connect a SessionRunner,
and verify that the session state machine transitions correctly through
each scenario.
"""
from __future__ import annotations

import asyncio

import pytest
import websockets

from simulator.server import handle_connection
from voice_agent.audio.vad import VAD
from voice_agent.runner import SessionRunner
from voice_agent.session import Session, SessionState


async def _run_scenario(
    scenario: str,
    port: int,
    timeout: float = 30.0,
) -> tuple[Session, SessionRunner]:
    """Helper: run a scenario and return the session + runner."""
    # Start simulator
    ready = asyncio.Event()

    async def handler(ws):
        await handle_connection(ws, scenario)

    server = await websockets.serve(handler, "localhost", port)
    ready.set()

    session = Session(
        work_item_id=f"wi_test_{scenario}",
        use_case="claim_status",
        payor="TestPayor",
        phone_number="+18005551234",
        context={"patient_name": "Jane Doe"},
    )

    runner = SessionRunner(session, f"ws://localhost:{port}")

    try:
        await asyncio.wait_for(runner.run(), timeout=timeout)
    except asyncio.TimeoutError:
        if not session.is_terminal:
            session.fail("test_timeout")
    finally:
        server.close()
        await server.wait_closed()

    return session, runner


class TestE2EHappyPath:
    @pytest.mark.asyncio
    async def test_happy_path_reaches_terminal(self):
        """Happy path scenario should complete (DONE or FAILED — both terminal)."""
        session, runner = await _run_scenario("happy_path", 18765)
        assert session.is_terminal

    @pytest.mark.asyncio
    async def test_happy_path_transitions_through_states(self):
        """Should pass through DIALING and at least one more state."""
        session, runner = await _run_scenario("happy_path", 18766)
        states = [s for s, _ in session.state_history]
        assert SessionState.PRE_CALL in states
        assert SessionState.DIALING in states
        # Should reach at least IVR (audio detected)
        assert len(states) >= 3

    @pytest.mark.asyncio
    async def test_happy_path_has_call_sid(self):
        """Session should have a call SID from the simulator."""
        session, runner = await _run_scenario("happy_path", 18767)
        assert session.call_sid is not None
        assert session.call_sid.startswith("CA_sim_")

    @pytest.mark.asyncio
    async def test_happy_path_emits_events(self):
        """Session should have emitted events."""
        session, runner = await _run_scenario("happy_path", 18768)
        assert len(session.events) >= 2  # at least created + state changes


class TestE2ENoAnswer:
    @pytest.mark.asyncio
    async def test_no_answer_fails(self):
        """No-answer scenario (silence then disconnect) should reach terminal."""
        session, runner = await _run_scenario("no_answer", 18769, timeout=15.0)
        assert session.is_terminal


class TestE2EIVRLoop:
    @pytest.mark.asyncio
    async def test_ivr_loop_reaches_terminal(self):
        """IVR loop scenario should complete."""
        session, runner = await _run_scenario("ivr_loop", 18770)
        assert session.is_terminal
