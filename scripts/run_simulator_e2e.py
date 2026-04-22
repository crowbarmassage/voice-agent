"""End-to-end test: run a session against the call simulator.

Starts the simulator server, connects a SessionRunner to it, and runs
a complete call scenario. Proves the full stack works: Session state
machine → MediaStreamClient → AudioPipeline → VAD → (optional STT).

Usage:
    python scripts/run_simulator_e2e.py
    python scripts/run_simulator_e2e.py --scenario ivr_loop
    python scripts/run_simulator_e2e.py --with-stt  # requires Granite model
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
    """Start the simulator WebSocket server in the background."""
    import websockets
    from simulator.server import handle_connection

    async def handler(websocket):
        results = await handle_connection(websocket, scenario)
        return results

    async with websockets.serve(handler, "localhost", port):
        log.info("simulator_ready", port=port, scenario=scenario)
        ready.set()
        await asyncio.Future()  # run forever (cancelled externally)


async def run_e2e(scenario: str, port: int, with_stt: bool = False) -> None:
    """Run end-to-end: start simulator + connect session runner."""
    configure_logging(json=False)

    # Start simulator server
    ready = asyncio.Event()
    server_task = asyncio.create_task(
        run_simulator_server(scenario, port, ready),
        name="simulator_server",
    )

    await ready.wait()
    log.info("simulator_started")

    # Create session
    session = Session(
        work_item_id="wi_e2e_test",
        use_case="claim_status",
        payor="TestPayor",
        phone_number="+18005551234",
        context={"patient_name": "Jane Doe", "dob": "1985-03-15"},
    )

    # Optionally load STT
    stt = None
    if with_stt:
        from voice_agent.stt.granite import GraniteSTT
        stt = GraniteSTT()
        await stt.start()

    # Create and run session runner
    ws_url = f"ws://localhost:{port}"
    runner = SessionRunner(session, ws_url, stt=stt)

    print(f"\n{'='*60}")
    print(f"E2E Test: {scenario}")
    print(f"Session: {session.id}")
    print(f"Simulator: {ws_url}")
    print(f"STT: {'Granite' if with_stt else 'disabled'}")
    print(f"{'='*60}\n")

    try:
        # Give the runner a timeout — scenarios shouldn't take forever
        await asyncio.wait_for(runner.run(), timeout=120.0)
    except asyncio.TimeoutError:
        log.warning("e2e_timeout")
        session.fail("timeout")

    # Results
    print(f"\n{'='*60}")
    print(f"Session final state: {session.state.value}")
    print(f"State history:")
    for state, ts in session.state_history:
        print(f"  {state.value:15s}  {ts.isoformat()}")
    print(f"Hold duration:        {session.total_hold_s:.1f}s")
    print(f"Conversation duration: {session.total_conversation_s:.1f}s")
    print(f"Total duration:       {session.duration_s():.1f}s")
    print(f"Events:               {len(session.events)}")

    if runner.transcripts:
        print(f"\nTranscripts ({len(runner.transcripts)}):")
        for t in runner.transcripts:
            print(f"  [{t.confidence:.2f}] {t.text[:80]}")

    print(f"\nCall SID: {session.call_sid}")
    if session.error:
        print(f"Error: {session.error}")
    print(f"{'='*60}\n")

    # Cleanup
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass

    if stt:
        await stt.stop()


def main():
    from simulator.scenarios import SCENARIOS

    parser = argparse.ArgumentParser(description="E2E test: session vs simulator")
    parser.add_argument(
        "--scenario", "-s",
        default="happy_path",
        choices=list(SCENARIOS.keys()),
    )
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--with-stt",
        action="store_true",
        help="Enable Granite STT (requires model weights)",
    )
    args = parser.parse_args()

    asyncio.run(run_e2e(args.scenario, args.port, args.with_stt))


if __name__ == "__main__":
    main()
