"""PHI access guardrail — minimum necessary enforcement.

Controls which PHI fields the agent is allowed to disclose per use case.
The brain never sees raw claim context directly — it goes through this
layer, which filters to only the fields permitted for the current use case
and call state.

Rules per use case (from TIER1_FEATURES.md §E1):
    - claim_status: patient name, DOB, member ID, claim #, DOS
    - eligibility: patient name, DOB, member ID
    - fax_lookup: facility name, department, patient name (if needed)
    - auth_status: patient name, DOB, member ID, auth #

PHI is disclosed reactively (in response to rep's request), not proactively.
"""
from __future__ import annotations


# PHI fields permitted per use case — the whitelist.
PERMITTED_PHI: dict[str, set[str]] = {
    "claim_status": {"patient_name", "dob", "member_id", "claim_number", "date_of_service"},
    "eligibility": {"patient_name", "dob", "member_id", "subscriber_name"},
    "fax_lookup": {"facility_name", "department", "patient_name"},
    "auth_status": {"patient_name", "dob", "member_id", "auth_number"},
}


class PHIAccessor:
    """Gated access to PHI fields from claim context."""

    def __init__(self, use_case: str, context: dict):
        self._use_case = use_case
        self._context = context
        self._permitted = PERMITTED_PHI.get(use_case, set())
        self._accessed: list[str] = []  # audit trail of what was disclosed

    def get(self, field: str) -> str | None:
        """Get a PHI field if permitted for this use case. Logs access."""
        if field not in self._permitted:
            return None  # minimum necessary: don't disclose what's not needed
        self._accessed.append(field)
        return self._context.get(field)

    @property
    def accessed_fields(self) -> list[str]:
        """Return list of PHI fields that were actually disclosed."""
        return list(self._accessed)
