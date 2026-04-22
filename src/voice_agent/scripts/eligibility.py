"""Tier 1B — Eligibility / benefits verification script.

Script goals:
    1. Identify self and practice
    2. State purpose ("verifying eligibility for a patient")
    3. Provide patient identifiers (name, DOB, member ID)
    4. Ask: active/inactive, plan name, effective dates, copay, coinsurance,
       deductible (met/remaining), OOP max, auth requirements
    5. Read-back key financials
    6. Thank and close

Entities to extract:
    - active: bool
    - plan_name: string
    - effective_date: date
    - term_date: date | None
    - copay: dollar amount
    - coinsurance_pct: float
    - deductible: dollar amount
    - deductible_met: dollar amount
    - oop_max: dollar amount
    - oop_met: dollar amount
    - auth_required: bool
    - rep_name: string
    - reference_number: string
"""
from __future__ import annotations
