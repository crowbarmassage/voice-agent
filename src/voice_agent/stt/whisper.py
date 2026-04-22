"""Whisper large-v3-turbo STT backend.

OpenAI Whisper via mlx-whisper. 99 languages, ~800M params, MIT license.
Fallback for multilingual or when Granite isn't suitable.

Model: mlx-community/whisper-large-v3-turbo
"""
from __future__ import annotations


class WhisperSTT:
    """Whisper STT implementation."""
    ...
