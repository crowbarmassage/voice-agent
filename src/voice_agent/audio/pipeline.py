"""Bidirectional audio pipeline for a single call session.

Handles: G.711 encode/decode, 8kHz↔16kHz resampling, audio chunking,
level normalization. Feeds VAD and STT on the inbound side, accepts
TTS output on the outbound side.
"""
from __future__ import annotations


class AudioPipeline:
    """Full-duplex audio pipeline for one call."""
    ...
