"""Brain backends — conversation LLM protocol + implementations.

The brain receives: system prompt (script + claim context) + conversation
history + latest counterparty utterance. Returns: agent's next response text.

Must support streaming (tokens → TTS sentence-by-sentence) and cancellation
(for barge-in).

Latency budget: <2s from counterparty transcript to first TTS audio byte.

See docs/TIER1_FEATURES.md §C4, §F7.
"""
from __future__ import annotations

import threading
from typing import Iterator, Protocol


class BrainBackend(Protocol):
    """Conversation LLM interface."""

    def respond(
        self,
        user_text: str,
        *,
        system_prompt: str,
        history: list[dict],
        cancel: threading.Event | None = None,
    ) -> Iterator[str]:
        """Stream response token pieces. Stops early if cancel is set."""
        ...
