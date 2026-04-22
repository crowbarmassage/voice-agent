"""Audio pipeline tests — codec, resampling, VAD, pipeline integration."""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from voice_agent.audio.codec import (
    ULAW_SAMPLE_RATE,
    STT_SAMPLE_RATE,
    base64_decode,
    base64_encode,
    chunk_audio,
    int16_bytes_to_pcm_f32,
    pcm_f32_to_int16_bytes,
    resample,
    resample_8k_to_16k,
    resample_16k_to_8k,
    ulaw_decode,
    ulaw_encode,
)
from voice_agent.audio.pipeline import AudioPipeline
from voice_agent.audio.vad import VAD, SpeechState, SILERO_FRAME_SAMPLES


class TestG711Codec:
    """G.711 μ-law encode/decode roundtrip."""

    def test_encode_decode_roundtrip(self):
        """Encode then decode should approximately reconstruct the signal."""
        # Generate a simple sine wave
        t = np.linspace(0, 0.1, 800, dtype=np.float32)  # 100ms at 8kHz
        original = 0.5 * np.sin(2 * np.pi * 440 * t)

        encoded = ulaw_encode(original)
        decoded = ulaw_decode(encoded)

        # μ-law is lossy but should be close
        assert len(decoded) == len(original)
        # SNR should be reasonable for telephony (>30dB)
        error = np.abs(original - decoded)
        assert np.max(error) < 0.05  # max error under 5%

    def test_encode_silence(self):
        silence = np.zeros(160, dtype=np.float32)
        encoded = ulaw_encode(silence)
        assert len(encoded) == 160  # 1 byte per sample in μ-law

    def test_decode_produces_float32(self):
        ulaw = b"\xff" * 160  # μ-law silence (0xFF = zero)
        decoded = ulaw_decode(ulaw)
        assert decoded.dtype == np.float32

    def test_clipping(self):
        """Values outside [-1, 1] should be clipped."""
        loud = np.array([2.0, -2.0, 1.5, -1.5], dtype=np.float32)
        encoded = ulaw_encode(loud)
        decoded = ulaw_decode(encoded)
        assert np.all(np.abs(decoded) <= 1.0)


class TestResampling:
    def test_8k_to_16k_doubles_length(self):
        audio_8k = np.random.randn(800).astype(np.float32)
        audio_16k = resample_8k_to_16k(audio_8k)
        assert len(audio_16k) == 1600

    def test_16k_to_8k_halves_length(self):
        audio_16k = np.random.randn(1600).astype(np.float32)
        audio_8k = resample_16k_to_8k(audio_16k)
        assert len(audio_8k) == 800

    def test_roundtrip_preserves_shape(self):
        audio_8k = np.random.randn(800).astype(np.float32)
        audio_16k = resample_8k_to_16k(audio_8k)
        audio_8k_back = resample_16k_to_8k(audio_16k)
        assert len(audio_8k_back) == len(audio_8k)

    def test_same_rate_is_noop(self):
        audio = np.random.randn(800).astype(np.float32)
        result = resample(audio, 16000, 16000)
        np.testing.assert_array_equal(result, audio)

    def test_general_resample(self):
        audio = np.random.randn(24000).astype(np.float32)  # 1s at 24kHz
        result = resample(audio, 24000, 8000)
        assert len(result) == 8000

    def test_empty_audio(self):
        result = resample_8k_to_16k(np.array([], dtype=np.float32))
        assert len(result) == 0


class TestPCMConversion:
    def test_f32_to_int16_roundtrip(self):
        original = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
        as_bytes = pcm_f32_to_int16_bytes(original)
        recovered = int16_bytes_to_pcm_f32(as_bytes)
        np.testing.assert_allclose(recovered, original, atol=1e-4)


class TestBase64:
    def test_roundtrip(self):
        data = b"\x00\x01\x02\xff\xfe"
        encoded = base64_encode(data)
        assert isinstance(encoded, str)
        decoded = base64_decode(encoded)
        assert decoded == data


class TestChunkAudio:
    def test_even_chunks(self):
        audio = np.zeros(1600, dtype=np.float32)
        chunks = chunk_audio(audio, 800)
        assert len(chunks) == 2
        assert all(len(c) == 800 for c in chunks)

    def test_last_chunk_shorter(self):
        audio = np.zeros(1000, dtype=np.float32)
        chunks = chunk_audio(audio, 800)
        assert len(chunks) == 2
        assert len(chunks[0]) == 800
        assert len(chunks[1]) == 200


class TestVAD:
    def test_initial_state_is_silence(self):
        vad = VAD()
        assert vad.state == SpeechState.SILENCE
        assert not vad.is_speech

    def test_energy_fallback_silence(self):
        """Without Silero loaded, energy fallback should detect silence."""
        vad = VAD()
        # Don't call load() — uses energy fallback
        silence = np.zeros(SILERO_FRAME_SAMPLES, dtype=np.float32)
        prob, event = vad.process_frame(silence)
        assert prob < 0.1

    def test_energy_fallback_speech(self):
        """Energy fallback should detect loud audio as speech."""
        vad = VAD()
        t = np.linspace(0, 0.032, SILERO_FRAME_SAMPLES, dtype=np.float32)
        loud = 0.5 * np.sin(2 * np.pi * 440 * t)
        prob, event = vad.process_frame(loud)
        assert prob > 0.5

    def test_process_chunk_buffers_partial(self):
        vad = VAD()
        # Feed less than one frame
        short = np.zeros(100, dtype=np.float32)
        results = vad.process_chunk(short)
        assert len(results) == 0

        # Feed enough to complete the frame
        rest = np.zeros(SILERO_FRAME_SAMPLES - 100 + 100, dtype=np.float32)
        results = vad.process_chunk(rest)
        assert len(results) >= 1

    def test_reset(self):
        vad = VAD()
        vad._state = SpeechState.SPEECH
        vad.reset()
        assert vad.state == SpeechState.SILENCE


class TestAudioPipeline:
    @pytest.mark.asyncio
    async def test_inbound_produces_stt_output(self):
        """Feeding inbound μ-law should produce PCM on stt_stream."""
        pipeline = AudioPipeline()
        pipeline._running = True
        # Skip VAD load for unit test
        pipeline._vad = VAD()

        # Create a 20ms μ-law frame (160 bytes)
        silence_pcm = np.zeros(160, dtype=np.float32)
        ulaw = ulaw_encode(silence_pcm)
        b64 = base64_encode(ulaw)

        # Feed inbound
        await pipeline.feed_inbound(b64)

        # Should have STT data available
        assert not pipeline._stt_queue.empty()
        chunk = await pipeline._stt_queue.get()
        assert isinstance(chunk, bytes)
        assert len(chunk) > 0

    @pytest.mark.asyncio
    async def test_outbound_resamples_and_encodes(self):
        """Sending TTS audio should produce base64 μ-law frames."""
        pipeline = AudioPipeline()
        pipeline._running = True

        # 100ms of 16kHz silence
        pcm_16k = np.zeros(1600, dtype=np.float32)
        await pipeline.send_outbound(pcm_16k, 16000)

        frames = await pipeline.drain_outbound()
        assert len(frames) > 0
        # Each frame should be base64-decodable
        for f in frames:
            decoded = base64_decode(f)
            assert len(decoded) > 0

    @pytest.mark.asyncio
    async def test_outbound_24k_tts(self):
        """TTS at 24kHz (OmniVoice) should be downsampled to 8kHz."""
        pipeline = AudioPipeline()
        pipeline._running = True

        pcm_24k = np.zeros(2400, dtype=np.float32)  # 100ms at 24kHz
        await pipeline.send_outbound(pcm_24k, 24000)

        frames = await pipeline.drain_outbound()
        assert len(frames) > 0

    @pytest.mark.asyncio
    async def test_stop_sends_sentinel(self):
        """Stopping the pipeline should send None to stt_stream."""
        pipeline = AudioPipeline()
        pipeline._running = True
        pipeline.stop()

        # stt_stream should terminate
        chunks = []
        async for chunk in pipeline.stt_stream():
            chunks.append(chunk)
        assert len(chunks) == 0  # only sentinel, which is not yielded

    def test_elapsed(self):
        pipeline = AudioPipeline()
        pipeline._running = True
        pipeline._call_start -= 5.0  # fake 5 seconds ago
        assert pipeline.elapsed_s() >= 5.0
