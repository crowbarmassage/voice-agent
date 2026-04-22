"""Brain backends — conversation LLM protocol + implementations.

The brain drives the agent's side of the conversation. It receives:
    - The call script (goal tree with current progress)
    - PHI-gated claim context (via PHIAccessor — never raw context)
    - Conversation history
    - Latest counterparty utterance
    - Extracted entities so far

It returns: streamed response tokens that feed into TTS sentence-by-sentence.

Must support streaming (for low latency) and cancellation (for barge-in).

v1 default: Claude API (Anthropic) — see docs/PROJECT_REVIEW_AND_PLAN.md.

NOTE: Protocol revised per PROJECT_REVIEW_AND_PLAN.md gap analysis. Original
took raw `system_prompt: str` + `history: list[dict]`. In practice the brain
needs the PHI accessor, script state, and extraction state — not just strings.
The system prompt is now assembled internally from these structured inputs.

Latency budget: <2s from counterparty transcript to first TTS audio byte.

See docs/TIER1_FEATURES.md §C4, §F7.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

from voice_agent.compliance.phi import PHIAccessor
from voice_agent.extraction import ExtractedEntity
from voice_agent.scripts import CallScript


@dataclass
class ConversationTurn:
    """A single turn in the conversation history."""

    role: str  # "agent" or "counterparty"
    text: str
    timestamp: float  # seconds from call start


@dataclass
class BrainContext:
    """Everything the brain needs to generate the next response.

    Assembled by the session manager and passed to the brain on each turn.
    The brain should never access claim context directly — only through
    the PHI accessor embedded here.
    """

    script: CallScript
    phi: PHIAccessor
    history: list[ConversationTurn] = field(default_factory=list)
    extracted_entities: list[ExtractedEntity] = field(default_factory=list)
    ai_disclosure_required: bool = True
    payor_name: str = ""
    use_case: str = ""


class BrainBackend(Protocol):
    """Conversation LLM interface."""

    async def respond(
        self,
        counterparty_text: str,
        *,
        context: BrainContext,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[str]:
        """Stream response token pieces. Stops early if cancel is set.

        The brain assembles its own system prompt from the structured
        BrainContext (script goals, PHI-gated fields, extraction state).
        Callers do not construct the prompt manually.
        """
        ...
