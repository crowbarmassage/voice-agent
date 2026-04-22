"""LLM-based entity extraction using Gemini.

Supplements pattern-based extraction for entities that don't match
rigid regex patterns. Runs after each counterparty utterance during
CONVERSATION state.

The LLM sees the conversation context and extracts structured entities
as JSON. Results are merged with pattern-based extraction (pattern wins
on conflicts for well-structured data).

See docs/TIER1_FEATURES.md §C5.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from voice_agent.extraction import ExtractedEntity, ExtractionResult
from voice_agent.logging import get_logger

log = get_logger(__name__)

# Load .env
_env_file = Path.home() / "Github" / ".env"
if _env_file.exists() and "GEMINI_API_KEY" not in os.environ:
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


EXTRACTION_PROMPT = """\
Extract structured entities from this healthcare billing conversation turn.
The counterparty (payor representative) just said the text below.

Return ONLY a JSON object with these fields (omit fields not mentioned):
{
  "claim_status": "paid|denied|pending|in_process|on_hold|adjusted|closed",
  "denial_reason": "free text or CARC/RARC code",
  "expected_date": "YYYY-MM-DD",
  "reference_number": "alphanumeric reference/call ID",
  "check_or_eft_number": "payment number",
  "dollar_amount": "numeric amount",
  "rep_name": "representative's name",
  "phone_or_fax": "10-digit number",
  "action_required": "what the caller needs to do next"
}

If the utterance contains no extractable entities, return {}.
Do NOT guess — only extract what is explicitly stated.
"""

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
    return _client


async def extract_with_llm(
    utterance: str,
    conversation_context: str = "",
    model: str = "gemini-3.1-flash-lite-preview",
    stt_confidence: float = 0.85,
) -> ExtractionResult:
    """Extract entities from an utterance using Gemini.

    Args:
        utterance: The counterparty's latest text.
        conversation_context: Recent conversation history for context.
        model: Gemini model to use.
        stt_confidence: STT confidence to factor into entity confidence.

    Returns:
        ExtractionResult with entities sourced as "llm".
    """
    import asyncio

    client = _get_client()

    prompt = f"{EXTRACTION_PROMPT}\n\nConversation context:\n{conversation_context}\n\nCounterparty said:\n\"{utterance}\""

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=model,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config={
                    "temperature": 0.0,
                    "max_output_tokens": 256,
                },
            ),
        )

        text = response.text.strip()

        # Strip markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(text)
        result = ExtractionResult(raw_text=utterance)

        for key, value in data.items():
            if value and str(value).strip():
                result.entities.append(ExtractedEntity(
                    name=key,
                    value=str(value).strip(),
                    confidence=0.75 * stt_confidence,  # LLM = lower base confidence
                    source="llm",
                    source_utterance=utterance,
                ))

        log.debug("llm_extraction", entities=len(result.entities), text=utterance[:60])
        return result

    except json.JSONDecodeError:
        log.warning("llm_extraction_json_error", text=utterance[:60])
        return ExtractionResult(raw_text=utterance)
    except Exception as e:
        log.error("llm_extraction_error", error=str(e))
        return ExtractionResult(raw_text=utterance)
