"""WebSocket server that mimics Twilio Media Streams protocol.

Accepts a connection from the voice agent, replays a scripted call scenario
(IVR prompts, hold music, rep dialogue), receives the agent's audio/DTMF
responses, and validates them against expected actions.

Run: python -m simulator.server --scenario happy_path --port 8765
"""
from __future__ import annotations


class CallSimulator:
    """Simulates a payor phone system for development and testing."""
    ...
