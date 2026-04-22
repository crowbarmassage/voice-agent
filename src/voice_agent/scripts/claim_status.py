"""Tier 1A — Claim status inquiry script.

Script goals:
    1. Identify self and practice (name, NPI, tax ID)
    2. State purpose ("checking status of a claim")
    3. Provide claim identifiers (patient name, DOB, member ID, claim #, DOS)
    4. Ask: "What is the current status of this claim?"
    5. Extract: status, denial reason (if any), expected payment date, required action
    6. Follow up on partial info
    7. Read-back key info
    8. Thank and close

Entities to extract:
    - claim_status: paid | denied | pending | in_process | other
    - denial_reason_code: CARC/RARC code (if denied)
    - expected_payment_date: date (if pending/in_process)
    - check_or_eft_number: string (if paid)
    - adjustment_amount: dollar amount (if adjusted)
    - rep_name: string
    - reference_number: string (call reference ID)

See docs/TIER1_FEATURES.md §C4.
"""
from __future__ import annotations
