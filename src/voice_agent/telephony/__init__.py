"""Telephony adapter — abstraction over Twilio/Telnyx/Bandwidth.

Full interface for bidirectional audio streaming over PSTN. The protocol
must support both real telephony providers and the call simulator (which
speaks the same WebSocket protocol for development/testing).

See docs/TIER1_FEATURES.md §F2.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class CallStatus(str, Enum):
    """Telephony-level call status (from provider callbacks)."""
    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    CANCELED = "canceled"
    FAILED = "failed"


@dataclass
class CallHandle:
    """Returned by place_call — encapsulates call state."""
    call_sid: str
    status: CallStatus = CallStatus.QUEUED


class TelephonyBackend(Protocol):
    """Telephony provider abstraction.

    NOTE: This protocol was revised per PROJECT_REVIEW_AND_PLAN.md gap
    analysis. The original stub only had place_call, send_dtmf, hangup.
    The full interface includes audio streaming, recording, and transfer
    — the hard parts.
    """

    async def place_call(
        self,
        to: str,
        from_number: str,
        *,
        status_callback_url: str | None = None,
        record: bool = False,
        machine_detection: bool = False,
    ) -> CallHandle:
        """Place an outbound call. Returns a CallHandle with call SID.

        Args:
            to: Destination phone number (E.164 format).
            from_number: Caller ID number (E.164).
            status_callback_url: Webhook URL for call status events.
            record: Whether to record the call from the start.
            machine_detection: Enable answering machine detection.
        """
        ...

    async def send_dtmf(self, call_sid: str, digits: str) -> None:
        """Send DTMF tones to the call (for IVR navigation)."""
        ...

    async def get_audio_stream(self, call_sid: str) -> AsyncIterator[bytes]:
        """Get the inbound audio stream (counterparty → agent).

        Yields G.711 μ-law audio chunks. This is the raw telephony audio
        that feeds into the audio pipeline for decoding, resampling, VAD,
        and STT.
        """
        ...

    async def play_audio(self, call_sid: str, audio: bytes) -> None:
        """Send audio to the call (agent → counterparty).

        Accepts encoded audio bytes to inject into the outbound stream.
        Used for TTS output.
        """
        ...

    async def play_tts(self, call_sid: str, text: str, voice: str = "Polly.Joanna") -> None:
        """Play text-to-speech via the telephony provider's built-in TTS.

        Useful for telephony hello-world and simple messages without
        needing our own TTS pipeline. Uses provider's TTS engine.
        """
        ...

    async def transfer(self, call_sid: str, to: str) -> None:
        """Transfer the call to another number (for warm handoff to human)."""
        ...

    async def hangup(self, call_sid: str) -> None:
        """End the call."""
        ...

    async def get_recording_url(self, call_sid: str) -> str | None:
        """Get the URL of the call recording after the call ends."""
        ...

    async def get_call_status(self, call_sid: str) -> CallStatus:
        """Poll current call status from the provider."""
        ...
