"""Call scenarios for the simulator.

Each scenario is a sequence of steps that model what happens on a real
payor call: IVR prompts, DTMF expectations, hold music, human pickup,
scripted rep dialogue, and expected agent responses.

Scenarios can use:
    - TTS text (synthesized at runtime via a simple TTS or pre-recorded)
    - Pre-recorded WAV files from simulator/recordings/
    - Silence (hold music simulation)
    - Expected DTMF from the agent (for IVR validation)

Until we have real call recordings (Phase 0 item 6), these are synthetic
scenarios that exercise the full call flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StepType(str, Enum):
    """Type of simulator step."""
    # Simulator sends audio/silence to the agent
    SPEAK = "speak"           # Speak text (TTS or pre-recorded)
    SILENCE = "silence"       # Send silence for N seconds
    HOLD_MUSIC = "hold_music" # Send hold music pattern (silence + periodic message)

    # Simulator expects action from the agent
    EXPECT_DTMF = "expect_dtmf"    # Wait for specific DTMF digits
    EXPECT_SPEECH = "expect_speech" # Wait for agent to speak (any content)

    # Control
    PAUSE = "pause"           # Wait N seconds (no audio sent)
    DISCONNECT = "disconnect" # Hang up


@dataclass
class ScenarioStep:
    """A single step in a call scenario."""
    step_type: StepType
    text: str = ""              # For SPEAK: text to synthesize
    duration_s: float = 0.0     # For SILENCE/HOLD_MUSIC/PAUSE: duration
    expected_digits: str = ""   # For EXPECT_DTMF: expected digit sequence
    timeout_s: float = 10.0     # Max time to wait for agent response
    audio_file: str = ""        # Optional: pre-recorded WAV instead of TTS
    label: str = ""             # Human-readable label for logging


@dataclass
class CallScenario:
    """A complete call scenario for the simulator."""
    name: str
    description: str
    payor: str = "TestPayor"
    steps: list[ScenarioStep] = field(default_factory=list)


# ── Built-in scenarios ──

HAPPY_PATH = CallScenario(
    name="happy_path",
    description="Claim status: IVR → hold → human → exchange → close",
    payor="UHC",
    steps=[
        # IVR greeting
        ScenarioStep(
            StepType.SPEAK,
            text="Thank you for calling UnitedHealthcare provider services. "
                 "For claims, press 1. For eligibility, press 2. "
                 "For authorizations, press 3.",
            label="ivr_main_menu",
        ),
        ScenarioStep(
            StepType.EXPECT_DTMF,
            expected_digits="1",
            timeout_s=10.0,
            label="expect_claims_dtmf",
        ),
        # Second IVR level
        ScenarioStep(
            StepType.SPEAK,
            text="Please enter your 10 digit NPI number.",
            label="ivr_npi_prompt",
        ),
        ScenarioStep(
            StepType.EXPECT_DTMF,
            expected_digits="",  # any 10 digits
            timeout_s=15.0,
            label="expect_npi",
        ),
        ScenarioStep(
            StepType.SPEAK,
            text="Thank you. Please hold while we connect you to a representative.",
            label="ivr_hold_transfer",
        ),
        # Hold
        ScenarioStep(
            StepType.HOLD_MUSIC,
            duration_s=5.0,
            label="hold_music",
        ),
        ScenarioStep(
            StepType.SPEAK,
            text="Your call is important to us. Please continue to hold.",
            label="hold_message",
        ),
        ScenarioStep(
            StepType.HOLD_MUSIC,
            duration_s=3.0,
            label="hold_music_2",
        ),
        # Human pickup
        ScenarioStep(
            StepType.SPEAK,
            text="Thank you for holding. This is Sarah with UnitedHealthcare "
                 "provider services. How can I help you today?",
            label="human_pickup",
        ),
        ScenarioStep(
            StepType.EXPECT_SPEECH,
            timeout_s=15.0,
            label="expect_agent_intro",
        ),
        # Rep asks for identifiers
        ScenarioStep(
            StepType.SPEAK,
            text="Sure, I can help you with that claim. Can I have the "
                 "patient's date of birth please?",
            label="rep_asks_dob",
        ),
        ScenarioStep(
            StepType.EXPECT_SPEECH,
            timeout_s=10.0,
            label="expect_dob",
        ),
        ScenarioStep(
            StepType.SPEAK,
            text="And the member ID?",
            label="rep_asks_member_id",
        ),
        ScenarioStep(
            StepType.EXPECT_SPEECH,
            timeout_s=10.0,
            label="expect_member_id",
        ),
        ScenarioStep(
            StepType.SPEAK,
            text="And the claim number or date of service?",
            label="rep_asks_claim",
        ),
        ScenarioStep(
            StepType.EXPECT_SPEECH,
            timeout_s=10.0,
            label="expect_claim_info",
        ),
        # Rep provides status
        ScenarioStep(
            StepType.PAUSE,
            duration_s=3.0,
            label="rep_looking_up",
        ),
        ScenarioStep(
            StepType.SPEAK,
            text="Okay, I found that claim. It's currently in process. "
                 "It was received on April first and is expected to finalize "
                 "by May fifteenth. The reference number for this call is "
                 "Alpha Bravo four four seven two.",
            label="rep_gives_status",
        ),
        ScenarioStep(
            StepType.EXPECT_SPEECH,
            timeout_s=15.0,
            label="expect_readback_or_close",
        ),
        # Close
        ScenarioStep(
            StepType.SPEAK,
            text="Yes, that's correct. Is there anything else I can help you with?",
            label="rep_confirms",
        ),
        ScenarioStep(
            StepType.EXPECT_SPEECH,
            timeout_s=10.0,
            label="expect_close",
        ),
        ScenarioStep(
            StepType.SPEAK,
            text="Thank you for calling. Have a great day.",
            label="rep_goodbye",
        ),
        ScenarioStep(
            StepType.DISCONNECT,
            label="call_end",
        ),
    ],
)


IVR_LOOP = CallScenario(
    name="ivr_loop",
    description="Agent gets stuck in IVR loop — same prompt repeats",
    payor="Aetna",
    steps=[
        ScenarioStep(
            StepType.SPEAK,
            text="Welcome to Aetna. Press 1 for claims. Press 2 for eligibility.",
            label="ivr_menu",
        ),
        ScenarioStep(StepType.EXPECT_DTMF, expected_digits="1", label="expect_1"),
        ScenarioStep(
            StepType.SPEAK,
            text="I'm sorry, I didn't understand. Press 1 for claims. "
                 "Press 2 for eligibility.",
            label="ivr_menu_repeat",
        ),
        ScenarioStep(StepType.EXPECT_DTMF, expected_digits="1", label="expect_1_again"),
        ScenarioStep(
            StepType.SPEAK,
            text="I'm sorry, I didn't understand. Press 1 for claims. "
                 "Press 2 for eligibility.",
            label="ivr_menu_repeat_2",
        ),
        ScenarioStep(StepType.EXPECT_DTMF, expected_digits="0", label="expect_operator"),
        ScenarioStep(
            StepType.SPEAK,
            text="Please hold for the next available representative.",
            label="transfer_to_rep",
        ),
        ScenarioStep(StepType.HOLD_MUSIC, duration_s=3.0, label="hold"),
        ScenarioStep(
            StepType.SPEAK,
            text="Thank you for holding. This is Mike. How can I help you?",
            label="human_pickup",
        ),
        ScenarioStep(StepType.EXPECT_SPEECH, label="expect_intro"),
        ScenarioStep(StepType.DISCONNECT, label="end"),
    ],
)


HOLD_TIMEOUT = CallScenario(
    name="hold_timeout",
    description="Hold exceeds maximum duration — agent should hang up and retry",
    payor="BCBS",
    steps=[
        ScenarioStep(
            StepType.SPEAK,
            text="Thank you for calling Blue Cross Blue Shield. "
                 "For provider services, press 1.",
            label="ivr",
        ),
        ScenarioStep(StepType.EXPECT_DTMF, expected_digits="1", label="expect_1"),
        ScenarioStep(
            StepType.SPEAK,
            text="All representatives are currently busy. "
                 "Please hold and your call will be answered in the order received.",
            label="hold_start",
        ),
        # Long hold — exceeds typical timeout
        ScenarioStep(StepType.HOLD_MUSIC, duration_s=120.0, label="long_hold"),
        # Agent should hang up before reaching this
        ScenarioStep(
            StepType.SPEAK,
            text="Thank you for holding. How can I help you?",
            label="human_pickup_if_waited",
        ),
        ScenarioStep(StepType.DISCONNECT, label="end"),
    ],
)


NO_ANSWER = CallScenario(
    name="no_answer",
    description="Call rings but nobody answers",
    payor="Cigna",
    steps=[
        ScenarioStep(StepType.SILENCE, duration_s=45.0, label="ringing"),
        ScenarioStep(StepType.DISCONNECT, label="no_answer"),
    ],
)


UNEXPECTED_TRANSFER = CallScenario(
    name="unexpected_transfer",
    description="Rep transfers to wrong department mid-conversation",
    payor="UHC",
    steps=[
        ScenarioStep(
            StepType.SPEAK,
            text="UnitedHealthcare provider services. Press 1 for claims.",
            label="ivr",
        ),
        ScenarioStep(StepType.EXPECT_DTMF, expected_digits="1", label="expect_1"),
        ScenarioStep(StepType.SILENCE, duration_s=2.0, label="connecting"),
        ScenarioStep(
            StepType.SPEAK,
            text="Hi, this is Jennifer. How can I help?",
            label="rep_1",
        ),
        ScenarioStep(StepType.EXPECT_SPEECH, label="expect_intro"),
        ScenarioStep(
            StepType.SPEAK,
            text="Oh, you need the claims department. Let me transfer you. "
                 "One moment please.",
            label="rep_transfers",
        ),
        ScenarioStep(StepType.HOLD_MUSIC, duration_s=3.0, label="transfer_hold"),
        ScenarioStep(
            StepType.SPEAK,
            text="Claims department, this is David. How can I assist you?",
            label="rep_2_pickup",
        ),
        ScenarioStep(StepType.EXPECT_SPEECH, label="expect_re_intro"),
        ScenarioStep(StepType.DISCONNECT, label="end"),
    ],
)


# Registry of all built-in scenarios
SCENARIOS: dict[str, CallScenario] = {
    s.name: s
    for s in [HAPPY_PATH, IVR_LOOP, HOLD_TIMEOUT, NO_ANSWER, UNEXPECTED_TRANSFER]
}
