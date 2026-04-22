"""TwilioBackend unit tests (mocked — no real Twilio API calls).

Tests that the backend correctly maps Twilio responses to our domain types,
builds TwiML correctly, and handles errors.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from voice_agent.telephony import CallStatus
from voice_agent.telephony.twilio_backend import TwilioBackend, _TWILIO_STATUS_MAP


class TestTwilioStatusMapping:
    """Verify Twilio status strings map correctly."""

    def test_all_twilio_statuses_mapped(self):
        twilio_statuses = [
            "queued", "ringing", "in-progress", "completed",
            "busy", "no-answer", "canceled", "failed",
        ]
        for status in twilio_statuses:
            assert status in _TWILIO_STATUS_MAP

    def test_completed_maps_correctly(self):
        assert _TWILIO_STATUS_MAP["completed"] == CallStatus.COMPLETED

    def test_in_progress_maps_correctly(self):
        assert _TWILIO_STATUS_MAP["in-progress"] == CallStatus.IN_PROGRESS

    def test_busy_maps_correctly(self):
        assert _TWILIO_STATUS_MAP["busy"] == CallStatus.BUSY


class TestTwilioBackendInit:
    """Test backend initialization."""

    @patch.dict("os.environ", {
        "TWILIO_ACCOUNT_SID": "ACtest123",
        "TWILIO_AUTH_TOKEN": "test_token",
        "TWILIO_FROM_NUMBER": "+15551234567",
    })
    def test_init_from_env(self):
        backend = TwilioBackend()
        assert backend.account_sid == "ACtest123"
        assert backend.from_number == "+15551234567"

    def test_init_from_args(self):
        backend = TwilioBackend(
            account_sid="ACtest",
            auth_token="token",
            from_number="+15559876543",
        )
        assert backend.account_sid == "ACtest"
        assert backend.from_number == "+15559876543"


class TestTwilioBackendPlaceCall:
    """Test call placement logic."""

    @pytest.mark.asyncio
    async def test_place_call_requires_twiml(self):
        backend = TwilioBackend(
            account_sid="ACtest",
            auth_token="token",
            from_number="+15551234567",
        )
        with pytest.raises(ValueError, match="twiml"):
            await backend.place_call("+18005551234")

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"TWILIO_FROM_NUMBER": ""}, clear=False)
    async def test_place_call_requires_from_number(self):
        backend = TwilioBackend(
            account_sid="ACtest",
            auth_token="token",
            from_number="",
        )
        backend.from_number = ""  # force empty even if env was loaded at init
        with pytest.raises(ValueError, match="from_number"):
            await backend.place_call("+18005551234", twiml="<Response/>")

    @pytest.mark.asyncio
    async def test_place_call_success(self):
        backend = TwilioBackend(
            account_sid="ACtest",
            auth_token="token",
            from_number="+15551234567",
        )
        mock_call = MagicMock()
        mock_call.sid = "CA_test_123"
        mock_call.status = "queued"

        with patch.object(backend._client.calls, "create", return_value=mock_call):
            handle = await backend.place_call(
                "+18005551234",
                twiml="<Response><Say>Hello</Say></Response>",
            )
            assert handle.call_sid == "CA_test_123"
            assert handle.status == CallStatus.QUEUED
