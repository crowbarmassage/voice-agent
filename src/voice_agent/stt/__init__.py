"""STT backends — protocol + implementations.

Protocol-based: add a new STT model by adding a file, not refactoring.
Each backend transcribes inbound call audio and emits utterances with
confidence scores.

Current candidates:
    - Granite 4.0 1b Speech (via mlx-audio) — best English WER, keyword biasing
    - Whisper large-v3-turbo (via mlx-whisper) — multilingual fallback
    - Cloud STT (Google/AWS with BAA) — for production scale

See docs/STT_FEATURES.md for full comparison.
See docs/TIER1_FEATURES.md §C1, §F5.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol


@dataclass
class Utterance:
    """A transcribed utterance from the counterparty."""

    text: str
    confidence: float
    is_final: bool
    start_time: float  # seconds from call start
    end_time: float


class STTBackend(Protocol):
    """Speech-to-text backend interface."""

    def transcribe_chunk(self, audio_chunk: bytes, sample_rate: int) -> list[Utterance]:
        """Transcribe a chunk of audio. Returns partial and/or final utterances."""
        ...

    def set_keywords(self, keywords: list[str]) -> None:
        """Hint keywords for biased decoding (Granite supports natively,
        Whisper uses initial_prompt)."""
        ...
