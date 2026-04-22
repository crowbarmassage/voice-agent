"""Audio pipeline — codec handling, resampling, VAD, AEC.

Inbound path:  G.711 μ-law (8kHz) → decode → upsample 16kHz → VAD → STT
Outbound path: brain text → TTS → audio → downsample → G.711 encode → telephony

Both paths run concurrently (full-duplex).

See docs/TIER1_FEATURES.md §F3.
"""
from voice_agent.audio.codec import (
    ulaw_decode,
    ulaw_encode,
    resample,
    resample_8k_to_16k,
    resample_16k_to_8k,
    base64_decode,
    base64_encode,
)
from voice_agent.audio.pipeline import AudioPipeline
from voice_agent.audio.vad import VAD, VADEvent, SpeechState
