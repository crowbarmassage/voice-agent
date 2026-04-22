"""TTS backends — protocol + implementations.

Voice must sound professional, calm, and clear. Optimized for telephony
(survives G.711 codec). Consistent voice across the entire call.

Must handle: medical terminology, alphanumeric strings (claim numbers,
NPI, member IDs spoken digit-by-digit), dates, dollar amounts.

See docs/TIER1_FEATURES.md §C2, §F6.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np


class TTSBackend(Protocol):
    """Text-to-speech backend interface."""

    sample_rate: int

    def synth(self, text: str) -> np.ndarray:
        """Synthesize text to 1-D float32 PCM audio."""
        ...

    def close(self) -> None:
        """Release model resources."""
        ...
