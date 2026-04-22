"""Tier 1D — Authorization status check script.

Script goals:
    1. Identify self and practice
    2. State purpose ("checking status of a prior authorization")
    3. Provide auth # and patient identifiers
    4. Ask: approved/pending/denied, effective dates, approved units/services,
       denial reason (if denied), appeal process
    5. Read-back
    6. Thank and close

Entities to extract:
    - auth_status: approved | pending | denied
    - approved_services: string
    - approved_units: int
    - effective_date: date
    - expiration_date: date
    - denial_reason: string (if denied)
    - appeal_deadline: date (if denied)
    - rep_name: string
    - reference_number: string
"""
from __future__ import annotations
