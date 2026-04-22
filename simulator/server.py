"""WebSocket server that mimics Twilio Media Streams protocol.

Accepts a connection from the voice agent, replays a scripted call scenario
(IVR prompts, hold music, rep dialogue), receives the agent's audio/DTMF
responses, and validates them against expected actions.

Speaks the exact same WebSocket JSON protocol as Twilio Media Streams:
    Inbound (server → agent):
        - {"event": "connected", "protocol": "Call", "version": "1.0.0"}
        - {"event": "start", "streamSid": "...", "start": {"callSid": "...", ...}}
        - {"event": "media", "media": {"payload": "<base64 μ-law>"}}
        - {"event": "stop"}

    Outbound (agent → server):
        - {"event": "media", "media": {"payload": "<base64 μ-law>"}}
        - {"event": "dtmf", "dtmf": {"digit": "1"}}  (non-standard, for testing)
        - {"event": "mark", "mark": {"name": "..."}}
        - {"event": "clear"}

Run: python -m simulator.server --scenario happy_path --port 8765
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from voice_agent.audio.codec import (
    ULAW_SAMPLE_RATE,
    base64_encode,
    ulaw_encode,
)
from voice_agent.logging import configure_logging, get_logger

log = get_logger(__name__)


def _text_to_ulaw_frames(text: str, words_per_second: float = 2.5) -> list[str]:
    """Generate synthetic audio frames for spoken text.

    Since we don't have a TTS engine in the simulator, we generate
    a simple tone pattern that represents speech. The duration is
    estimated from word count. Each frame is 20ms of G.711 μ-law
    audio, base64 encoded.

    For real testing, replace this with pre-recorded WAV files or
    pipe through a TTS engine.
    """
    word_count = len(text.split())
    duration_s = max(1.0, word_count / words_per_second)
    num_frames = int(duration_s * (ULAW_SAMPLE_RATE / 160))  # 160 samples per 20ms

    frames = []
    for i in range(num_frames):
        t = np.linspace(
            i * 160 / ULAW_SAMPLE_RATE,
            (i + 1) * 160 / ULAW_SAMPLE_RATE,
            160,
            dtype=np.float32,
        )
        # Mix of tones to simulate speech-like audio
        audio = 0.1 * (
            np.sin(2 * np.pi * 200 * t)
            + 0.5 * np.sin(2 * np.pi * 400 * t)
            + 0.3 * np.sin(2 * np.pi * 150 * t * (1 + 0.1 * np.sin(2 * np.pi * 3 * t)))
        )
        ulaw = ulaw_encode(audio)
        frames.append(base64_encode(ulaw))
    return frames


def _silence_frames(duration_s: float) -> list[str]:
    """Generate silence frames (near-zero audio)."""
    num_frames = int(duration_s * (ULAW_SAMPLE_RATE / 160))
    silence = np.zeros(160, dtype=np.float32)
    ulaw = ulaw_encode(silence)
    b64 = base64_encode(ulaw)
    return [b64] * num_frames


def _hold_music_frames(duration_s: float) -> list[str]:
    """Generate hold music pattern: quiet repeating tone."""
    num_frames = int(duration_s * (ULAW_SAMPLE_RATE / 160))
    frames = []
    for i in range(num_frames):
        t = np.linspace(
            i * 160 / ULAW_SAMPLE_RATE,
            (i + 1) * 160 / ULAW_SAMPLE_RATE,
            160,
            dtype=np.float32,
        )
        # Gentle hold music: quiet sine with slow modulation
        audio = 0.03 * np.sin(2 * np.pi * 440 * t) * (
            0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * t[0])
        )
        ulaw = ulaw_encode(audio)
        frames.append(base64_encode(ulaw))
    return frames


class CallSimulator:
    """Simulates a payor phone system for development and testing.

    Runs a scenario step-by-step over a WebSocket connection, sending
    audio and waiting for agent responses.
    """

    def __init__(self, scenario_name: str = "happy_path"):
        from simulator.scenarios import SCENARIOS

        if scenario_name not in SCENARIOS:
            raise ValueError(
                f"Unknown scenario: {scenario_name}. "
                f"Available: {', '.join(SCENARIOS.keys())}"
            )
        self.scenario = SCENARIOS[scenario_name]
        self.call_sid = f"CA_sim_{uuid.uuid4().hex[:12]}"
        self.stream_sid = f"MZ_sim_{uuid.uuid4().hex[:12]}"
        self._received_dtmf: list[str] = []
        self._received_audio_frames = 0
        self._agent_spoke = False
        self._log = log.bind(scenario=scenario_name, call_sid=self.call_sid)

    async def run(self, websocket) -> dict:
        """Run the scenario over the given WebSocket connection.

        Returns a summary dict with results.
        """
        self._log.info("scenario_start", payor=self.scenario.payor)
        results = {
            "scenario": self.scenario.name,
            "call_sid": self.call_sid,
            "steps_completed": 0,
            "steps_total": len(self.scenario.steps),
            "dtmf_received": [],
            "agent_audio_frames": 0,
            "errors": [],
        }

        # Send connected event
        await websocket.send(json.dumps({
            "event": "connected",
            "protocol": "Call",
            "version": "1.0.0",
        }))

        # Send start event
        await websocket.send(json.dumps({
            "event": "start",
            "streamSid": self.stream_sid,
            "start": {
                "callSid": self.call_sid,
                "accountSid": "AC_simulator",
                "from": "+15551234567",
                "to": "+18005551234",
                "mediaFormat": {
                    "encoding": "audio/x-mulaw",
                    "sampleRate": 8000,
                    "channels": 1,
                },
            },
        }))

        from simulator.scenarios import StepType

        for i, step in enumerate(self.scenario.steps):
            self._log.info(
                "scenario_step",
                step=i,
                type=step.step_type.value,
                label=step.label,
            )

            try:
                if step.step_type == StepType.SPEAK:
                    await self._send_speech(websocket, step.text, step.label)

                elif step.step_type == StepType.SILENCE:
                    await self._send_frames(websocket, _silence_frames(step.duration_s))

                elif step.step_type == StepType.HOLD_MUSIC:
                    await self._send_frames(websocket, _hold_music_frames(step.duration_s))

                elif step.step_type == StepType.EXPECT_DTMF:
                    ok = await self._wait_for_dtmf(
                        websocket, step.expected_digits, step.timeout_s
                    )
                    if not ok:
                        results["errors"].append(
                            f"Step {i} ({step.label}): DTMF timeout or mismatch"
                        )

                elif step.step_type == StepType.EXPECT_SPEECH:
                    ok = await self._wait_for_speech(websocket, step.timeout_s)
                    if not ok:
                        results["errors"].append(
                            f"Step {i} ({step.label}): no speech from agent"
                        )

                elif step.step_type == StepType.PAUSE:
                    await asyncio.sleep(step.duration_s)

                elif step.step_type == StepType.DISCONNECT:
                    break

                results["steps_completed"] = i + 1

            except Exception as e:
                self._log.error("step_error", step=i, label=step.label, error=str(e))
                results["errors"].append(f"Step {i} ({step.label}): {e}")
                break

        # Send stop event
        await websocket.send(json.dumps({"event": "stop"}))

        results["dtmf_received"] = list(self._received_dtmf)
        results["agent_audio_frames"] = self._received_audio_frames

        status = "PASS" if not results["errors"] else "FAIL"
        self._log.info(
            "scenario_complete",
            status=status,
            steps=results["steps_completed"],
            errors=len(results["errors"]),
        )
        return results

    async def _send_speech(self, ws, text: str, label: str) -> None:
        """Send synthesized speech frames for the given text."""
        frames = _text_to_ulaw_frames(text)
        self._log.debug("sending_speech", label=label, frames=len(frames))
        await self._send_frames(ws, frames)

    async def _send_frames(self, ws, frames: list[str]) -> None:
        """Send a list of base64 audio frames at real-time pace (20ms each)."""
        for frame in frames:
            msg = json.dumps({
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": frame,
                    "timestamp": str(int(time.monotonic() * 1000)),
                },
            })
            await ws.send(msg)
            await asyncio.sleep(0.02)  # 20ms real-time pacing

    async def _wait_for_dtmf(
        self, ws, expected_digits: str, timeout_s: float
    ) -> bool:
        """Wait for DTMF digits from the agent."""
        collected = ""
        deadline = time.monotonic() + timeout_s

        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                msg = json.loads(raw)
                event = msg.get("event", "")

                if event == "dtmf":
                    digit = msg.get("dtmf", {}).get("digit", "")
                    collected += digit
                    self._received_dtmf.append(digit)
                    self._log.debug("dtmf_received", digit=digit, collected=collected)

                    if expected_digits and collected == expected_digits:
                        return True
                    if not expected_digits and len(collected) >= 1:
                        return True  # any digits accepted

                elif event == "media":
                    self._received_audio_frames += 1

            except asyncio.TimeoutError:
                continue
            except Exception:
                break

        return False

    async def _wait_for_speech(self, ws, timeout_s: float) -> bool:
        """Wait for the agent to send audio frames (indicating speech)."""
        frames_before = self._received_audio_frames
        deadline = time.monotonic() + timeout_s

        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                msg = json.loads(raw)
                event = msg.get("event", "")

                if event == "media":
                    self._received_audio_frames += 1
                elif event == "dtmf":
                    digit = msg.get("dtmf", {}).get("digit", "")
                    self._received_dtmf.append(digit)

            except asyncio.TimeoutError:
                continue
            except Exception:
                break

        # Consider speech detected if we received at least 5 audio frames (~100ms)
        return (self._received_audio_frames - frames_before) >= 5


async def handle_connection(websocket, scenario_name: str) -> dict:
    """Handle a single simulator WebSocket connection."""
    sim = CallSimulator(scenario_name)
    return await sim.run(websocket)


async def main(scenario: str, port: int, host: str) -> None:
    """Run the simulator WebSocket server."""
    try:
        import websockets
    except ImportError:
        print("Install websockets: pip install websockets", file=sys.stderr)
        sys.exit(1)

    configure_logging(json=False)
    log.info("simulator_starting", scenario=scenario, port=port)

    async def handler(websocket):
        results = await handle_connection(websocket, scenario)
        print(f"\n{'='*60}")
        print(f"Scenario: {results['scenario']}")
        print(f"Steps: {results['steps_completed']}/{results['steps_total']}")
        print(f"DTMF received: {results['dtmf_received']}")
        print(f"Agent audio frames: {results['agent_audio_frames']}")
        if results["errors"]:
            print(f"Errors:")
            for e in results["errors"]:
                print(f"  - {e}")
        else:
            print("Result: PASS")
        print(f"{'='*60}\n")

    async with websockets.serve(handler, host, port):
        print(f"Simulator listening on ws://{host}:{port}")
        print(f"Scenario: {scenario}")
        print("Waiting for agent connection...\n")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    from simulator.scenarios import SCENARIOS

    parser = argparse.ArgumentParser(
        description="Call simulator — fake Twilio Media Streams endpoint"
    )
    parser.add_argument(
        "--scenario", "-s",
        default="happy_path",
        choices=list(SCENARIOS.keys()),
        help="Scenario to run (default: happy_path)",
    )
    parser.add_argument("--port", "-p", type=int, default=8765)
    parser.add_argument("--host", default="localhost")
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available scenarios and exit",
    )
    args = parser.parse_args()

    if args.list:
        for name, s in SCENARIOS.items():
            print(f"  {name:25s} {s.description}")
        sys.exit(0)

    asyncio.run(main(args.scenario, args.port, args.host))
