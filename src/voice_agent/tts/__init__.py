"""TTS backends — protocol + implementations.

Voice must sound professional, calm, and clear. Optimized for telephony
(survives G.711 codec). Consistent voice across the entire call.

Must handle: medical terminology, alphanumeric strings (claim numbers,
NPI, member IDs spoken digit-by-digit), dates, dollar amounts.

Supports both sync (batch) and async streaming synthesis. The streaming
path is preferred for telephony — it delivers first audio bytes faster
by synthesizing sentence-by-sentence as brain tokens arrive.

See docs/TIER1_FEATURES.md §C2, §F6.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

import numpy as np


class TTSBackend(Protocol):
    """Text-to-speech backend interface."""

    sample_rate: int

    def synth(self, text: str) -> np.ndarray:
        """Synthesize text to 1-D float32 PCM audio (batch mode)."""
        ...

    async def synth_streaming(self, text_stream: AsyncIterator[str]) -> AsyncIterator[bytes]:
        """Stream PCM audio chunks as text tokens arrive.

        Buffers tokens until a sentence boundary, synthesizes each sentence,
        and yields audio chunks. This is the low-latency path for telephony:
        brain streams tokens → TTS synthesizes per-sentence → audio streams
        to telephony.

        Yields: PCM int16 audio chunks at self.sample_rate.
        """
        ...

    async def close(self) -> None:
        """Release model resources."""
        ...
