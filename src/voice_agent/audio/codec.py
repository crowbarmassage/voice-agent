"""G.711 μ-law codec and resampling utilities.

Twilio Media Streams delivers audio as G.711 μ-law, 8kHz, mono.
STT models expect 16kHz linear PCM. TTS outputs at various sample rates.

This module handles:
    - G.711 μ-law ↔ linear PCM encode/decode
    - 8kHz ↔ 16kHz resampling (linear interpolation, sufficient for telephony)
    - Audio chunking for WebSocket frame sizes
    - Base64 encode/decode for Twilio Media Streams JSON protocol

See docs/TIER1_FEATURES.md §F3.
"""
from __future__ import annotations

import audioop
import base64
import struct

import numpy as np

# G.711 μ-law constants
ULAW_SAMPLE_RATE = 8000
ULAW_BYTES_PER_SAMPLE = 1
ULAW_FRAME_DURATION_MS = 20  # Twilio sends 20ms frames
ULAW_FRAME_SIZE = ULAW_SAMPLE_RATE * ULAW_FRAME_DURATION_MS // 1000  # 160 bytes

STT_SAMPLE_RATE = 16000


def ulaw_decode(ulaw_bytes: bytes) -> np.ndarray:
    """Decode G.711 μ-law bytes to float32 PCM at 8kHz.

    Returns: 1-D float32 array in [-1, 1].
    """
    # audioop.ulaw2lin converts μ-law to 16-bit linear PCM
    pcm_bytes = audioop.ulaw2lin(ulaw_bytes, 2)  # 2 = 16-bit
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    return samples.astype(np.float32) / 32768.0


def ulaw_encode(pcm_f32: np.ndarray) -> bytes:
    """Encode float32 PCM to G.711 μ-law bytes.

    Args:
        pcm_f32: 1-D float32 array in [-1, 1].
    Returns:
        G.711 μ-law encoded bytes.
    """
    # Clip and convert to int16
    clipped = np.clip(pcm_f32, -1.0, 1.0)
    pcm_i16 = (clipped * 32767).astype(np.int16)
    pcm_bytes = pcm_i16.tobytes()
    return audioop.lin2ulaw(pcm_bytes, 2)


def resample_8k_to_16k(audio_8k: np.ndarray) -> np.ndarray:
    """Upsample 8kHz audio to 16kHz using linear interpolation.

    Linear interpolation is sufficient for telephony-quality audio.
    The signal is already bandlimited to 4kHz by the PSTN codec.
    """
    n = len(audio_8k)
    if n == 0:
        return np.array([], dtype=np.float32)
    # Create interpolated samples between each pair
    indices = np.arange(0, n, 0.5)
    x_orig = np.arange(n, dtype=np.float32)
    return np.interp(indices, x_orig, audio_8k).astype(np.float32)


def resample_16k_to_8k(audio_16k: np.ndarray) -> np.ndarray:
    """Downsample 16kHz audio to 8kHz by taking every other sample.

    Simple decimation is fine here — the output goes through G.711 μ-law
    encoding which further bandlimits the signal.
    """
    return audio_16k[::2].copy()


def resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Resample audio between arbitrary sample rates."""
    if from_rate == to_rate:
        return audio
    if from_rate == 8000 and to_rate == 16000:
        return resample_8k_to_16k(audio)
    if from_rate == 16000 and to_rate == 8000:
        return resample_16k_to_8k(audio)
    # General case: linear interpolation
    ratio = to_rate / from_rate
    n_out = int(len(audio) * ratio)
    indices = np.linspace(0, len(audio) - 1, n_out)
    x_orig = np.arange(len(audio), dtype=np.float32)
    return np.interp(indices, x_orig, audio).astype(np.float32)


def pcm_f32_to_int16_bytes(pcm_f32: np.ndarray) -> bytes:
    """Convert float32 PCM to int16 PCM bytes (for STT input)."""
    clipped = np.clip(pcm_f32, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16).tobytes()


def int16_bytes_to_pcm_f32(pcm_bytes: bytes) -> np.ndarray:
    """Convert int16 PCM bytes to float32 array."""
    return np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0


def base64_encode(data: bytes) -> str:
    """Base64 encode for Twilio Media Streams JSON protocol."""
    return base64.b64encode(data).decode("ascii")


def base64_decode(data: str) -> bytes:
    """Base64 decode from Twilio Media Streams JSON protocol."""
    return base64.b64decode(data)


def chunk_audio(audio: np.ndarray, chunk_samples: int) -> list[np.ndarray]:
    """Split audio into fixed-size chunks. Last chunk may be shorter."""
    chunks = []
    for i in range(0, len(audio), chunk_samples):
        chunks.append(audio[i:i + chunk_samples])
    return chunks
