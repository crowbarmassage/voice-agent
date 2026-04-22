"""Disposition model validation tests.

Validates that the Disposition Pydantic model enforces required fields,
defaults, and value constraints.

See docs/TIER1_FEATURES.md §D1.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from voice_agent.models import CallOutcome, Disposition


NOW = datetime.now(timezone.utc)


class TestDispositionModel:
    def test_minimal_valid_disposition(self):
        d = Disposition(
            work_item_id="wi_001",
            use_case="claim_status",
            payor="UHC",
            phone_number="+18005551234",
            call_start=NOW,
            call_end=NOW,
            outcome=CallOutcome.COMPLETED,
        )
        assert d.work_item_id == "wi_001"
        assert d.outcome == CallOutcome.COMPLETED
        assert d.extracted_entities == {}
        assert d.entities_verified == []
        assert d.retry_needed is False
        assert d.next_action == "none"

    def test_all_outcomes_are_valid(self):
        for outcome in CallOutcome:
            d = Disposition(
                work_item_id="wi_001",
                use_case="claim_status",
                payor="UHC",
                phone_number="+18005551234",
                call_start=NOW,
                call_end=NOW,
                outcome=outcome,
            )
            assert d.outcome == outcome

    def test_invalid_outcome_rejected(self):
        with pytest.raises(ValidationError):
            Disposition(
                work_item_id="wi_001",
                use_case="claim_status",
                payor="UHC",
                phone_number="+18005551234",
                call_start=NOW,
                call_end=NOW,
                outcome="invalid_outcome",
            )

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            Disposition(
                use_case="claim_status",
                payor="UHC",
                phone_number="+18005551234",
                call_start=NOW,
                call_end=NOW,
                outcome=CallOutcome.COMPLETED,
                # missing work_item_id
            )

    def test_extracted_entities_stored(self):
        d = Disposition(
            work_item_id="wi_001",
            use_case="claim_status",
            payor="UHC",
            phone_number="+18005551234",
            call_start=NOW,
            call_end=NOW,
            outcome=CallOutcome.COMPLETED,
            extracted_entities={"claim_status": "paid", "check_number": "12345"},
            entities_verified=["claim_status"],
            confidence_score=0.95,
        )
        assert d.extracted_entities["claim_status"] == "paid"
        assert "claim_status" in d.entities_verified
        assert d.confidence_score == 0.95

    def test_escalated_disposition_has_reason(self):
        d = Disposition(
            work_item_id="wi_001",
            use_case="claim_status",
            payor="UHC",
            phone_number="+18005551234",
            call_start=NOW,
            call_end=NOW,
            outcome=CallOutcome.ESCALATED,
            escalation_reason="hostile_counterparty",
        )
        assert d.escalation_reason == "hostile_counterparty"

    def test_serialization_roundtrip(self):
        d = Disposition(
            work_item_id="wi_001",
            use_case="claim_status",
            payor="UHC",
            phone_number="+18005551234",
            call_start=NOW,
            call_end=NOW,
            outcome=CallOutcome.COMPLETED,
        )
        data = d.model_dump()
        d2 = Disposition(**data)
        assert d == d2
