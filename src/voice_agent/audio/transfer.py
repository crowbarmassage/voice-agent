"""Transfer detector — detect when the counterparty transfers the call.

Cues: "let me transfer you to...", hold music resuming briefly after
conversation, a new voice greeting after a pause.

When a transfer is detected, the session must:
    1. Reset conversation state for the new rep (re-identify, re-state purpose)
    2. Retain claim context and any entities already extracted
    3. Log the transfer event for audit
    4. If transferred to an unexpected department, consider escalation

See docs/TIER1_FEATURES.md §B6.
"""
from __future__ import annotations


class TransferDetector:
    """Detect call transfers from audio and transcript signals."""

    def on_transcript(self, text: str) -> bool:
        """Check if transcript indicates a transfer. Returns True if detected."""
        ...
