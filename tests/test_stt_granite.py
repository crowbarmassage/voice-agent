"""Granite STT backend tests (no model loading — protocol conformance + unit logic)."""
from __future__ import annotations

import pytest

from voice_agent.stt import STTBackend, Utterance
from voice_agent.stt.granite import GraniteSTT, DEFAULT_PROMPT


class TestGraniteProtocolConformance:
    """Verify GraniteSTT has all methods required by STTBackend protocol."""

    def test_has_start(self):
        assert hasattr(GraniteSTT, "start")

    def test_has_transcribe_stream(self):
        assert hasattr(GraniteSTT, "transcribe_stream")

    def test_has_set_keywords(self):
        assert hasattr(GraniteSTT, "set_keywords")

    def test_has_stop(self):
        assert hasattr(GraniteSTT, "stop")


class TestGraniteInit:
    def test_default_init(self):
        stt = GraniteSTT()
        assert stt._prompt_text == DEFAULT_PROMPT
        assert stt._model is None

    def test_custom_prompt(self):
        stt = GraniteSTT(prompt="Custom prompt")
        assert stt._prompt_text == "Custom prompt"

    def test_set_keywords_before_load(self):
        stt = GraniteSTT()
        stt.set_keywords(["NPI", "CARC", "UnitedHealthcare"])
        assert stt._keywords == ["NPI", "CARC", "UnitedHealthcare"]


class TestGraniteRequiresStart:
    @pytest.mark.asyncio
    async def test_transcribe_without_start_raises(self):
        stt = GraniteSTT()

        async def empty_stream():
            return
            yield  # make it an async generator

        with pytest.raises(RuntimeError, match="start"):
            async for _ in stt.transcribe_stream(empty_stream(), 16000):
                pass


class TestUtteranceModel:
    def test_utterance_fields(self):
        u = Utterance(
            text="the claim is pending",
            confidence=0.92,
            is_final=True,
            start_time=5.0,
            end_time=7.5,
        )
        assert u.text == "the claim is pending"
        assert u.is_final is True
        assert u.words == []
