"""Live call: place a real Twilio call with Gemini brain.

Runs a FastAPI webhook server that Twilio calls on each conversation turn.
Uses Twilio's built-in STT (<Gather input="speech">) and TTS (<Say>)
with our Gemini brain providing the conversation intelligence.

Flow:
    1. Start webhook server + ngrok tunnel
    2. Place outbound call via Twilio REST API
    3. Call connects → Twilio hits /voice webhook
    4. Agent introduces itself via <Say>, then <Gather> listens
    5. You speak → Twilio STT → hits /gather webhook with transcript
    6. Transcript → Gemini brain → <Say> response + <Gather> for next turn
    7. Loop until you hang up or agent closes

Usage:
    python scripts/live_call.py --to +14143507739

Requirements:
    - TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER in env
    - GEMINI_API_KEY in env
    - ngrok installed and authenticated
"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load .env
for _env_path in [PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"]:
    if _env_path.exists():
        for line in _env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import Response

from voice_agent.brain.gemini import GeminiBrain
from voice_agent.brain import BrainContext, ConversationTurn
from voice_agent.compliance.phi import PHIAccessor
from voice_agent.logging import configure_logging, get_logger
from voice_agent.scripts.claim_status import create_claim_status_script

log = get_logger(__name__)

app = FastAPI()

# ── Global state for the call ──
brain = GeminiBrain()
script = create_claim_status_script("Riverside Medical", "1234567890", "12-3456789")
phi = PHIAccessor("claim_status", {
    "patient_name": "Jane Doe",
    "dob": "1985-03-15",
    "member_id": "MBR123456",
    "claim_number": "CLM-2026-001",
    "date_of_service": "2026-04-01",
})
conversation_history: list[ConversationTurn] = []
call_start_time = time.monotonic()
turn_count = 0


def _build_context() -> BrainContext:
    return BrainContext(
        script=script,
        phi=phi,
        history=list(conversation_history),
        payor_name="UHC",
        use_case="claim_status",
        ai_disclosure_required=True,
    )


def _twiml_gather(say_text: str, voice: str = "Polly.Joanna") -> str:
    """Build TwiML: say something, then gather speech input."""
    # Escape XML special chars in the say text
    safe_text = (
        say_text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Gather input="speech" action="/gather" method="POST" '
        f'speechTimeout="3" timeout="10" language="en-US">'
        f'<Say voice="{voice}">{safe_text}</Say>'
        "</Gather>"
        # If no speech detected, prompt again
        f'<Say voice="{voice}">I didn\'t catch that. Could you repeat?</Say>'
        '<Redirect method="POST">/reprompt</Redirect>'
        "</Response>"
    )


def _twiml_say_and_hangup(say_text: str, voice: str = "Polly.Joanna") -> str:
    safe_text = say_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say voice="{voice}">{safe_text}</Say>'
        "<Hangup/>"
        "</Response>"
    )


@app.post("/voice")
async def voice_webhook(request: Request):
    """Initial webhook when call connects. Agent introduces itself."""
    global turn_count, call_start_time
    turn_count = 0
    call_start_time = time.monotonic()
    conversation_history.clear()

    log.info("call_connected_webhook")

    # Get brain's opening
    ctx = _build_context()
    response_parts = []
    async for chunk in brain.respond(
        "The call just connected. Introduce yourself and state your purpose.",
        context=ctx,
    ):
        response_parts.append(chunk)

    opening = "".join(response_parts).strip()
    log.info("agent_opening", text=opening[:100])

    conversation_history.append(
        ConversationTurn(role="agent", text=opening, timestamp=0.0)
    )

    twiml = _twiml_gather(opening)
    return Response(content=twiml, media_type="application/xml")


@app.post("/gather")
async def gather_webhook(
    SpeechResult: str = Form(""),
    Confidence: str = Form("0"),
):
    """Webhook when Twilio captures speech. Feed to brain, respond."""
    global turn_count
    turn_count += 1

    text = SpeechResult.strip()
    confidence = float(Confidence) if Confidence else 0.0

    log.info("speech_received", text=text[:100], confidence=confidence, turn=turn_count)

    if not text:
        twiml = _twiml_gather("I didn't catch that. Could you please repeat?")
        return Response(content=twiml, media_type="application/xml")

    # Record counterparty turn
    conversation_history.append(
        ConversationTurn(
            role="counterparty",
            text=text,
            timestamp=time.monotonic() - call_start_time,
        )
    )

    # Check for goodbye signals
    goodbye_phrases = ["goodbye", "bye", "that's all", "hang up", "end call"]
    if any(phrase in text.lower() for phrase in goodbye_phrases):
        closing = "Thank you for your time. Have a great day. Goodbye."
        log.info("call_closing", reason="goodbye_detected")
        twiml = _twiml_say_and_hangup(closing)
        return Response(content=twiml, media_type="application/xml")

    # Get brain response
    ctx = _build_context()
    response_parts = []
    async for chunk in brain.respond(text, context=ctx):
        response_parts.append(chunk)

    response = "".join(response_parts).strip()
    log.info("agent_response", text=response[:100], turn=turn_count)

    conversation_history.append(
        ConversationTurn(
            role="agent",
            text=response,
            timestamp=time.monotonic() - call_start_time,
        )
    )

    # Max turns safety
    if turn_count >= 20:
        twiml = _twiml_say_and_hangup(
            "I've reached my conversation limit. A member of our team will "
            "call back. Thank you for your time."
        )
        return Response(content=twiml, media_type="application/xml")

    twiml = _twiml_gather(response)
    return Response(content=twiml, media_type="application/xml")


@app.post("/reprompt")
async def reprompt_webhook():
    """Called when no speech was detected — re-gather."""
    twiml = _twiml_gather("Are you still there?")
    return Response(content=twiml, media_type="application/xml")


@app.post("/status")
async def status_webhook(CallStatus: str = Form(""), CallSid: str = Form("")):
    """Call status callback."""
    log.info("call_status", status=CallStatus, call_sid=CallSid)

    if CallStatus == "completed":
        print(f"\n{'='*60}")
        print(f"Call completed. {turn_count} conversation turns.")
        print(f"\nTranscript:")
        for turn in conversation_history:
            role = "YOU  " if turn.role == "counterparty" else "AGENT"
            print(f"  [{role}] {turn.text}")
        print(f"{'='*60}\n")


async def start_ngrok(port: int) -> str:
    """Start ngrok tunnel and return the public URL."""
    proc = await asyncio.create_subprocess_exec(
        "ngrok", "http", str(port), "--log=stdout", "--log-format=json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Wait for ngrok to provide the URL
    import json as _json
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        try:
            data = _json.loads(line.decode())
            if data.get("url"):
                return data["url"]
        except _json.JSONDecodeError:
            continue

    raise RuntimeError("Failed to get ngrok URL")


async def place_call(to: str, webhook_base: str) -> str:
    """Place the outbound call via Twilio."""
    from voice_agent.telephony.twilio_backend import TwilioBackend

    backend = TwilioBackend()
    handle = await backend.place_call(
        to=to,
        twiml_url=f"{webhook_base}/voice",
        status_callback_url=f"{webhook_base}/status",
        record=True,
    )
    return handle.call_sid


_startup_config: dict = {}


@app.on_event("startup")
async def on_startup():
    """Place the call once the webhook server is ready to receive requests."""
    call_to = _startup_config.get("to")
    ngrok_url = _startup_config.get("ngrok_url")
    if not call_to or not ngrok_url:
        return
    print(f"\nServer ready. Placing call to {call_to}...")
    call_sid = await place_call(call_to, ngrok_url)
    print(f"Call SID: {call_sid}")
    print("\nPick up your phone!")
    print("The agent will introduce itself as Riverside Medical billing.")
    print("Say 'goodbye' to end the call.\n")


def main():
    parser = argparse.ArgumentParser(description="Live call with Gemini brain")
    parser.add_argument("--to", required=True, help="Phone number to call (E.164)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    configure_logging(json=False)

    print(f"\n{'='*60}")
    print("Live Call — Gemini Brain + Twilio")
    print(f"{'='*60}")
    print(f"Calling: {args.to}")
    print(f"Brain: gemini-3.1-flash-lite-preview")
    print(f"Script: claim_status (Riverside Medical → UHC)")
    print(f"Patient: Jane Doe, DOB 1985-03-15, Claim CLM-2026-001")
    print(f"{'='*60}\n")

    # Start cloudflared tunnel (no interstitial, free)
    print("Starting cloudflared tunnel...")
    tunnel_proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{args.port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # cloudflared prints the URL to stderr
    import re as _re
    tunnel_url = None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        line = tunnel_proc.stderr.readline()
        if not line:
            time.sleep(0.1)
            continue
        text = line.decode("utf-8", errors="ignore")
        match = _re.search(r"(https://[a-z0-9-]+\.trycloudflare\.com)", text)
        if match:
            tunnel_url = match.group(1)
            break

    if not tunnel_url:
        print("ERROR: Could not get cloudflared URL.")
        tunnel_proc.kill()
        sys.exit(1)

    print(f"Tunnel URL: {tunnel_url}")
    print(f"Webhook: {tunnel_url}/voice")

    # Store for the startup event
    _startup_config["to"] = args.to
    _startup_config["ngrok_url"] = tunnel_url

    # Run the webhook server — call is placed in on_startup after server is ready
    try:
        uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        tunnel_proc.kill()
        tunnel_proc.wait()


if __name__ == "__main__":
    main()
