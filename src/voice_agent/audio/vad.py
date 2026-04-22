"""Voice Activity Detection — Silero VAD wrapper.

Detects speech onset/offset in the inbound audio stream.
Used for: turn-taking, endpointing, barge-in detection, hold→human transition.

Silero VAD operates on 16kHz mono audio in 512-sample (32ms) frames.
It returns a speech probability per frame. We apply hysteresis thresholds
to produce clean onset/offset events.

See docs/TIER1_FEATURES.md §C1, §C3.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from voice_agent.logging import get_logger

log = get_logger(__name__)


class SpeechState(str, Enum):
    SILENCE = "silence"
    SPEECH = "speech"


@dataclass
class VADEvent:
    """Speech state transition event."""

    state: SpeechState
    timestamp: float  # time.monotonic() when detected
    duration_s: float = 0.0  # duration of the previous state


# Silero VAD frame sizes at 16kHz
SILERO_FRAME_SAMPLES = 512  # 32ms at 16kHz
SILERO_SAMPLE_RATE = 16000


class VAD:
    """Silero VAD wrapper with configurable silence thresholds.

    Provides frame-by-frame speech probability and onset/offset detection
    with hysteresis to avoid flickering.
    """

    def __init__(
        self,
        onset_threshold: float = 0.5,
        offset_threshold: float = 0.35,
        min_speech_ms: int = 250,
        min_silence_ms: int = 300,
    ):
        """
        Args:
            onset_threshold: Speech probability above this = speech start.
            offset_threshold: Speech probability below this = speech end.
            min_speech_ms: Minimum speech duration to trigger onset event.
            min_silence_ms: Minimum silence duration to trigger offset event.
        """
        self._onset_threshold = onset_threshold
        self._offset_threshold = offset_threshold
        self._min_speech_frames = max(1, int(min_speech_ms / 32))
        self._min_silence_frames = max(1, int(min_silence_ms / 32))

        self._model = None
        self._state = SpeechState.SILENCE
        self._state_start = time.monotonic()
        self._consecutive_speech = 0
        self._consecutive_silence = 0
        self._buffer = np.array([], dtype=np.float32)

    @property
    def state(self) -> SpeechState:
        return self._state

    @property
    def is_speech(self) -> bool:
        return self._state == SpeechState.SPEECH

    def load(self) -> None:
        """Load the Silero VAD model. Call once at startup."""
        try:
            import torch
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                trust_repo=True,
            )
            self._model = model
            log.info("vad_loaded", model="silero_vad")
        except Exception as e:
            log.warning("vad_load_failed, using energy-based fallback", error=str(e))
            self._model = None

    def process_frame(self, audio_f32: np.ndarray) -> tuple[float, VADEvent | None]:
        """Process a single frame of 16kHz float32 audio.

        Args:
            audio_f32: Exactly SILERO_FRAME_SAMPLES (512) float32 samples.

        Returns:
            (speech_probability, event_or_none)
        """
        prob = self._get_probability(audio_f32)
        event = self._update_state(prob)
        return prob, event

    def process_chunk(self, audio_f32: np.ndarray) -> list[tuple[float, VADEvent | None]]:
        """Process an arbitrary-length chunk, splitting into VAD frames.

        Buffers partial frames for the next call. Returns results per frame.
        """
        self._buffer = np.concatenate([self._buffer, audio_f32])
        results = []
        while len(self._buffer) >= SILERO_FRAME_SAMPLES:
            frame = self._buffer[:SILERO_FRAME_SAMPLES]
            self._buffer = self._buffer[SILERO_FRAME_SAMPLES:]
            results.append(self.process_frame(frame))
        return results

    def reset(self) -> None:
        """Reset state (e.g., after a transfer)."""
        self._state = SpeechState.SILENCE
        self._state_start = time.monotonic()
        self._consecutive_speech = 0
        self._consecutive_silence = 0
        self._buffer = np.array([], dtype=np.float32)
        if self._model is not None:
            self._model.reset_states()

    def _get_probability(self, frame: np.ndarray) -> float:
        """Get speech probability for a single frame."""
        if self._model is not None:
            import torch
            tensor = torch.from_numpy(frame).unsqueeze(0)
            prob = self._model(tensor, SILERO_SAMPLE_RATE).item()
            return prob
        else:
            # Energy-based fallback when Silero isn't available
            rms = float(np.sqrt(np.mean(frame ** 2)))
            return min(1.0, rms / 0.02)  # rough mapping

    def _update_state(self, prob: float) -> VADEvent | None:
        """Update state machine with hysteresis. Returns event on transition."""
        now = time.monotonic()

        if self._state == SpeechState.SILENCE:
            if prob >= self._onset_threshold:
                self._consecutive_speech += 1
                self._consecutive_silence = 0
            else:
                self._consecutive_speech = 0

            if self._consecutive_speech >= self._min_speech_frames:
                duration = now - self._state_start
                self._state = SpeechState.SPEECH
                self._state_start = now
                self._consecutive_speech = 0
                return VADEvent(SpeechState.SPEECH, now, duration)

        elif self._state == SpeechState.SPEECH:
            if prob < self._offset_threshold:
                self._consecutive_silence += 1
                self._consecutive_speech = 0
            else:
                self._consecutive_silence = 0

            if self._consecutive_silence >= self._min_silence_frames:
                duration = now - self._state_start
                self._state = SpeechState.SILENCE
                self._state_start = now
                self._consecutive_silence = 0
                return VADEvent(SpeechState.SILENCE, now, duration)

        return None
