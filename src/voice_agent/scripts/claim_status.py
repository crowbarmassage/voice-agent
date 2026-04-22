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

See docs/TIER1_FEATURES.md §C4.
"""
from __future__ import annotations

from voice_agent.scripts import CallScript, ScriptGoal


def create_claim_status_script(
    practice_name: str = "our practice",
    npi: str = "",
    tax_id: str = "",
) -> CallScript:
    """Create a claim status inquiry call script (goal tree)."""
    return CallScript(
        use_case="claim_status",
        opening=(
            f"Hi, this is an automated assistant calling from {practice_name} "
            "billing office. I'm calling to check on the status of a claim."
        ),
        goals=[
            ScriptGoal(
                name="identify",
                description=(
                    f"Identify self and practice. Provide NPI ({npi}) and "
                    f"tax ID ({tax_id}) if asked."
                ),
            ),
            ScriptGoal(
                name="state_purpose",
                description="State purpose: checking status of a claim.",
            ),
            ScriptGoal(
                name="provide_identifiers",
                description=(
                    "Provide claim identifiers as the rep asks: "
                    "patient name, DOB, member ID, claim number, date of service. "
                    "Respond in whatever order the rep requests."
                ),
            ),
            ScriptGoal(
                name="get_status",
                description=(
                    "Ask: 'What is the current status of this claim?' "
                    "Extract: status (paid/denied/pending/in-process), "
                    "denial reason if applicable, expected payment date, "
                    "any required action."
                ),
            ),
            ScriptGoal(
                name="get_details",
                description=(
                    "If rep gives partial info, ask follow-ups. "
                    "Get the reference number for this call."
                ),
            ),
            ScriptGoal(
                name="readback",
                description=(
                    "Read back key info to confirm: claim status, "
                    "reference number, expected date."
                ),
            ),
            ScriptGoal(
                name="close",
                description="Thank the representative and close the call.",
                required=False,
            ),
        ],
        closing="Thank you for your help. Have a great day.",
        escalation_conditions=[
            "Rep asks a question not answerable from claim context",
            "Rep is hostile or asks to speak to a person",
            "Rep transfers to unexpected department",
            "Cannot understand rep (low STT confidence)",
            "10+ minutes without completing any goals",
            "Rep asks about clinical information",
        ],
    )
