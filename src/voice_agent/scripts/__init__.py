"""Call scripts — goal trees per use case.

Each script defines a set of goals the agent must accomplish during a call.
Goals are a tree, not a linear sequence — the agent adapts to the order
the counterparty drives the conversation.

A script includes:
    - Opening (identification + purpose statement)
    - Goals (what info to provide and what to extract)
    - Verification rules (which entities to read back)
    - Closing
    - Escalation conditions

See docs/TIER1_FEATURES.md §C4 for all four Tier 1 scripts.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScriptGoal:
    """A single goal in a call script."""

    name: str
    description: str
    required: bool = True
    completed: bool = False
    extracted_entities: dict = field(default_factory=dict)


@dataclass
class CallScript:
    """Goal-tree call script for a use case."""

    use_case: str
    opening: str
    goals: list[ScriptGoal]
    closing: str
    escalation_conditions: list[str]
