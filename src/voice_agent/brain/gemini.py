"""Gemini brain backend — v1 default.

Uses Google Gemini API for conversation intelligence. Streaming support
for low-latency token delivery.

Environment variables:
    GEMINI_API_KEY — Google AI API key

The brain receives structured BrainContext (script goals, PHI-gated claim
context, conversation history, extraction state) and assembles its own
system prompt. Callers do not construct the prompt manually.

See docs/TIER1_FEATURES.md §C4, §F7.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

from voice_agent.brain import (
    BrainContext,
    BrainResponse,
    ConversationTurn,
    EscalationReason,
)
from voice_agent.logging import get_logger
from voice_agent.metrics import metrics

log = get_logger(__name__)

DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"

# Load .env from parent if needed
_env_file = Path.home() / "Github" / ".env"
if _env_file.exists() and "GEMINI_API_KEY" not in os.environ:
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _build_system_prompt(context: BrainContext) -> str:
    """Build the system prompt from structured BrainContext."""
    parts = []

    # Role and identity
    parts.append(
        "You are an automated billing assistant calling from a healthcare "
        "provider's billing office. You are on a phone call with a payor "
        "representative. Your responses will be spoken aloud by a text-to-speech "
        "engine, so write in flowing conversational prose — no markdown, bullets, "
        "headers, or emoji. Keep responses concise (1-3 sentences unless more "
        "detail is needed)."
    )

    # AI disclosure
    if context.ai_disclosure_required:
        parts.append(
            "At the start of the call, identify yourself: 'Hi, this is an "
            "automated assistant calling from [Practice] billing office.'"
        )

    # Use case and payor
    parts.append(f"Use case: {context.use_case}. Payor: {context.payor_name}.")

    # Script goals
    if context.script:
        parts.append(f"Call script: {context.script.use_case}")
        parts.append(f"Opening: {context.script.opening}")
        goals_text = []
        for g in context.script.goals:
            status = "DONE" if g.completed else "TODO"
            goals_text.append(f"  [{status}] {g.name}: {g.description}")
        parts.append("Goals:\n" + "\n".join(goals_text))
        parts.append(f"Closing: {context.script.closing}")

    # PHI — only what the accessor permits
    parts.append("Patient/claim information available (disclose only when asked):")
    phi_fields = []
    for field_name in context.phi._permitted:
        value = context.phi.get(field_name)
        if value:
            phi_fields.append(f"  {field_name}: {value}")
    if phi_fields:
        parts.append("\n".join(phi_fields))
    else:
        parts.append("  (no context loaded)")

    # Extracted entities so far
    if context.extracted_entities:
        parts.append("Entities extracted so far:")
        for e in context.extracted_entities:
            verified = " (verified)" if e.verified else ""
            parts.append(f"  {e.name}: {e.value}{verified}")

    # Transfer handling
    if context.is_transfer:
        parts.append(
            "You were just transferred to a new representative. "
            "Re-identify yourself and re-state your purpose."
        )

    # Guardrails
    parts.append(
        "IMPORTANT RULES:\n"
        "- You are administrative only. Do not interpret clinical information.\n"
        "- Disclose PHI reactively (when the rep asks), not proactively.\n"
        "- For high-value entities (reference numbers, dates, dollar amounts), "
        "read them back to confirm.\n"
        "- If the rep asks something you cannot answer, say: 'I don't have that "
        "information available, but I can have someone call back with it.'\n"
        "- If the rep is hostile or asks to speak to a person, politely close: "
        "'I apologize, a member of our team will call back. Thank you.'\n"
        "- Spell out numbers digit by digit for clarity on the phone."
    )

    return "\n\n".join(parts)


def _build_messages(
    context: BrainContext, counterparty_text: str
) -> list[dict]:
    """Build the message list for the Gemini API."""
    messages = []

    # Conversation history
    for turn in context.history:
        role = "user" if turn.role == "counterparty" else "model"
        messages.append({"role": role, "parts": [{"text": turn.text}]})

    # Latest counterparty utterance
    messages.append({"role": "user", "parts": [{"text": counterparty_text}]})

    return messages


class GeminiBrain:
    """Gemini API brain implementation of BrainBackend protocol."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
    ):
        self._model_name = model
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._client = None
        self._log = log.bind(component="gemini_brain", model=model)

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def respond(
        self,
        counterparty_text: str,
        *,
        context: BrainContext,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[str]:
        """Stream response tokens from Gemini.

        Yields text chunks as they arrive. Stops early if cancel is set
        (for barge-in support).
        """
        import time

        client = self._get_client()
        system_prompt = _build_system_prompt(context)
        messages = _build_messages(context, counterparty_text)

        self._log.info(
            "brain_request",
            counterparty_text=counterparty_text[:80],
            history_turns=len(context.history),
        )

        t0 = time.monotonic()
        first_token = True

        try:
            # Run streaming generation
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.models.generate_content_stream(
                    model=self._model_name,
                    contents=messages,
                    config={
                        "system_instruction": system_prompt,
                        "temperature": 0.3,
                        "max_output_tokens": 256,
                    },
                ),
            )

            full_text = []
            for chunk in response:
                if cancel and cancel.is_set():
                    self._log.info("brain_cancelled")
                    break

                text = chunk.text
                if text:
                    if first_token:
                        ttft = (time.monotonic() - t0) * 1000
                        metrics.record_timer("brain_ttft_ms", ttft)
                        first_token = False
                    full_text.append(text)
                    yield text

            elapsed = (time.monotonic() - t0) * 1000
            metrics.record_timer("brain_response_ms", elapsed)
            metrics.inc("brain_responses")
            self._log.info(
                "brain_response",
                text="".join(full_text)[:100],
                elapsed_ms=round(elapsed),
            )

        except Exception as e:
            self._log.error("brain_error", error=str(e))
            metrics.inc("brain_errors")
            yield "I'm sorry, I'm having a technical issue. Could you please repeat that?"

    async def analyze_response(
        self,
        counterparty_text: str,
        *,
        context: BrainContext,
    ) -> BrainResponse:
        """Non-streaming analysis for structured decisions."""
        client = self._get_client()
        system_prompt = _build_system_prompt(context)

        analysis_prompt = (
            f"The counterparty said: \"{counterparty_text}\"\n\n"
            "Analyze this and respond with ONLY a JSON object (no markdown):\n"
            "{\n"
            '  "response_text": "your spoken response",\n'
            '  "should_escalate": false,\n'
            '  "escalation_reason": null,\n'
            '  "entities_to_verify": [],\n'
            '  "goals_completed": []\n'
            "}"
        )

        messages = _build_messages(context, analysis_prompt)

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=self._model_name,
                    contents=messages,
                    config={
                        "system_instruction": system_prompt,
                        "temperature": 0.1,
                        "max_output_tokens": 512,
                    },
                ),
            )

            text = response.text.strip()

            # Try to parse JSON response
            import json
            try:
                # Strip markdown code fences if present
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                data = json.loads(text)
                return BrainResponse(
                    text=data.get("response_text", text),
                    should_escalate=data.get("should_escalate", False),
                    escalation_reason=(
                        EscalationReason(data["escalation_reason"])
                        if data.get("escalation_reason")
                        else None
                    ),
                    entities_to_verify=data.get("entities_to_verify", []),
                    goals_completed=data.get("goals_completed", []),
                )
            except (json.JSONDecodeError, ValueError):
                return BrainResponse(text=text)

        except Exception as e:
            self._log.error("brain_analyze_error", error=str(e))
            return BrainResponse(
                text="I'm sorry, could you repeat that?",
                should_escalate=False,
            )
