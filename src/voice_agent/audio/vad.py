"""Voice Activity Detection — Silero VAD wrapper.

Detects speech onset/offset in the inbound audio stream.
Used for: turn-taking, endpointing, barge-in detection, hold→human transition.

See docs/TIER1_FEATURES.md §C1, §C3.
"""
from __future__ import annotations


class VAD:
    """Silero VAD wrapper with configurable silence thresholds."""
    ...
