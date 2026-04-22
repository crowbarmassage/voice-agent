"""Audio pipeline — codec handling, resampling, VAD, AEC.

Inbound path:  G.711 μ-law (8kHz) → decode → upsample 16kHz → VAD → STT
Outbound path: brain text → TTS → audio → downsample → G.711 encode → telephony

Both paths run concurrently (full-duplex).

See docs/TIER1_FEATURES.md §F3.
"""
