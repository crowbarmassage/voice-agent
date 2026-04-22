"""Compliance layer — PHI guardrails + audit logging.

All PHI access goes through this module. Never access claim context
fields directly — use the PHI accessor to enforce minimum necessary.

All call events are logged to the immutable audit log.

See docs/TIER1_FEATURES.md §E.
"""
