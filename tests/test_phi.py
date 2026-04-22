"""PHI whitelist enforcement tests.

Validates that PHIAccessor only discloses fields permitted for each use case,
and that access is logged for audit.

See docs/TIER1_FEATURES.md §E1.
"""
import pytest

from voice_agent.compliance.phi import PERMITTED_PHI, PHIAccessor


SAMPLE_CONTEXT = {
    "patient_name": "Jane Doe",
    "dob": "1985-03-15",
    "member_id": "MBR123456",
    "claim_number": "CLM-2026-001",
    "date_of_service": "2026-04-01",
    "subscriber_name": "John Doe",
    "facility_name": "Sunrise SNF",
    "department": "Medical Records",
    "auth_number": "AUTH-999",
    "npi": "1234567890",
    "tax_id": "12-3456789",
    "diagnosis_code": "J18.9",  # should NEVER be disclosed
    "ssn": "123-45-6789",  # should NEVER be disclosed
}


class TestPHIWhitelist:
    """PHI whitelist is correctly defined per use case."""

    def test_claim_status_permits_correct_fields(self):
        expected = {"patient_name", "dob", "member_id", "claim_number", "date_of_service"}
        assert PERMITTED_PHI["claim_status"] == expected

    def test_eligibility_permits_correct_fields(self):
        expected = {"patient_name", "dob", "member_id", "subscriber_name"}
        assert PERMITTED_PHI["eligibility"] == expected

    def test_fax_lookup_permits_correct_fields(self):
        expected = {"facility_name", "department", "patient_name"}
        assert PERMITTED_PHI["fax_lookup"] == expected

    def test_auth_status_permits_correct_fields(self):
        expected = {"patient_name", "dob", "member_id", "auth_number"}
        assert PERMITTED_PHI["auth_status"] == expected

    def test_no_use_case_permits_ssn(self):
        for use_case, fields in PERMITTED_PHI.items():
            assert "ssn" not in fields, f"{use_case} permits SSN"

    def test_no_use_case_permits_diagnosis(self):
        for use_case, fields in PERMITTED_PHI.items():
            assert "diagnosis_code" not in fields, f"{use_case} permits diagnosis_code"

    def test_no_use_case_permits_npi_as_phi(self):
        """NPI is provider data, not patient PHI — but should not be in the PHI whitelist."""
        for use_case, fields in PERMITTED_PHI.items():
            assert "npi" not in fields, f"{use_case} permits NPI in PHI whitelist"


class TestPHIAccessor:
    """PHIAccessor enforces minimum necessary and logs access."""

    def test_permitted_field_returns_value(self):
        accessor = PHIAccessor("claim_status", SAMPLE_CONTEXT)
        assert accessor.get("patient_name") == "Jane Doe"

    def test_blocked_field_returns_none(self):
        accessor = PHIAccessor("claim_status", SAMPLE_CONTEXT)
        assert accessor.get("ssn") is None

    def test_diagnosis_blocked_for_claim_status(self):
        accessor = PHIAccessor("claim_status", SAMPLE_CONTEXT)
        assert accessor.get("diagnosis_code") is None

    def test_access_logged(self):
        accessor = PHIAccessor("claim_status", SAMPLE_CONTEXT)
        accessor.get("patient_name")
        accessor.get("dob")
        assert accessor.accessed_fields == ["patient_name", "dob"]

    def test_blocked_access_not_logged(self):
        accessor = PHIAccessor("claim_status", SAMPLE_CONTEXT)
        accessor.get("ssn")
        assert accessor.accessed_fields == []

    def test_unknown_use_case_blocks_all(self):
        accessor = PHIAccessor("unknown_use_case", SAMPLE_CONTEXT)
        assert accessor.get("patient_name") is None
        assert accessor.get("dob") is None
        assert accessor.accessed_fields == []

    def test_cross_use_case_isolation(self):
        """claim_status accessor cannot access auth_number."""
        accessor = PHIAccessor("claim_status", SAMPLE_CONTEXT)
        assert accessor.get("auth_number") is None

    def test_auth_status_can_access_auth_number(self):
        accessor = PHIAccessor("auth_status", SAMPLE_CONTEXT)
        assert accessor.get("auth_number") == "AUTH-999"

    def test_missing_context_field_returns_none(self):
        accessor = PHIAccessor("claim_status", {})
        assert accessor.get("patient_name") is None
        # Field was permitted but not in context — still logged as accessed
        assert accessor.accessed_fields == ["patient_name"]
