"""Call simulator — fake Twilio Media Streams endpoint for development.

Replays recorded IVR audio, simulates hold music, and responds with scripted
rep dialogue from annotated real call recordings. Speaks the same WebSocket
protocol as Twilio Media Streams so the same voice_agent code runs against
both simulated and real calls.

Usage:
    1. Record real payor calls and annotate them (see docs/PROJECT_REVIEW_AND_PLAN.md §Phase 0 step 6).
    2. Place annotated recordings in simulator/recordings/.
    3. Run the simulator: python -m simulator.server
    4. Point the voice agent at the simulator's WebSocket URL instead of Twilio.

Scenarios to simulate:
    - Happy path: IVR → hold → human pickup → claim status exchange → close
    - IVR loop: agent gets stuck, hits the same prompt twice
    - Hold timeout: hold exceeds max duration
    - Unexpected transfer: rep transfers to wrong department
    - Hostile/confused rep: rep asks unexpected questions
    - Garbled audio: low-quality segments to test STT robustness
    - Mid-call disconnect
    - Simultaneous speech (both parties talking at once)

See docs/TIER1_FEATURES.md §F8.
"""
