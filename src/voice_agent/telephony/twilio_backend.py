"""Twilio HIPAA telephony backend.

Uses Twilio Media Streams (WebSocket) for bidirectional real-time audio.
Requires Twilio HIPAA-eligible product with signed BAA.

See docs/TIER1_FEATURES.md §B1, §F2.
"""
from __future__ import annotations


class TwilioBackend:
    """Twilio implementation of TelephonyBackend protocol."""
    ...
