# Architecture Overview

## System Diagram

```
Work Queue (Postgres)
    │
    ▼
Session Manager (one per active call)
    ├── Pre-call: context assembly, payor profile, business hours check
    ├── Telephony Adapter
    │       ├── Webhook mode: Twilio <Gather>/<Say> + FastAPI + cloudflared
    │       ├── WebSocket mode: Twilio Media Streams (simulator-compatible)
    │       ├── Outbound call placement (PSTN)
    │       ├── DTMF sending (IVR navigation)
    │       └── Bidirectional audio stream
    ├── Audio Pipeline
    │       ├── Inbound: G.711 decode → 16kHz upsample → Silero VAD → STT
    │       └── Outbound: Brain text → TTS → downsample → G.711 encode
    ├── IVR Navigator (per-payor rule engine)
    ├── Hold Handler (hold message vs human pickup detection)
    ├── Brain (Gemini API — conversation LLM)
    │       ├── Goal-tree script execution
    │       ├── PHI-gated context (minimum necessary)
    │       └── Guardrails (admin only, no clinical, no SSN)
    ├── Entity Extraction
    │       ├── Pattern-based (regex — status, dates, reference #, codes)
    │       └── LLM-based (Gemini — free-form entities)
    └── Post-call: disposition record, audit log, retry scheduling
```

## Two Call Modes

### Webhook Mode (current — used for live calls)

```
Twilio ──HTTP POST──▶ FastAPI webhook ──▶ Gemini brain
                                         ──▶ Entity extraction
       ◀──TwiML (<Say> + <Gather>)──────
```

- Twilio handles STT (`<Gather input="speech">`) and TTS (`<Say>`)
- Our server provides the conversation intelligence
- Requires a public URL (cloudflared tunnel for dev)
- Latency: ~1-2s per turn (brain response time)
- File: `scripts/live_call.py`

### WebSocket Mode (used with simulator, future for Media Streams)

```
Twilio/Simulator ──WebSocket──▶ MediaStreamClient ──▶ AudioPipeline
                                                      ├── VAD
                                                      ├── STT (Granite)
                                                      └── TTS (placeholder)
                  ◀──WebSocket──  SessionRunner ◀──── Brain (Gemini)
```

- Bidirectional audio over WebSocket (Twilio Media Streams protocol)
- Our pipeline handles STT (Granite), VAD (Silero), TTS
- Same code runs against simulator and real Twilio
- File: `src/voice_agent/runner.py`

## Key Data Flows

### Inbound Audio (counterparty → agent)
```
G.711 μ-law (8kHz) → decode → upsample 16kHz → Silero VAD → Granite STT → Utterance
```

### Outbound Audio (agent → counterparty)
```
Brain text → TTS → PCM → resample 8kHz → G.711 encode → WebSocket
```

### Entity Extraction
```
Counterparty utterance
    ├── Pattern extractor (instant, high confidence)
    │   └── claim_status, dates, reference #, denial codes, etc.
    └── LLM extractor (async, medium confidence)
        └── free-form entities, action_required, etc.
    ↓
ExtractionResult (merged — pattern wins on conflict)
```

### Session State Machine
```
PRE_CALL → DIALING → IVR → HOLD → CONVERSATION → POST_CALL → DONE
                 ↓       ↓       ↓            ↓              ↓
              FAILED  FAILED  FAILED       HOLD (re-hold)  FAILED
```

## Directory Structure

```
voice-agent/
├── src/voice_agent/
│   ├── session.py              # Session state machine
│   ├── runner.py               # SessionRunner (orchestrates everything)
│   ├── events.py               # 30 typed domain events
│   ├── models.py               # Pydantic models (Disposition, PayorProfile)
│   ├── logging.py              # structlog JSON with correlation IDs
│   ├── metrics.py              # Counters and timers
│   ├── telephony/
│   │   ├── __init__.py         # TelephonyBackend protocol
│   │   ├── twilio_backend.py   # Twilio REST API implementation
│   │   └── media_stream.py     # WebSocket client (Media Streams)
│   ├── audio/
│   │   ├── codec.py            # G.711 μ-law, resampling, base64
│   │   ├── pipeline.py         # Full-duplex AudioPipeline
│   │   ├── vad.py              # Silero VAD wrapper
│   │   ├── hold.py             # Hold handler (stub)
│   │   └── transfer.py         # Transfer detector (stub)
│   ├── stt/
│   │   ├── __init__.py         # STTBackend protocol
│   │   ├── granite.py          # Granite 4.0 1B Speech (local)
│   │   └── whisper.py          # Whisper (stub)
│   ├── tts/
│   │   ├── __init__.py         # TTSBackend protocol
│   │   └── omnivoice.py        # OmniVoice (stub)
│   ├── brain/
│   │   ├── __init__.py         # BrainBackend protocol
│   │   ├── gemini.py           # Gemini API (v1 default)
│   │   └── claude.py           # Claude API (stub)
│   ├── ivr/
│   │   └── __init__.py         # IVR navigator (rule engine)
│   ├── scripts/
│   │   ├── __init__.py         # CallScript + ScriptGoal
│   │   ├── claim_status.py     # Tier 1A goal tree
│   │   ├── eligibility.py      # Tier 1B (stub)
│   │   ├── auth_status.py      # Tier 1D (stub)
│   │   └── fax_lookup.py       # Tier 1C (stub)
│   ├── extraction/
│   │   ├── __init__.py         # ExtractedEntity, ExtractionResult
│   │   ├── patterns.py         # Regex-based extraction
│   │   └── llm.py              # Gemini-based extraction
│   ├── db/
│   │   ├── tables.py           # SQLAlchemy models (5 tables)
│   │   ├── repository.py       # Queue state machine + repositories
│   │   └── engine.py           # DB engine factory
│   ├── queue/
│   │   └── __init__.py         # Work queue (stub)
│   ├── compliance/
│   │   ├── phi.py              # PHI accessor (whitelist enforcement)
│   │   └── audit.py            # Audit entry model
│   └── monitoring/
│       └── __init__.py         # Dashboard (stub)
├── simulator/
│   ├── server.py               # WebSocket server (Twilio protocol)
│   └── scenarios.py            # 5 built-in call scenarios
├── scripts/
│   ├── live_call.py            # Place a real call with Gemini brain
│   ├── telephony_hello_world.py
│   ├── run_simulator_e2e.py
│   └── db_setup.sh
├── tests/                      # 171 unit + 6 E2E tests
├── config/payors/              # Per-payor YAML profiles
├── alembic/                    # DB migrations
└── docs/                       # Requirements, plans, persona
```

## Tech Stack

| Layer | Choice | Status |
|---|---|---|
| Language | Python 3.13 | Active |
| Telephony | Twilio (dev account) | Working |
| Tunnel | cloudflared | Working |
| STT | Granite 4.0 1B Speech (local) | Implemented |
| STT (webhook) | Twilio built-in `<Gather>` | Working |
| TTS | Twilio Polly.Joanna (webhook mode) | Working |
| TTS (local) | OmniVoice (stub) | Not wired |
| Brain | Gemini 3.1 Flash Lite Preview | Working, 785ms TTFT |
| VAD | Silero VAD | Working |
| Database | Postgres (SQLAlchemy + Alembic) | Schema done |
| Logging | structlog (JSON) | Working |
| Web | FastAPI + uvicorn | Working (webhook) |
| Config | PyYAML | Template only |
