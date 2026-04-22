"""Hold handler — hold music detection, patience, human pickup detection.

Detects when the call transitions to/from hold state:
    - Hold onset: silence + music + periodic spoken messages ("your call is
      important to us"). No speech directed at the caller.
    - Human pickup: speech directed at the caller after hold ("thank you for
      holding, how can I help you?"). Agent must respond within ~1 second.
    - Periodic hold messages: detected via STT, confirmed as hold messages
      (not a human returning), ignored.

Tracks hold duration against the payor profile's max_hold_minutes timeout.

See docs/TIER1_FEATURES.md §B5.
"""
from __future__ import annotations


class HoldHandler:
    """Detects hold state and human pickup from inbound audio signals."""

    def __init__(self, max_hold_minutes: int = 90):
        self.max_hold_minutes = max_hold_minutes
        self._hold_start: float | None = None

    @property
    def is_on_hold(self) -> bool:
        """Whether the call is currently in hold state."""
        return self._hold_start is not None

    @property
    def hold_duration_s(self) -> float:
        """Seconds spent on hold (0 if not on hold)."""
        ...

    def on_audio_frame(self, frame: bytes, vad_is_speech: bool) -> str | None:
        """Process an audio frame. Returns state transition if detected:
        'hold_started', 'human_detected', 'hold_timeout', or None."""
        ...
