"""Entity extraction tests — pattern-based and merge logic."""
from __future__ import annotations

import pytest

from voice_agent.extraction import ExtractedEntity, ExtractionResult
from voice_agent.extraction.patterns import extract_from_text


class TestClaimStatusExtraction:
    def test_pending(self):
        r = extract_from_text("The claim is currently pending.")
        e = r.get("claim_status")
        assert e is not None
        assert e.value == "pending"

    def test_in_process(self):
        r = extract_from_text("It's in process right now.")
        e = r.get("claim_status")
        assert e is not None
        assert e.value == "pending"  # "in process" maps to pending

    def test_denied(self):
        r = extract_from_text("Unfortunately that claim was denied.")
        e = r.get("claim_status")
        assert e is not None
        assert e.value == "denied"

    def test_paid(self):
        r = extract_from_text("The claim has been paid. Check was issued last week.")
        e = r.get("claim_status")
        assert e is not None
        assert e.value == "paid"

    def test_no_status(self):
        r = extract_from_text("Can I have the patient's date of birth?")
        assert r.get("claim_status") is None


class TestReferenceExtraction:
    def test_nato_phonetic(self):
        r = extract_from_text("The reference number is Alpha Bravo four four seven two.")
        e = r.get("reference_number")
        assert e is not None
        assert e.value == "AB4472"

    def test_reference_number_prefix(self):
        r = extract_from_text("Reference number is REF-12345.")
        e = r.get("reference_number")
        assert e is not None
        assert "REF" in e.value

    def test_call_ref(self):
        r = extract_from_text("Your call ref number is XY789.")
        e = r.get("reference_number")
        assert e is not None

    def test_no_reference(self):
        r = extract_from_text("How can I help you today?")
        assert r.get("reference_number") is None


class TestDateExtraction:
    def test_expected_date(self):
        r = extract_from_text("Expected to finalize by May 15.")
        e = r.get("expected_date")
        assert e is not None
        assert "05-15" in e.value

    def test_expected_date_ordinal(self):
        r = extract_from_text("It should process by May fifteenth.")
        e = r.get("expected_date")
        assert e is not None
        assert "05-15" in e.value

    def test_expected_date_with_year(self):
        r = extract_from_text("Payment expected April 1, 2026.")
        e = r.get("expected_date")
        assert e is not None
        assert e.value == "2026-04-01"

    def test_received_date(self):
        r = extract_from_text("Received on 04/01/2026.")
        e = r.get("received_date")
        assert e is not None
        assert e.value == "2026-04-01"

    def test_two_dates_labeled_differently(self):
        """The key bug: rep says both received date and expected date."""
        r = extract_from_text(
            "It was received on April first and is expected to finalize "
            "by May fifteenth."
        )
        received = r.get("received_date")
        expected = r.get("expected_date")
        assert received is not None, "Should extract received_date"
        assert expected is not None, "Should extract expected_date"
        assert "04-01" in received.value
        assert "05-15" in expected.value

    def test_payment_date(self):
        r = extract_from_text("Check was issued on April tenth.")
        e = r.get("payment_date")
        assert e is not None
        assert "04-10" in e.value

    def test_unlabeled_date(self):
        """Date without context clues gets generic 'date' label."""
        r = extract_from_text("The date is March 20.")
        e = r.get("date")
        assert e is not None


class TestDollarExtraction:
    def test_dollar_sign(self):
        r = extract_from_text("The adjustment amount is $1,234.56.")
        e = r.get("dollar_amount")
        assert e is not None
        assert e.value == "1234.56"

    def test_dollars_word(self):
        r = extract_from_text("The billed amount was 500 dollars.")
        e = r.get("dollar_amount")
        assert e is not None
        assert e.value == "500"


class TestDenialCodeExtraction:
    def test_co_code(self):
        r = extract_from_text("The denial reason is CO-45.")
        e = r.get("denial_code")
        assert e is not None
        assert e.value == "CO-45"

    def test_pr_code(self):
        r = extract_from_text("Reason code PR 1.")
        e = r.get("denial_code")
        assert e is not None
        assert "PR" in e.value


class TestRepNameExtraction:
    def test_this_is_name(self):
        r = extract_from_text("Thank you for holding. This is Sarah with UHC.")
        e = r.get("rep_name")
        assert e is not None
        assert e.value == "Sarah"

    def test_my_name_is(self):
        r = extract_from_text("My name is David, how can I help?")
        e = r.get("rep_name")
        assert e is not None
        assert e.value == "David"


class TestCheckExtraction:
    def test_check_number(self):
        r = extract_from_text("Check number 8765432 was issued on April 10th.")
        e = r.get("check_or_eft_number")
        assert e is not None
        assert e.value == "8765432"

    def test_eft_number(self):
        r = extract_from_text("EFT number 12345678.")
        e = r.get("check_or_eft_number")
        assert e is not None


class TestPhoneExtraction:
    def test_fax_number(self):
        r = extract_from_text("The fax number is 800-555-1234.")
        e = r.get("phone_or_fax")
        assert e is not None
        assert e.value == "8005551234"


class TestFullUtterance:
    def test_rep_gives_status(self):
        """Realistic rep utterance should extract multiple entities."""
        r = extract_from_text(
            "Okay, I found that claim. It's currently pending, in process. "
            "It was received on April first and is expected to finalize "
            "by May fifteenth. The reference number for this call is "
            "Alpha Bravo four four seven two."
        )
        assert r.get("claim_status") is not None
        assert r.get("claim_status").value == "pending"
        assert r.get("reference_number") is not None
        assert r.get("reference_number").value == "AB4472"
        assert r.get("received_date") is not None
        assert "04-01" in r.get("received_date").value
        assert r.get("expected_date") is not None
        assert "05-15" in r.get("expected_date").value

    def test_empty_utterance(self):
        r = extract_from_text("")
        assert len(r.entities) == 0


class TestConfidenceScoring:
    def test_high_stt_confidence(self):
        r = extract_from_text("The claim is denied.", stt_confidence=0.98)
        e = r.get("claim_status")
        assert e.confidence > 0.85

    def test_low_stt_confidence(self):
        r = extract_from_text("The claim is denied.", stt_confidence=0.5)
        e = r.get("claim_status")
        assert e.confidence < 0.5


class TestExtractionResultMerge:
    def test_pattern_wins_over_llm(self):
        r1 = ExtractionResult(entities=[
            ExtractedEntity("claim_status", "pending", 0.9, source="pattern"),
        ])
        r2 = ExtractionResult(entities=[
            ExtractedEntity("claim_status", "denied", 0.7, source="llm"),
        ])
        r1.merge(r2)
        assert r1.get("claim_status").value == "pending"

    def test_llm_replaced_by_pattern(self):
        r1 = ExtractionResult(entities=[
            ExtractedEntity("claim_status", "denied", 0.7, source="llm"),
        ])
        r2 = ExtractionResult(entities=[
            ExtractedEntity("claim_status", "pending", 0.9, source="pattern"),
        ])
        r1.merge(r2)
        assert r1.get("claim_status").value == "pending"

    def test_new_entities_added(self):
        r1 = ExtractionResult(entities=[
            ExtractedEntity("claim_status", "pending", 0.9, source="pattern"),
        ])
        r2 = ExtractionResult(entities=[
            ExtractedEntity("rep_name", "Sarah", 0.7, source="llm"),
        ])
        r1.merge(r2)
        assert r1.get("claim_status") is not None
        assert r1.get("rep_name") is not None
        assert len(r1.entities) == 2
