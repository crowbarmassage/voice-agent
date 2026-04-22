"""Session runner — wires Session + AudioPipeline + STT + IVR + Brain + TTS.

Orchestrates the full call lifecycle: connects to telephony (real or
simulated), runs the audio pipeline, feeds STT, navigates IVR, holds,
converses with the brain, and drives session state transitions.

This is the "main loop" for a single call.

Usage:
    runner = SessionRunner(session, ws_url="ws://localhost:8765", brain=brain)
    await runner.run()
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import numpy as np

from voice_agent.audio.codec import ULAW_SAMPLE_RATE
from voice_agent.audio.pipeline import AudioPipeline
from voice_agent.audio.vad import SpeechState, VAD
from voice_agent.brain import BrainBackend, BrainContext, ConversationTurn
from voice_agent.compliance.phi import PHIAccessor
from voice_agent.events import CallEvent, EventType
from voice_agent.ivr import IVRActionType, IVRConfig, IVRNavigator, IVRRule
from voice_agent.logging import get_logger
from voice_agent.metrics import metrics
from voice_agent.scripts import CallScript
from voice_agent.session import Session, SessionState
from voice_agent.stt import STTBackend, Utterance
from voice_agent.telephony.media_stream import MediaStreamClient

log = get_logger(__name__)


class SessionRunner:
    """Runs a single call session end-to-end.

    Connects to the telephony WebSocket (Twilio Media Streams or simulator),
    processes inbound audio through VAD + STT, navigates IVR with the
    IVR navigator, detects hold/human pickup, and converses using the brain.
    """

    def __init__(
        self,
        session: Session,
        ws_url: str,
        *,
        stt: STTBackend | None = None,
        brain: BrainBackend | None = None,
        script: CallScript | None = None,
        ivr_config: IVRConfig | None = None,
        vad: VAD | None = None,
    ):
        self._session = session
        self._ws_url = ws_url
        self._stt = stt
        self._brain = brain
        self._script = script
        self._vad = vad or VAD()
        self._pipeline = AudioPipeline(vad=self._vad)
        self._media_client: MediaStreamClient | None = None

        # IVR
        self._ivr = IVRNavigator(
            ivr_config or IVRConfig(payor=session.payor, department=session.use_case),
            context=session.context,
        ) if ivr_config else None

        # Conversation state
        self._transcripts: list[Utterance] = []
        self._conversation_history: list[ConversationTurn] = []
        self._transcript_queue: asyncio.Queue[Utterance] = asyncio.Queue()
        self._cancel_tts = asyncio.Event()
        self._call_start_time = 0.0

        # PHI accessor
        self._phi = PHIAccessor(session.use_case, session.context)

        self._log = log.bind(
            session_id=session.id,
            work_item_id=session.work_item_id,
        )

    @property
    def transcripts(self) -> list[Utterance]:
        return list(self._transcripts)

    @property
    def conversation_history(self) -> list[ConversationTurn]:
        return list(self._conversation_history)

    async def run(self) -> None:
        """Run the full call lifecycle."""
        try:
            self._session.transition_to(SessionState.DIALING, reason="connecting")
            self._pipeline.start()
            self._call_start_time = time.monotonic()

            # Connect to WebSocket
            self._media_client = MediaStreamClient(self._ws_url, self._pipeline)
            await self._media_client.connect()
            self._session.call_sid = self._media_client.call_sid
            self._log.info("call_connected", call_sid=self._session.call_sid)

            # Run all concurrent tasks
            tasks = [
                asyncio.create_task(self._media_client.run(), name="media_bridge"),
                asyncio.create_task(self._process_audio(), name="vad_processor"),
                asyncio.create_task(self._conversation_loop(), name="conversation"),
            ]
            if self._stt:
                tasks.append(asyncio.create_task(self._run_stt(), name="stt"))

            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Post-call transitions
            if not self._session.is_terminal:
                if self._session.state == SessionState.CONVERSATION:
                    self._session.transition_to(SessionState.POST_CALL, reason="call_ended")
                    self._session.transition_to(SessionState.DONE, reason="completed")
                else:
                    self._session.fail("call_ended_unexpectedly")

        except Exception as e:
            self._log.error("session_runner_error", error=str(e))
            if not self._session.is_terminal:
                self._session.fail(str(e))
        finally:
            if self._media_client:
                await self._media_client.disconnect()
            self._pipeline.stop()
            metrics.inc("sessions_completed")

    # ── Conversation loop (the main intelligence) ──

    async def _conversation_loop(self) -> None:
        """Main loop: reads transcripts and acts based on session state.

        IVR state   → feed transcript to IVR navigator, send DTMF
        HOLD state  → detect hold messages vs human pickup
        CONVERSATION → feed transcript to brain, send TTS response
        """
        while not self._session.is_terminal:
            try:
                utterance = await asyncio.wait_for(
                    self._transcript_queue.get(), timeout=1.0,
                )
            except asyncio.TimeoutError:
                # Check for hold timeout
                if (
                    self._session.state == SessionState.HOLD
                    and self._session.hold_start
                ):
                    hold_s = (
                        time.monotonic()
                        - self._session.hold_start.timestamp()
                        + time.time()
                        - time.monotonic()
                    )
                    # Simple: use total_hold_s + current hold
                    pass
                continue

            text = utterance.text.strip()
            if not text:
                continue

            state = self._session.state

            if state == SessionState.IVR:
                await self._handle_ivr(text)

            elif state == SessionState.HOLD:
                await self._handle_hold(text)

            elif state == SessionState.CONVERSATION:
                await self._handle_conversation(text, utterance)

            elif state == SessionState.DIALING:
                # First audio — transition to IVR
                self._session.transition_to(SessionState.IVR, reason="audio_detected")
                await self._handle_ivr(text)

    async def _handle_ivr(self, text: str) -> None:
        """Process an IVR prompt: match rules and send DTMF."""
        if not self._ivr:
            # No IVR config — go straight to hold
            self._session.transition_to(SessionState.HOLD, reason="no_ivr_config")
            return

        action = self._ivr.process_prompt(text)

        if self._ivr.is_complete:
            self._log.info("ivr_complete")
            self._session.transition_to(SessionState.HOLD, reason="ivr_complete")
            self._session._emit_event(
                EventType.IVR_NAVIGATION_COMPLETE,
                details={"actions_taken": len(self._ivr.actions_taken)},
            )
            return

        if self._ivr.is_timed_out:
            self._log.warning("ivr_timeout")
            self._session._emit_event(EventType.IVR_TIMEOUT)
            self._session.fail("ivr_timeout")
            return

        if action:
            if action.action_type == IVRActionType.DTMF:
                self._log.info("ivr_sending_dtmf", digits=action.value, rule=action.matched_rule)
                await self._send_dtmf(action.value)
                self._session._emit_event(
                    EventType.DTMF_SENT,
                    details={"digits": action.value, "rule": action.matched_rule},
                )
            elif action.action_type == IVRActionType.SPEECH:
                self._log.info("ivr_sending_speech", text=action.value)
                await self._send_tts(action.value)

            if self._ivr.is_looping:
                self._session._emit_event(EventType.IVR_LOOP_DETECTED)

    async def _handle_hold(self, text: str) -> None:
        """Process audio during hold: detect hold messages vs human pickup."""
        text_lower = text.lower()

        # Hold message patterns (ignore these)
        hold_phrases = [
            "your call is important",
            "please continue to hold",
            "estimated wait time",
            "all representatives are busy",
            "please remain on the line",
        ]
        if any(phrase in text_lower for phrase in hold_phrases):
            self._log.debug("hold_message", text=text[:60])
            self._session._emit_event(
                EventType.HOLD_MESSAGE_DETECTED,
                details={"text": text[:100]},
            )
            return

        # Human pickup patterns
        human_phrases = [
            "how can i help",
            "how may i help",
            "thank you for holding",
            "thank you for calling",
            "what can i do for you",
            "this is",  # "This is Sarah with..."
        ]
        if any(phrase in text_lower for phrase in human_phrases):
            self._log.info("human_detected", text=text[:60])
            self._session.transition_to(
                SessionState.CONVERSATION, reason="human_detected"
            )
            self._session._emit_event(
                EventType.HUMAN_DETECTED,
                details={"text": text[:100]},
            )
            # Process this utterance as the first conversation turn
            await self._handle_conversation(text, None)
            return

        # Ambiguous — if it's long enough, might be human
        if len(text.split()) > 8:
            self._log.info("possible_human", text=text[:60])
            self._session.transition_to(
                SessionState.CONVERSATION, reason="speech_detected"
            )
            await self._handle_conversation(text, None)

    async def _handle_conversation(self, text: str, utterance: Utterance | None) -> None:
        """Process a counterparty utterance: feed to brain, send response."""
        self._conversation_history.append(
            ConversationTurn(
                role="counterparty",
                text=text,
                timestamp=time.monotonic() - self._call_start_time,
            )
        )
        self._session._emit_event(
            EventType.COUNTERPARTY_UTTERANCE,
            details={"text": text[:200]},
        )

        if not self._brain or not self._script:
            self._log.debug("no_brain_configured, skipping response")
            return

        # Build brain context
        brain_ctx = BrainContext(
            script=self._script,
            phi=self._phi,
            history=list(self._conversation_history),
            payor_name=self._session.payor,
            use_case=self._session.use_case,
            ai_disclosure_required=True,
        )

        # Stream brain response → TTS
        self._cancel_tts.clear()
        response_parts: list[str] = []
        try:
            async for chunk in self._brain.respond(
                text, context=brain_ctx, cancel=self._cancel_tts,
            ):
                response_parts.append(chunk)
        except Exception as e:
            self._log.error("brain_respond_error", error=str(e))
            response_parts = ["I'm sorry, could you repeat that?"]

        full_response = "".join(response_parts).strip()
        if full_response:
            self._log.info("agent_response", text=full_response[:100])

            # Send as TTS audio
            await self._send_tts(full_response)

            # Record in history
            self._conversation_history.append(
                ConversationTurn(
                    role="agent",
                    text=full_response,
                    timestamp=time.monotonic() - self._call_start_time,
                )
            )
            self._session._emit_event(
                EventType.AGENT_UTTERANCE,
                details={"text": full_response[:200]},
            )

    # ── Audio processing ──

    async def _process_audio(self) -> None:
        """Monitor VAD events and drive state transitions."""
        async for event in self._pipeline.vad_events():
            if self._session.is_terminal:
                break

            if event.state == SpeechState.SPEECH:
                if self._session.state == SessionState.DIALING:
                    self._session.transition_to(
                        SessionState.IVR, reason="audio_detected"
                    )
                # Barge-in: if counterparty speaks while we're sending TTS
                if self._session.state == SessionState.CONVERSATION:
                    self._cancel_tts.set()

            elif event.state == SpeechState.SILENCE:
                if event.duration_s > 3.0 and self._session.state == SessionState.HOLD:
                    self._session.transition_to(
                        SessionState.CONVERSATION, reason="human_detected"
                    )

    async def _run_stt(self) -> None:
        """Run STT and feed transcripts to the conversation loop."""
        if not self._stt:
            return
        self._log.info("stt_starting")
        try:
            async for utterance in self._stt.transcribe_stream(
                self._pipeline.stt_stream(), 16000
            ):
                if utterance.text.strip():
                    self._transcripts.append(utterance)
                    self._transcript_queue.put_nowait(utterance)
                    self._log.info(
                        "transcript",
                        text=utterance.text[:100],
                        confidence=round(utterance.confidence, 2),
                    )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._log.error("stt_error", error=str(e))

    # ── Output helpers ──

    async def _send_tts(self, text: str) -> None:
        """Send TTS audio to the call. Placeholder tone generation for now."""
        words = len(text.split())
        duration_s = max(0.5, words / 2.5)
        num_samples = int(ULAW_SAMPLE_RATE * duration_s)
        t = np.linspace(0, duration_s, num_samples, dtype=np.float32)
        audio = 0.1 * (
            np.sin(2 * np.pi * 200 * t)
            + 0.5 * np.sin(2 * np.pi * 350 * t)
        )
        await self._pipeline.send_outbound(audio, ULAW_SAMPLE_RATE)

    async def _send_dtmf(self, digits: str) -> None:
        """Send DTMF digits to the call."""
        if self._media_client:
            for digit in digits:
                await self._media_client.send_dtmf(digit)
                await asyncio.sleep(0.15)
