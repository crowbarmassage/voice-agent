"""Claude API brain backend — v1 default.

Uses Anthropic Claude via API for conversation intelligence. Selected as the
v1 brain for:
    - Best-in-class instruction following for complex script execution
    - Streaming support for low-latency token delivery
    - Managed infrastructure (no GPU provisioning)
    - BAA available for HIPAA compliance

Requires: Anthropic BAA signed for production PHI handling.

The brain receives the system prompt (containing script goals and PHI-gated
claim context from PHIAccessor), conversation history, and the latest
counterparty utterance. It returns streamed response tokens that feed into
TTS sentence-by-sentence.

See docs/PROJECT_REVIEW_AND_PLAN.md — brain model commitment.
"""
from __future__ import annotations


class ClaudeBrain:
    """Claude API brain implementation."""
    ...
