"""Session manager — orchestrates the lifecycle of a single outbound call.

One Session instance per active call. Manages the state machine:
    pre-call → dial → ivr → hold → conversation → post-call

Holds: claim context, conversation history, extracted entities, script state,
telephony handle, audio streams.

See docs/TIER1_FEATURES.md §F1.
"""
from __future__ import annotations


class Session:
    """Single-call session orchestrator."""
    ...
