"""Bidirectional audio pipeline for a single call session.

Inbound path:  G.711 μ-law (8kHz) → decode → upsample 16kHz → VAD → STT
Outbound path: brain text → TTS → downsample → G.711 encode → telephony

Both paths run concurrently (full-duplex). One pipeline per active call.

The pipeline acts as the bridge between the telephony layer (which speaks
G.711 μ-law at 8kHz over WebSocket) and the AI layers (STT/TTS/brain
which work with 16kHz linear PCM).

See docs/TIER1_FEATURES.md §F3.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import numpy as np

from voice_agent.audio.codec import (
    ULAW_SAMPLE_RATE,
    STT_SAMPLE_RATE,
    base64_decode,
    base64_encode,
    pcm_f32_to_int16_bytes,
    resample,
    ulaw_decode,
    ulaw_encode,
)
from voice_agent.audio.vad import VAD, SpeechState, VADEvent
from voice_agent.logging import get_logger
from voice_agent.metrics import metrics

log = get_logger(__name__)


class AudioPipeline:
    """Full-duplex audio pipeline for one call.

    Inbound: accepts G.711 μ-law frames (from telephony or simulator),
    decodes/resamples/runs VAD, and exposes a 16kHz PCM async stream
    for STT consumption.

    Outbound: accepts PCM audio (from TTS at any sample rate), resamples
    to 8kHz, encodes to G.711 μ-law, and exposes an async stream of
    base64-encoded frames for the telephony WebSocket.
    """

    def __init__(self, vad: VAD | None = None):
        self._vad = vad or VAD()
        self._inbound_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._outbound_queue: asyncio.Queue[str] = asyncio.Queue()
        self._stt_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._running = False
        self._call_start = time.monotonic()

        # Metrics
        self._inbound_frames = 0
        self._outbound_frames = 0

        # VAD state for external consumers
        self._current_vad_state = SpeechState.SILENCE
        self._vad_events: asyncio.Queue[VADEvent] = asyncio.Queue()

        self._log = log.bind(component="audio_pipeline")

    @property
    def is_speech(self) -> bool:
        """Whether the inbound audio currently contains speech."""
        return self._current_vad_state == SpeechState.SPEECH

    @property
    def vad(self) -> VAD:
        return self._vad

    def start(self) -> None:
        """Initialize the pipeline (load VAD model, etc.)."""
        self._vad.load()
        self._running = True
        self._call_start = time.monotonic()
        self._log.info("pipeline_started")

    def stop(self) -> None:
        """Stop the pipeline and signal consumers."""
        self._running = False
        self._stt_queue.put_nowait(None)  # sentinel for STT stream
        self._log.info(
            "pipeline_stopped",
            inbound_frames=self._inbound_frames,
            outbound_frames=self._outbound_frames,
        )

    # ── Inbound path (telephony → STT) ──

    async def feed_inbound(self, ulaw_b64: str) -> None:
        """Feed a base64-encoded G.711 μ-law frame from the telephony WebSocket.

        This is called by the telephony adapter for each 'media' message.
        """
        ulaw_bytes = base64_decode(ulaw_b64)
        self._inbound_frames += 1

        # Decode μ-law → float32 PCM at 8kHz
        pcm_8k = ulaw_decode(ulaw_bytes)

        # Upsample to 16kHz for STT
        pcm_16k = resample(pcm_8k, ULAW_SAMPLE_RATE, STT_SAMPLE_RATE)

        # Run VAD on 16kHz audio
        vad_results = self._vad.process_chunk(pcm_16k)
        for prob, event in vad_results:
            if event is not None:
                self._current_vad_state = event.state
                self._vad_events.put_nowait(event)
                self._log.debug(
                    "vad_event",
                    state=event.state.value,
                    duration_s=round(event.duration_s, 2),
                )

        # Forward 16kHz PCM to STT as int16 bytes
        pcm_bytes = pcm_f32_to_int16_bytes(pcm_16k)
        await self._stt_queue.put(pcm_bytes)

    def feed_inbound_sync(self, ulaw_b64: str) -> None:
        """Synchronous version of feed_inbound (for non-async callers)."""
        ulaw_bytes = base64_decode(ulaw_b64)
        self._inbound_frames += 1
        pcm_8k = ulaw_decode(ulaw_bytes)
        pcm_16k = resample(pcm_8k, ULAW_SAMPLE_RATE, STT_SAMPLE_RATE)
        vad_results = self._vad.process_chunk(pcm_16k)
        for prob, event in vad_results:
            if event is not None:
                self._current_vad_state = event.state
                try:
                    self._vad_events.put_nowait(event)
                except asyncio.QueueFull:
                    pass
        pcm_bytes = pcm_f32_to_int16_bytes(pcm_16k)
        try:
            self._stt_queue.put_nowait(pcm_bytes)
        except asyncio.QueueFull:
            pass

    async def stt_stream(self) -> AsyncIterator[bytes]:
        """Async iterator of 16kHz int16 PCM chunks for STT consumption.

        Yields chunks until the pipeline is stopped (None sentinel).
        This is the primary interface between the audio pipeline and STT.
        """
        while True:
            chunk = await self._stt_queue.get()
            if chunk is None:
                break
            yield chunk

    async def vad_events(self) -> AsyncIterator[VADEvent]:
        """Async iterator of VAD state change events."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._vad_events.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                continue

    # ── Outbound path (TTS → telephony) ──

    async def send_outbound(
        self, pcm_f32: np.ndarray, sample_rate: int
    ) -> None:
        """Queue TTS audio for sending to the telephony WebSocket.

        Resamples to 8kHz, encodes to G.711 μ-law, base64 encodes, and
        queues for the telephony adapter to pick up.

        Args:
            pcm_f32: Float32 PCM audio from TTS.
            sample_rate: Sample rate of the input audio.
        """
        # Resample to 8kHz
        if sample_rate != ULAW_SAMPLE_RATE:
            pcm_8k = resample(pcm_f32, sample_rate, ULAW_SAMPLE_RATE)
        else:
            pcm_8k = pcm_f32

        # Encode to μ-law
        ulaw_bytes = ulaw_encode(pcm_8k)

        # Split into 20ms frames and base64 encode
        frame_size = ULAW_SAMPLE_RATE * 20 // 1000  # 160 bytes per 20ms
        for i in range(0, len(ulaw_bytes), frame_size):
            frame = ulaw_bytes[i:i + frame_size]
            if len(frame) > 0:
                b64 = base64_encode(frame)
                await self._outbound_queue.put(b64)
                self._outbound_frames += 1

    async def outbound_stream(self) -> AsyncIterator[str]:
        """Async iterator of base64-encoded G.711 μ-law frames for telephony.

        The telephony adapter reads from this to send audio to the call.
        """
        while self._running or not self._outbound_queue.empty():
            try:
                frame = await asyncio.wait_for(self._outbound_queue.get(), timeout=0.5)
                yield frame
            except asyncio.TimeoutError:
                continue

    # ── Utilities ──

    def elapsed_s(self) -> float:
        """Seconds since pipeline started."""
        return time.monotonic() - self._call_start

    async def drain_outbound(self) -> list[str]:
        """Drain all queued outbound frames (for testing)."""
        frames = []
        while not self._outbound_queue.empty():
            frames.append(await self._outbound_queue.get())
        return frames
