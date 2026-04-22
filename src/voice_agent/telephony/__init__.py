"""Telephony adapter — abstraction over Twilio/Telnyx/Bandwidth.

Interface:
    place_call(to, from_number) → call_sid
    send_dtmf(call_sid, digits)
    play_audio(call_sid, audio_stream)
    get_audio_stream(call_sid) → inbound audio stream
    transfer(call_sid, to)
    hangup(call_sid)
    get_recording(call_sid) → recording URL

See docs/TIER1_FEATURES.md §F2.
"""
from __future__ import annotations

from typing import Protocol


class TelephonyBackend(Protocol):
    """Telephony provider abstraction."""

    async def place_call(self, to: str, from_number: str) -> str:
        """Place an outbound call. Returns call SID."""
        ...

    async def send_dtmf(self, call_sid: str, digits: str) -> None:
        """Send DTMF tones to the call (for IVR navigation)."""
        ...

    async def hangup(self, call_sid: str) -> None:
        """End the call."""
        ...
