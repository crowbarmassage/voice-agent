"""Session runner — wires Session + AudioPipeline + STT + TTS for a live call.

Orchestrates the full call lifecycle: connects to telephony (real or
simulated), runs the audio pipeline, feeds STT, and drives session
state transitions based on events.

This is the "main loop" for a single call. The session manager creates
one runner per active call.

Usage:
    runner = SessionRunner(session, ws_url="ws://localhost:8765")
    await runner.run()
"""
from __future__ import annotations

import asyncio
import time

import numpy as np

from voice_agent.audio.codec import ulaw_encode, base64_encode, ULAW_SAMPLE_RATE
from voice_agent.audio.pipeline import AudioPipeline
from voice_agent.audio.vad import SpeechState, VAD
from voice_agent.events import EventType
from voice_agent.logging import get_logger
from voice_agent.metrics import metrics
from voice_agent.session import Session, SessionState
from voice_agent.stt import STTBackend, Utterance
from voice_agent.telephony.media_stream import MediaStreamClient

log = get_logger(__name__)


class SessionRunner:
    """Runs a single call session end-to-end.

    Connects to the telephony WebSocket (Twilio Media Streams or simulator),
    processes inbound audio through VAD + STT, and manages session state
    transitions.
    """

    def __init__(
        self,
        session: Session,
        ws_url: str,
        *,
        stt: STTBackend | None = None,
        vad: VAD | None = None,
    ):
        self._session = session
        self._ws_url = ws_url
        self._stt = stt
        self._vad = vad or VAD()
        self._pipeline = AudioPipeline(vad=self._vad)
        self._media_client: MediaStreamClient | None = None
        self._transcripts: list[Utterance] = []
        self._log = log.bind(
            session_id=session.id,
            work_item_id=session.work_item_id,
        )

    @property
    def transcripts(self) -> list[Utterance]:
        """All transcripts received during the call."""
        return list(self._transcripts)

    async def run(self) -> None:
        """Run the full call lifecycle.

        1. Transition to DIALING, connect to WebSocket
        2. Start audio pipeline + STT
        3. Process events until call ends
        4. Transition to POST_CALL → DONE
        """
        try:
            # Pre-call → Dialing
            self._session.transition_to(SessionState.DIALING, reason="connecting")
            self._pipeline.start()

            # Connect to WebSocket
            self._media_client = MediaStreamClient(self._ws_url, self._pipeline)
            await self._media_client.connect()
            self._session.call_sid = self._media_client.call_sid

            self._log.info(
                "call_connected",
                call_sid=self._session.call_sid,
            )

            # Run audio bridge + STT + event processing concurrently
            tasks = [
                asyncio.create_task(self._media_client.run(), name="media_bridge"),
                asyncio.create_task(self._process_audio(), name="audio_processor"),
            ]

            if self._stt:
                tasks.append(
                    asyncio.create_task(self._run_stt(), name="stt"),
                )

            # Wait for media bridge to end (call over)
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel remaining tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Post-call
            if not self._session.is_terminal:
                if self._session.state == SessionState.CONVERSATION:
                    self._session.transition_to(
                        SessionState.POST_CALL, reason="call_ended"
                    )
                    self._session.transition_to(SessionState.DONE, reason="completed")
                elif self._session.state in (
                    SessionState.DIALING,
                    SessionState.IVR,
                    SessionState.HOLD,
                ):
                    self._session.transition_to(
                        SessionState.FAILED, reason="call_ended_unexpectedly"
                    )

        except Exception as e:
            self._log.error("session_runner_error", error=str(e))
            if not self._session.is_terminal:
                self._session.fail(str(e))
        finally:
            if self._media_client:
                await self._media_client.disconnect()
            self._pipeline.stop()
            metrics.inc("sessions_completed")

    async def send_tts_text(self, text: str) -> None:
        """Synthesize and send TTS audio to the call.

        For v1, generates a simple tone pattern (placeholder).
        Replace with real TTS backend integration.
        """
        # Generate speech-like audio (placeholder — same as simulator)
        words = len(text.split())
        duration_s = max(0.5, words / 2.5)
        num_samples = int(ULAW_SAMPLE_RATE * duration_s)
        t = np.linspace(0, duration_s, num_samples, dtype=np.float32)
        audio = 0.1 * (
            np.sin(2 * np.pi * 200 * t)
            + 0.5 * np.sin(2 * np.pi * 350 * t)
        )
        await self._pipeline.send_outbound(audio, ULAW_SAMPLE_RATE)
        self._log.info("tts_sent", text_length=len(text), duration_s=round(duration_s, 2))

    async def send_dtmf(self, digits: str) -> None:
        """Send DTMF digits to the call."""
        if self._media_client:
            for digit in digits:
                await self._media_client.send_dtmf(digit)
                await asyncio.sleep(0.2)  # gap between digits

    async def _process_audio(self) -> None:
        """Monitor VAD events and drive session state transitions."""
        speech_detected_at: float | None = None
        silence_since: float | None = None

        async for event in self._pipeline.vad_events():
            if self._session.is_terminal:
                break

            if event.state == SpeechState.SPEECH:
                speech_detected_at = time.monotonic()
                silence_since = None

                # If we're in DIALING and hear speech, transition
                if self._session.state == SessionState.DIALING:
                    self._session.transition_to(
                        SessionState.IVR, reason="audio_detected"
                    )

                # If we're on HOLD and hear directed speech, might be human
                if self._session.state == SessionState.HOLD:
                    # Short speech on hold = hold message, long = human
                    # This is a simplified heuristic
                    pass

            elif event.state == SpeechState.SILENCE:
                silence_since = time.monotonic()

                # Track speech duration for hold → conversation detection
                if speech_detected_at and event.duration_s > 3.0:
                    if self._session.state == SessionState.HOLD:
                        self._session.transition_to(
                            SessionState.CONVERSATION,
                            reason="human_detected",
                        )

    async def _run_stt(self) -> None:
        """Run STT on the inbound audio stream."""
        if not self._stt:
            return

        self._log.info("stt_starting")
        try:
            async for utterance in self._stt.transcribe_stream(
                self._pipeline.stt_stream(), 16000
            ):
                self._transcripts.append(utterance)
                self._session._emit_event(
                    EventType.COUNTERPARTY_UTTERANCE,
                    details={
                        "text": utterance.text,
                        "confidence": utterance.confidence,
                        "is_final": utterance.is_final,
                    },
                )
                self._log.info(
                    "transcript",
                    text=utterance.text[:100],
                    confidence=round(utterance.confidence, 2),
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._log.error("stt_error", error=str(e))
