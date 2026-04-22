"""IVR navigator tests."""
from __future__ import annotations

import pytest

from voice_agent.ivr import (
    IVRActionType,
    IVRConfig,
    IVRNavigator,
    IVRRule,
)


def _uhc_config() -> IVRConfig:
    return IVRConfig(
        payor="UHC",
        department="claims",
        rules=[
            IVRRule("press 1 for claims", IVRActionType.DTMF, "1"),
            IVRRule("press 2 for eligibility", IVRActionType.DTMF, "2"),
            IVRRule("enter your npi", IVRActionType.DTMF, "{npi}"),
            IVRRule("enter your tax id", IVRActionType.DTMF, "{tax_id}"),
        ],
    )


class TestIVRNavigator:
    def test_matches_claims_prompt(self):
        nav = IVRNavigator(_uhc_config())
        action = nav.process_prompt("Press 1 for claims, press 2 for eligibility")
        assert action is not None
        assert action.action_type == IVRActionType.DTMF
        assert action.value == "1"

    def test_substitutes_npi(self):
        nav = IVRNavigator(_uhc_config(), context={"npi": "1234567890"})
        action = nav.process_prompt("Please enter your NPI number")
        assert action is not None
        assert action.value == "1234567890"

    def test_substitutes_tax_id(self):
        nav = IVRNavigator(_uhc_config(), context={"tax_id": "123456789"})
        action = nav.process_prompt("Enter your tax ID")
        assert action is not None
        assert action.value == "123456789"

    def test_no_match_returns_none(self):
        nav = IVRNavigator(_uhc_config())
        action = nav.process_prompt("Your call is important to us")
        assert action is None

    def test_hold_transfer_completes_navigation(self):
        nav = IVRNavigator(_uhc_config())
        nav.process_prompt("Please hold while we connect you to a representative")
        assert nav.is_complete

    def test_loop_detection(self):
        config = _uhc_config()
        config.max_same_prompt = 2
        nav = IVRNavigator(config)
        # Same prompt twice triggers loop detection
        nav.process_prompt("Press 1 for claims")
        action = nav.process_prompt("Press 1 for claims")
        # Second time should trigger fallback (press 0)
        assert action is not None
        assert action.value == "0"
        assert action.matched_rule == "loop_fallback"

    def test_timeout(self):
        config = _uhc_config()
        config.max_ivr_time_s = 0  # immediate timeout
        nav = IVRNavigator(config)
        action = nav.process_prompt("Press 1 for claims")
        assert action is None
        assert nav.is_timed_out

    def test_actions_tracked(self):
        nav = IVRNavigator(_uhc_config())
        nav.process_prompt("Press 1 for claims")
        nav.process_prompt("Enter your NPI")
        assert len(nav.actions_taken) == 2

    def test_case_insensitive(self):
        nav = IVRNavigator(_uhc_config())
        action = nav.process_prompt("PRESS 1 FOR CLAIMS")
        assert action is not None
        assert action.value == "1"

    def test_mark_complete(self):
        nav = IVRNavigator(_uhc_config())
        assert not nav.is_complete
        nav.mark_complete()
        assert nav.is_complete
        assert nav.process_prompt("Press 1") is None
