"""Entity extraction + confidence scoring.

Extracts structured data from conversation transcripts in real-time.
Two approaches (not mutually exclusive):
    - Pattern-based: regex for well-structured data (phone numbers,
      dates, dollar amounts, reference IDs, claim statuses)
    - LLM-based: Gemini extracts entities from conversation context

Each extracted entity gets a confidence score based on STT confidence
and whether it was verified via read-back.

See docs/TIER1_FEATURES.md §C5, §C6.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExtractedEntity:
    """A single entity extracted from the conversation."""

    name: str
    value: str
    confidence: float  # 0.0 - 1.0
    verified: bool = False  # True if confirmed via read-back
    source: str = "pattern"  # "pattern" or "llm"
    source_utterance: str = ""  # the transcript text it was extracted from


@dataclass
class ExtractionResult:
    """Result of running extraction on a single utterance."""

    entities: list[ExtractedEntity] = field(default_factory=list)
    raw_text: str = ""

    def get(self, name: str) -> ExtractedEntity | None:
        """Get entity by name, or None."""
        for e in self.entities:
            if e.name == name:
                return e
        return None

    def merge(self, other: ExtractionResult) -> None:
        """Merge another result into this one. Pattern wins over LLM on conflicts."""
        existing_names = {e.name for e in self.entities}
        for entity in other.entities:
            if entity.name in existing_names:
                # Pattern source wins over LLM
                existing = next(e for e in self.entities if e.name == entity.name)
                if existing.source == "llm" and entity.source == "pattern":
                    self.entities.remove(existing)
                    self.entities.append(entity)
                elif existing.source == entity.source and entity.confidence > existing.confidence:
                    self.entities.remove(existing)
                    self.entities.append(entity)
            else:
                self.entities.append(entity)
