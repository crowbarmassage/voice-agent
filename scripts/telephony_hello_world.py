"""Telephony hello-world — Phase 0 validation.

Places an outbound test call via Twilio, plays a canned TTS message,
records the call, and hangs up. Proves the TwilioBackend works end-to-end.

Usage:
    # Set env vars first:
    export TWILIO_ACCOUNT_SID=ACxxxx
    export TWILIO_AUTH_TOKEN=xxxx
    export TWILIO_FROM_NUMBER=+1xxxxxxxxxx

    # Run:
    python scripts/telephony_hello_world.py --to +14143507739

    # Or with all options:
    python scripts/telephony_hello_world.py \
        --to +14143507739 \
        --message "Hello, this is a test call from the voice agent platform." \
        --voice Polly.Joanna \
        --record
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import os
from pathlib import Path

# Add src to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load .env if present — check project root and parent (~/Github/.env)
for _env_path in [PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"]:
    if _env_path.exists():
        for line in _env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

from voice_agent.logging import configure_logging, get_logger
from voice_agent.telephony.twilio_backend import TwilioBackend

log = get_logger(__name__)

DEFAULT_MESSAGE = (
    "Hello. This is an automated test call from the voice agent platform. "
    "This call is being placed to verify telephony integration. "
    "If you are receiving this call, the system is working correctly. "
    "Thank you, and goodbye."
)


async def hello_world(
    to: str,
    message: str = DEFAULT_MESSAGE,
    voice: str = "Polly.Joanna",
    record: bool = True,
) -> None:
    """Place a test call, play TTS, optionally record, hang up."""
    configure_logging(json=False)
    log.info("telephony_hello_world_start", to=to, record=record)

    backend = TwilioBackend()

    # Build TwiML inline: Say the message, pause, then hang up.
    # If recording, Twilio records from call start via the record=True param.
    from twilio.twiml.voice_response import VoiceResponse

    response = VoiceResponse()
    response.say(message, voice=voice)
    response.pause(length=1)
    response.say("End of test. Goodbye.", voice=voice)

    twiml_str = str(response)
    log.info("twiml_generated", twiml=twiml_str)

    # Place the call
    handle = await backend.place_call(
        to=to,
        twiml=twiml_str,
        record=record,
    )
    log.info("call_placed", call_sid=handle.call_sid, status=handle.status.value)

    # Poll for call completion
    print(f"\nCall placed: {handle.call_sid}")
    print(f"Calling {to}...")
    print("Waiting for call to complete...\n")

    for attempt in range(60):  # max 60 * 5s = 5 minutes
        await asyncio.sleep(5)
        status = await backend.get_call_status(handle.call_sid)
        print(f"  Status: {status.value}")

        if status.value in ("completed", "busy", "no-answer", "canceled", "failed"):
            break
    else:
        print("Timed out waiting for call to complete.")
        await backend.hangup(handle.call_sid)

    # Get final status
    final_status = await backend.get_call_status(handle.call_sid)
    log.info("call_completed", call_sid=handle.call_sid, status=final_status.value)
    print(f"\nFinal status: {final_status.value}")

    # Get recording URL if recorded
    if record:
        await asyncio.sleep(3)  # brief wait for recording to finalize
        recording_url = await backend.get_recording_url(handle.call_sid)
        if recording_url:
            print(f"Recording: {recording_url}")
            log.info("recording_available", url=recording_url)
        else:
            print("No recording available (call may not have connected).")

    print("\nHello-world complete.")


def main():
    parser = argparse.ArgumentParser(description="Telephony hello-world test")
    parser.add_argument(
        "--to",
        required=True,
        help="Destination phone number in E.164 format (e.g., +14143507739)",
    )
    parser.add_argument(
        "--message",
        default=DEFAULT_MESSAGE,
        help="TTS message to play",
    )
    parser.add_argument(
        "--voice",
        default="Polly.Joanna",
        help="Twilio TTS voice (default: Polly.Joanna)",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        default=True,
        help="Record the call (default: True)",
    )
    parser.add_argument(
        "--no-record",
        dest="record",
        action="store_false",
        help="Don't record the call",
    )
    args = parser.parse_args()

    asyncio.run(hello_world(
        to=args.to,
        message=args.message,
        voice=args.voice,
        record=args.record,
    ))


if __name__ == "__main__":
    main()
