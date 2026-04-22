"""Twilio HIPAA telephony backend.

Uses Twilio's REST API for call control and Media Streams (WebSocket) for
bidirectional real-time audio. Requires Twilio HIPAA-eligible product with
signed BAA for production PHI handling. Standard Twilio works for non-PHI
dev/testing.

Environment variables:
    TWILIO_ACCOUNT_SID  — Twilio account SID
    TWILIO_AUTH_TOKEN   — Twilio auth token
    TWILIO_FROM_NUMBER  — Default outbound caller ID (E.164)

See docs/TIER1_FEATURES.md §B1, §F2.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

from voice_agent.logging import get_logger
from voice_agent.metrics import metrics
from voice_agent.telephony import CallHandle, CallStatus

log = get_logger(__name__)

# Map Twilio status strings to our CallStatus enum
_TWILIO_STATUS_MAP = {
    "queued": CallStatus.QUEUED,
    "ringing": CallStatus.RINGING,
    "in-progress": CallStatus.IN_PROGRESS,
    "completed": CallStatus.COMPLETED,
    "busy": CallStatus.BUSY,
    "no-answer": CallStatus.NO_ANSWER,
    "canceled": CallStatus.CANCELED,
    "failed": CallStatus.FAILED,
}


class TwilioBackend:
    """Twilio implementation of TelephonyBackend protocol.

    For Phase 0/1, this implements the REST API path for call placement,
    DTMF, hangup, recording, and provider TTS. The Media Streams WebSocket
    path for real-time bidirectional audio will be added in Phase 1 when
    the audio pipeline is wired.
    """

    def __init__(
        self,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
    ):
        self.account_sid = account_sid or os.environ["TWILIO_ACCOUNT_SID"]
        self.auth_token = auth_token or os.environ["TWILIO_AUTH_TOKEN"]
        self.from_number = from_number or os.environ.get("TWILIO_FROM_NUMBER", "")
        self._client = Client(self.account_sid, self.auth_token)
        self._log = log.bind(component="twilio")

    async def place_call(
        self,
        to: str,
        from_number: str | None = None,
        *,
        status_callback_url: str | None = None,
        record: bool = False,
        machine_detection: bool = False,
        twiml: str | None = None,
        twiml_url: str | None = None,
    ) -> CallHandle:
        """Place an outbound call via Twilio REST API.

        Either twiml (inline TwiML) or twiml_url (webhook) must be provided
        to tell Twilio what to do when the call connects.
        """
        from_num = from_number or self.from_number
        if not from_num:
            raise ValueError("No from_number provided and TWILIO_FROM_NUMBER not set")

        kwargs: dict = {
            "to": to,
            "from_": from_num,
            "record": record,
        }

        if twiml:
            kwargs["twiml"] = twiml
        elif twiml_url:
            kwargs["url"] = twiml_url
        else:
            raise ValueError("Either twiml or twiml_url must be provided")

        if status_callback_url:
            kwargs["status_callback"] = status_callback_url
            kwargs["status_callback_event"] = [
                "initiated", "ringing", "answered", "completed",
            ]

        if machine_detection:
            kwargs["machine_detection"] = "Enable"

        # Run sync Twilio SDK call in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        call = await loop.run_in_executor(
            None, lambda: self._client.calls.create(**kwargs)
        )

        self._log.info("call_placed", call_sid=call.sid, to=to, from_=from_num)
        metrics.inc("calls_placed")

        return CallHandle(
            call_sid=call.sid,
            status=_TWILIO_STATUS_MAP.get(call.status, CallStatus.QUEUED),
        )

    async def send_dtmf(self, call_sid: str, digits: str) -> None:
        """Send DTMF tones to a live call."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.calls(call_sid).update(
                twiml=f"<Response><Play digits='{digits}'/></Response>"
            ),
        )
        self._log.info("dtmf_sent", call_sid=call_sid, digits=digits)

    async def play_tts(
        self, call_sid: str, text: str, voice: str = "Polly.Joanna"
    ) -> None:
        """Play text-to-speech on a live call using Twilio's <Say> verb."""
        twiml = f'<Response><Say voice="{voice}">{text}</Say></Response>'
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.calls(call_sid).update(twiml=twiml),
        )
        self._log.info("tts_played", call_sid=call_sid, text_length=len(text))

    async def play_audio(self, call_sid: str, audio_url: str) -> None:
        """Play an audio file URL on a live call using Twilio's <Play> verb."""
        twiml = f"<Response><Play>{audio_url}</Play></Response>"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.calls(call_sid).update(twiml=twiml),
        )

    async def hangup(self, call_sid: str) -> None:
        """End a call."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.calls(call_sid).update(status="completed"),
        )
        self._log.info("call_hangup", call_sid=call_sid)
        metrics.inc("calls_ended")

    async def transfer(self, call_sid: str, to: str) -> None:
        """Transfer call to another number via <Dial>."""
        twiml = f"<Response><Dial>{to}</Dial></Response>"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.calls(call_sid).update(twiml=twiml),
        )
        self._log.info("call_transferred", call_sid=call_sid, to=to)

    async def get_call_status(self, call_sid: str) -> CallStatus:
        """Get current call status from Twilio."""
        loop = asyncio.get_event_loop()
        call = await loop.run_in_executor(
            None, lambda: self._client.calls(call_sid).fetch()
        )
        return _TWILIO_STATUS_MAP.get(call.status, CallStatus.FAILED)

    async def get_recording_url(self, call_sid: str) -> str | None:
        """Get the recording URL for a completed call."""
        loop = asyncio.get_event_loop()
        recordings = await loop.run_in_executor(
            None,
            lambda: list(self._client.calls(call_sid).recordings.list(limit=1)),
        )
        if not recordings:
            return None
        # Twilio recording URI → full URL
        rec = recordings[0]
        return f"https://api.twilio.com{rec.uri.replace('.json', '.mp3')}"

    async def get_audio_stream(self, call_sid: str) -> AsyncIterator[bytes]:
        """Get inbound audio stream via Media Streams WebSocket.

        TODO: Implement in Phase 1 when audio pipeline is wired.
        This requires a WebSocket server that Twilio connects to via
        <Connect><Stream> TwiML.
        """
        raise NotImplementedError(
            "Media Streams WebSocket not yet implemented. "
            "Use play_tts() for Phase 0 hello-world testing."
        )
        yield b""  # make this a generator for type checking
