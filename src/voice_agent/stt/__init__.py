"""STT backends — protocol + implementations.

Protocol-based: add a new STT model by adding a file, not refactoring.
Each backend transcribes inbound call audio and emits utterances with
confidence scores.

Current candidates:
    - Granite 4.0 1b Speech (via mlx-audio) — best English WER, keyword biasing
    - Whisper large-v3-turbo (via mlx-whisper) — multilingual fallback
    - Cloud STT (Google Speech / AWS Transcribe with BAA) — for production scale

NOTE: Protocol revised per PROJECT_REVIEW_AND_PLAN.md gap analysis.
Original used synchronous `transcribe_chunk(bytes)`. Real telephony audio
arrives as a continuous stream, so the interface is now an async streaming
iterator that yields utterances as they are detected.

See docs/STT_FEATURES.md for full comparison.
See docs/TIER1_FEATURES.md §C1, §F5.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class WordTiming:
    """Word-level timing and confidence from STT."""

    word: str
    start_time: float
    end_time: float
    confidence: float


@dataclass
class Utterance:
    """A transcribed utterance from the counterparty."""

    text: str
    confidence: float
    is_final: bool
    start_time: float  # seconds from call start
    end_time: float
    language: str | None = None  # detected language code (if available)
    words: list[WordTiming] = field(default_factory=list)


class STTBackend(Protocol):
    """Speech-to-text backend interface (streaming)."""

    async def start(self) -> None:
        """Initialize the backend (load model, warm up)."""
        ...

    async def transcribe_stream(
        self, audio_stream: AsyncIterator[bytes], sample_rate: int
    ) -> AsyncIterator[Utterance]:
        """Transcribe a continuous audio stream.

        Accepts an async iterator of audio chunks (decoded PCM, 16kHz).
        Yields Utterance objects as they are detected — both partials
        (is_final=False) and finals (is_final=True).

        This is the primary interface for telephony use. The audio stream
        runs for the duration of the call.
        """
        ...

    def set_keywords(self, keywords: list[str]) -> None:
        """Hint keywords for biased decoding.

        Granite supports natively via prompt injection.
        Whisper uses initial_prompt as a crude approximation.
        Cloud STT backends may have their own keyword/phrase hint APIs.
        """
        ...

    async def stop(self) -> None:
        """Release resources."""
        ...
