"""Entity extraction + confidence scoring.

Extracts structured data from conversation transcripts in real-time.
Two approaches (not mutually exclusive):
    - LLM-based: brain extracts entities from its own context
    - Pattern-based: regex/NER for well-structured data (phone numbers,
      dates, dollar amounts, reference IDs)

Each extracted entity gets a confidence score based on STT confidence
and whether it was verified via read-back.

See docs/TIER1_FEATURES.md §C5, §C6.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExtractedEntity:
    """A single entity extracted from the conversation."""

    name: str
    value: str
    confidence: float  # 0.0 - 1.0
    verified: bool  # True if confirmed via read-back
    source_utterance: str  # the transcript text it was extracted from
