"""Gemini brain tests (unit — no API calls)."""
from __future__ import annotations

import pytest

from voice_agent.brain import BrainContext, ConversationTurn, EscalationReason
from voice_agent.brain.gemini import GeminiBrain, _build_system_prompt, DEFAULT_MODEL
from voice_agent.compliance.phi import PHIAccessor
from voice_agent.scripts import CallScript, ScriptGoal
from voice_agent.scripts.claim_status import create_claim_status_script


def _make_context() -> BrainContext:
    script = create_claim_status_script("Test Practice", "1234567890", "12-3456789")
    phi = PHIAccessor("claim_status", {
        "patient_name": "Jane Doe",
        "dob": "1985-03-15",
        "member_id": "MBR123",
        "claim_number": "CLM-001",
        "date_of_service": "2026-04-01",
    })
    return BrainContext(
        script=script,
        phi=phi,
        payor_name="UHC",
        use_case="claim_status",
    )


class TestGeminiBrainInit:
    def test_default_model(self):
        brain = GeminiBrain()
        assert brain._model_name == DEFAULT_MODEL

    def test_custom_model(self):
        brain = GeminiBrain(model="gemini-2.5-flash")
        assert brain._model_name == "gemini-2.5-flash"


class TestSystemPrompt:
    def test_contains_role(self):
        ctx = _make_context()
        prompt = _build_system_prompt(ctx)
        assert "billing assistant" in prompt.lower()

    def test_contains_payor(self):
        ctx = _make_context()
        prompt = _build_system_prompt(ctx)
        assert "UHC" in prompt

    def test_contains_script_goals(self):
        ctx = _make_context()
        prompt = _build_system_prompt(ctx)
        assert "identify" in prompt.lower()
        assert "get_status" in prompt

    def test_contains_phi_fields(self):
        ctx = _make_context()
        prompt = _build_system_prompt(ctx)
        assert "Jane Doe" in prompt
        assert "1985-03-15" in prompt
        assert "MBR123" in prompt

    def test_contains_guardrails(self):
        ctx = _make_context()
        prompt = _build_system_prompt(ctx)
        assert "administrative only" in prompt.lower()
        assert "reactively" in prompt

    def test_phi_not_over_disclosed(self):
        """SSN and diagnosis should NOT appear in the prompt."""
        phi = PHIAccessor("claim_status", {
            "patient_name": "Jane Doe",
            "ssn": "123-45-6789",
            "diagnosis_code": "J18.9",
        })
        ctx = BrainContext(
            script=create_claim_status_script(),
            phi=phi,
            payor_name="UHC",
            use_case="claim_status",
        )
        prompt = _build_system_prompt(ctx)
        assert "123-45-6789" not in prompt
        assert "J18.9" not in prompt

    def test_transfer_flag(self):
        ctx = _make_context()
        ctx.is_transfer = True
        prompt = _build_system_prompt(ctx)
        assert "transferred" in prompt.lower()

    def test_ai_disclosure(self):
        ctx = _make_context()
        ctx.ai_disclosure_required = True
        prompt = _build_system_prompt(ctx)
        assert "automated assistant" in prompt.lower()


class TestClaimStatusScript:
    def test_has_all_goals(self):
        script = create_claim_status_script()
        goal_names = [g.name for g in script.goals]
        assert "identify" in goal_names
        assert "get_status" in goal_names
        assert "readback" in goal_names
        assert "close" in goal_names

    def test_close_is_optional(self):
        script = create_claim_status_script()
        close = next(g for g in script.goals if g.name == "close")
        assert close.required is False

    def test_has_escalation_conditions(self):
        script = create_claim_status_script()
        assert len(script.escalation_conditions) >= 3
