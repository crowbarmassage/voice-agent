"""End-to-end test: run a full autonomous call against the simulator.

Starts the simulator, connects a SessionRunner with IVR navigator + Gemini
brain + optional STT, and runs a complete call scenario autonomously.

Usage:
    python scripts/run_simulator_e2e.py
    python scripts/run_simulator_e2e.py --scenario ivr_loop
    python scripts/run_simulator_e2e.py --with-brain  # enable Gemini brain
    python scripts/run_simulator_e2e.py --with-stt    # enable Granite STT
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_agent.logging import configure_logging, get_logger
from voice_agent.session import Session, SessionState
from voice_agent.runner import SessionRunner

log = get_logger(__name__)

DEFAULT_PORT = 8765


async def run_simulator_server(scenario: str, port: int, ready: asyncio.Event) -> None:
    import websockets
    from simulator.server import handle_connection

    async def handler(websocket):
        await handle_connection(websocket, scenario)

    async with websockets.serve(handler, "localhost", port):
        log.info("simulator_ready", port=port, scenario=scenario)
        ready.set()
        await asyncio.Future()


async def run_e2e(
    scenario: str,
    port: int,
    with_stt: bool = False,
    with_brain: bool = False,
) -> None:
    configure_logging(json=False)

    # Start simulator
    ready = asyncio.Event()
    server_task = asyncio.create_task(
        run_simulator_server(scenario, port, ready),
    )
    await ready.wait()

    # Create session with full claim context
    session = Session(
        work_item_id="wi_e2e_test",
        use_case="claim_status",
        payor="UHC",
        phone_number="+18005551234",
        context={
            "patient_name": "Jane Doe",
            "dob": "1985-03-15",
            "member_id": "MBR123456",
            "claim_number": "CLM-2026-001",
            "date_of_service": "2026-04-01",
            "npi": "1234567890",
            "tax_id": "123456789",
        },
    )

    # Build IVR config for UHC
    from voice_agent.ivr import IVRActionType, IVRConfig, IVRRule
    ivr_config = IVRConfig(
        payor="UHC",
        department="claims",
        rules=[
            IVRRule("press 1 for claims", IVRActionType.DTMF, "1"),
            IVRRule("press 2 for eligibility", IVRActionType.DTMF, "2"),
            IVRRule("enter your npi", IVRActionType.DTMF, "{npi}"),
            IVRRule("enter your tax id", IVRActionType.DTMF, "{tax_id}"),
        ],
    )

    # Build claim status script
    from voice_agent.scripts.claim_status import create_claim_status_script
    script = create_claim_status_script("Riverside Medical", "1234567890", "12-3456789")

    # Optional: Gemini brain
    brain = None
    if with_brain:
        from voice_agent.brain.gemini import GeminiBrain
        brain = GeminiBrain()
        log.info("brain_enabled", model="gemini-3.1-flash-lite-preview")

    # Optional: Granite STT
    stt = None
    if with_stt:
        from voice_agent.stt.granite import GraniteSTT
        stt = GraniteSTT()
        await stt.start()

    # Create and run
    ws_url = f"ws://localhost:{port}"
    runner = SessionRunner(
        session, ws_url,
        stt=stt,
        brain=brain,
        script=script,
        ivr_config=ivr_config,
    )

    print(f"\n{'='*60}")
    print(f"E2E Test: {scenario}")
    print(f"Session: {session.id}")
    print(f"Brain: {'Gemini' if with_brain else 'disabled'}")
    print(f"STT: {'Granite' if with_stt else 'disabled'}")
    print(f"IVR: UHC claims rules loaded")
    print(f"{'='*60}\n")

    try:
        await asyncio.wait_for(runner.run(), timeout=180.0)
    except asyncio.TimeoutError:
        log.warning("e2e_timeout")
        if not session.is_terminal:
            session.fail("timeout")

    # Results
    print(f"\n{'='*60}")
    print(f"Session final state: {session.state.value}")
    print(f"\nState history:")
    for state, ts in session.state_history:
        print(f"  {state.value:15s}  {ts.isoformat()}")
    print(f"\nHold duration:        {session.total_hold_s:.1f}s")
    print(f"Conversation duration: {session.total_conversation_s:.1f}s")
    print(f"Total duration:       {session.duration_s():.1f}s")
    print(f"Events:               {len(session.events)}")

    if runner.conversation_history:
        print(f"\nConversation ({len(runner.conversation_history)} turns):")
        for turn in runner.conversation_history:
            role = "REP" if turn.role == "counterparty" else "AGENT"
            print(f"  [{role:5s}] {turn.text[:100]}")

    if runner.transcripts:
        print(f"\nRaw transcripts ({len(runner.transcripts)}):")
        for t in runner.transcripts:
            print(f"  [{t.confidence:.2f}] {t.text[:80]}")

    print(f"\nCall SID: {session.call_sid}")
    if session.error:
        print(f"Error: {session.error}")
    print(f"{'='*60}\n")

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
    if stt:
        await stt.stop()


def main():
    from simulator.scenarios import SCENARIOS

    parser = argparse.ArgumentParser(description="E2E: autonomous call vs simulator")
    parser.add_argument("--scenario", "-s", default="happy_path", choices=list(SCENARIOS.keys()))
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    parser.add_argument("--with-stt", action="store_true", help="Enable Granite STT")
    parser.add_argument("--with-brain", action="store_true", help="Enable Gemini brain")
    args = parser.parse_args()
    asyncio.run(run_e2e(args.scenario, args.port, args.with_stt, args.with_brain))


if __name__ == "__main__":
    main()
