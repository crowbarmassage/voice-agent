"""Call simulator tests — scenarios and frame generation."""
from __future__ import annotations

import pytest

from simulator.scenarios import (
    HAPPY_PATH,
    HOLD_TIMEOUT,
    IVR_LOOP,
    NO_ANSWER,
    SCENARIOS,
    CallScenario,
    ScenarioStep,
    StepType,
    UNEXPECTED_TRANSFER,
)
from simulator.server import (
    CallSimulator,
    _hold_music_frames,
    _silence_frames,
    _text_to_ulaw_frames,
)
from voice_agent.audio.codec import base64_decode


class TestScenarios:
    def test_all_scenarios_in_registry(self):
        assert "happy_path" in SCENARIOS
        assert "ivr_loop" in SCENARIOS
        assert "hold_timeout" in SCENARIOS
        assert "no_answer" in SCENARIOS
        assert "unexpected_transfer" in SCENARIOS

    def test_happy_path_has_steps(self):
        assert len(HAPPY_PATH.steps) > 10

    def test_happy_path_starts_with_ivr(self):
        first = HAPPY_PATH.steps[0]
        assert first.step_type == StepType.SPEAK
        assert "claims" in first.text.lower()

    def test_happy_path_ends_with_disconnect(self):
        last = HAPPY_PATH.steps[-1]
        assert last.step_type == StepType.DISCONNECT

    def test_every_scenario_has_disconnect(self):
        for name, scenario in SCENARIOS.items():
            has_disconnect = any(
                s.step_type == StepType.DISCONNECT for s in scenario.steps
            )
            assert has_disconnect, f"{name} has no DISCONNECT step"

    def test_ivr_loop_has_repeated_menu(self):
        speak_steps = [
            s for s in IVR_LOOP.steps if s.step_type == StepType.SPEAK
        ]
        menu_texts = [s.text for s in speak_steps if "didn't understand" in s.text]
        assert len(menu_texts) >= 2

    def test_hold_timeout_has_long_hold(self):
        hold_steps = [
            s for s in HOLD_TIMEOUT.steps if s.step_type == StepType.HOLD_MUSIC
        ]
        assert any(s.duration_s >= 60 for s in hold_steps)


class TestFrameGeneration:
    def test_text_to_ulaw_produces_frames(self):
        frames = _text_to_ulaw_frames("Hello, how are you today?")
        assert len(frames) > 0
        # Each frame should be base64 decodable
        for f in frames:
            decoded = base64_decode(f)
            assert len(decoded) == 160  # 20ms at 8kHz

    def test_silence_frames(self):
        frames = _silence_frames(1.0)
        assert len(frames) == 50  # 1s / 20ms = 50 frames

    def test_hold_music_frames(self):
        frames = _hold_music_frames(0.5)
        assert len(frames) == 25  # 0.5s / 20ms

    def test_longer_text_produces_more_frames(self):
        short = _text_to_ulaw_frames("Hi")
        long = _text_to_ulaw_frames(
            "Hello, I am calling to check on the status of a claim "
            "for patient Jane Doe with date of birth March 15 1985."
        )
        assert len(long) > len(short)


class TestCallSimulator:
    def test_init_valid_scenario(self):
        sim = CallSimulator("happy_path")
        assert sim.scenario.name == "happy_path"
        assert sim.call_sid.startswith("CA_sim_")

    def test_init_invalid_scenario_raises(self):
        with pytest.raises(ValueError, match="Unknown scenario"):
            CallSimulator("nonexistent")
