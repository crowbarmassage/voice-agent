"""IVR navigation — per-payor state machines.

Each payor's phone tree is a state machine loaded from the payor's YAML
profile (config/payors/). The navigator listens to IVR prompts via STT,
matches them against expected prompts, and sends DTMF tones or speech
responses.

Handles: DTMF menus, speech input menus, NPI/tax ID entry, unknown prompt
fallback (press 0, say "representative"), loop detection, timeout.

See docs/TIER1_FEATURES.md §B3.
"""
from __future__ import annotations


class IVRNavigator:
    """Navigate a payor's IVR phone tree."""
    ...
