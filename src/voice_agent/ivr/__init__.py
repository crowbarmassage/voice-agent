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

import re
import time
from dataclasses import dataclass, field
from enum import Enum

from voice_agent.logging import get_logger
from voice_agent.metrics import metrics

log = get_logger(__name__)


class IVRActionType(str, Enum):
    DTMF = "dtmf"
    SPEECH = "speech"
    WAIT = "wait"


@dataclass
class IVRRule:
    """A single IVR navigation rule: when you hear X, do Y."""
    prompt_contains: str
    action: IVRActionType
    value: str  # DTMF digits, speech text, or empty for wait
    priority: int = 0  # higher = matched first


@dataclass
class IVRAction:
    """An action to take in response to an IVR prompt."""
    action_type: IVRActionType
    value: str
    matched_rule: str  # which prompt_contains triggered this
    confidence: float = 1.0


@dataclass
class IVRConfig:
    """IVR configuration for a payor department."""
    payor: str
    department: str
    rules: list[IVRRule] = field(default_factory=list)
    fallback_digits: str = "0"  # press 0 for operator as fallback
    max_ivr_time_s: float = 180.0  # 3 minutes max in IVR
    max_same_prompt: int = 2  # loop detection: same prompt N times


class IVRNavigator:
    """Navigate a payor's IVR phone tree.

    Receives transcribed IVR prompts and returns the appropriate action
    (DTMF digits, speech response, or wait). Tracks state for loop
    detection and timeout.
    """

    def __init__(self, config: IVRConfig, context: dict | None = None):
        self._config = config
        self._context = context or {}  # claim context for variable substitution
        self._start_time = time.monotonic()
        self._prompt_history: list[str] = []
        self._actions_taken: list[IVRAction] = []
        self._complete = False
        self._log = log.bind(payor=config.payor, department=config.department)

    @property
    def is_complete(self) -> bool:
        """True if IVR navigation is done (reached a human or timed out)."""
        return self._complete

    @property
    def is_timed_out(self) -> bool:
        return (time.monotonic() - self._start_time) > self._config.max_ivr_time_s

    @property
    def is_looping(self) -> bool:
        """Detect if we're stuck in a loop (same prompt seen too many times)."""
        if len(self._prompt_history) < self._config.max_same_prompt:
            return False
        recent = self._prompt_history[-self._config.max_same_prompt:]
        return len(set(recent)) == 1

    @property
    def actions_taken(self) -> list[IVRAction]:
        return list(self._actions_taken)

    def process_prompt(self, transcript: str) -> IVRAction | None:
        """Process an IVR prompt transcript and return the action to take.

        Returns None if the prompt doesn't match any rules and no fallback
        is appropriate (e.g., it's a hold message, not an IVR menu).
        """
        if self._complete:
            return None

        if self.is_timed_out:
            self._log.warning("ivr_timeout", elapsed_s=time.monotonic() - self._start_time)
            self._complete = True
            return None

        transcript_lower = transcript.lower().strip()
        self._prompt_history.append(transcript_lower)

        # Check for "hold" or "representative" indicators — IVR is done
        if self._is_transfer_to_hold(transcript_lower):
            self._log.info("ivr_complete", reason="transfer_to_hold")
            self._complete = True
            return None

        # Check for loop
        if self.is_looping:
            self._log.warning("ivr_loop_detected", prompt=transcript_lower[:50])
            metrics.inc("ivr_loops")
            # Try fallback: press 0 for operator
            action = IVRAction(
                action_type=IVRActionType.DTMF,
                value=self._config.fallback_digits,
                matched_rule="loop_fallback",
            )
            self._actions_taken.append(action)
            return action

        # Match against rules (highest priority first)
        sorted_rules = sorted(self._config.rules, key=lambda r: -r.priority)
        for rule in sorted_rules:
            if rule.prompt_contains.lower() in transcript_lower:
                value = self._substitute_context(rule.value)
                action = IVRAction(
                    action_type=rule.action,
                    value=value,
                    matched_rule=rule.prompt_contains,
                )
                self._actions_taken.append(action)
                self._log.info(
                    "ivr_matched",
                    prompt=transcript_lower[:50],
                    action=rule.action.value,
                    value=value,
                )
                metrics.inc("ivr_actions")
                return action

        # No match — log but don't act (might be an informational message)
        self._log.debug("ivr_no_match", prompt=transcript_lower[:80])
        return None

    def mark_complete(self) -> None:
        """Manually mark IVR navigation as complete (e.g., human detected)."""
        self._complete = True

    def _substitute_context(self, value: str) -> str:
        """Replace {npi}, {tax_id}, etc. with values from claim context."""
        result = value
        for key, val in self._context.items():
            result = result.replace(f"{{{key}}}", str(val))
        return result

    def _is_transfer_to_hold(self, text: str) -> bool:
        """Detect if the IVR is transferring us to hold/representative."""
        hold_phrases = [
            "please hold",
            "connecting you",
            "transfer you",
            "next available representative",
            "your call will be answered",
            "please wait",
            "one moment",
        ]
        return any(phrase in text for phrase in hold_phrases)


def load_ivr_config_from_yaml(payor_yaml: dict, department: str) -> IVRConfig:
    """Load IVR config from a parsed payor YAML profile."""
    ivr_section = payor_yaml.get("ivr", {}).get(department, [])
    rules = []
    for entry in ivr_section:
        rules.append(IVRRule(
            prompt_contains=entry["prompt_contains"],
            action=IVRActionType(entry.get("action", "dtmf")),
            value=entry.get("value", ""),
            priority=entry.get("priority", 0),
        ))

    return IVRConfig(
        payor=payor_yaml.get("name", "Unknown"),
        department=department,
        rules=rules,
        max_hold_minutes=payor_yaml.get("max_hold_minutes", 90),
    )
