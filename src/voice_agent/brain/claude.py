"""Claude API brain backend.

Uses Anthropic Claude via API for conversation intelligence. Requires
Anthropic BAA for HIPAA compliance in production.

Good candidate for production: strong instruction-following, low latency
via streaming, handles complex script branching well.
"""
from __future__ import annotations


class ClaudeBrain:
    """Claude API brain implementation."""
    ...
