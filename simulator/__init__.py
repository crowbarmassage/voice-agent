"""Call simulator — fake Twilio Media Streams endpoint for development.

Replays scripted call scenarios (IVR, hold, rep dialogue) over WebSocket
using the exact same JSON protocol as Twilio Media Streams. The voice agent
code runs against the simulator without modification.

Usage:
    python -m simulator.server --scenario happy_path --port 8765
    python -m simulator.server --list  # show available scenarios

Built-in scenarios:
    happy_path          — IVR → hold → human → claim status exchange → close
    ivr_loop            — Agent gets stuck in IVR loop
    hold_timeout        — Hold exceeds max duration
    no_answer           — Call rings but nobody answers
    unexpected_transfer — Rep transfers to wrong department

See docs/TIER1_FEATURES.md §F8.
"""
