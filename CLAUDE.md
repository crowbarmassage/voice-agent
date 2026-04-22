# Voice Agent — RCM Outbound Calling Platform

## What this is

Production voice agent platform for healthcare revenue cycle management (RCM).
Agents make outbound phone calls to counterparties — payors, SNFs, hospices,
home health agencies — to handle routine billing tasks: claim status checks,
eligibility verification, auth status, documentation requests, denial inquiries.

The value proposition: an RCM team's billers spend hours on hold with payors.
This platform runs 50+ calls in parallel, navigates IVR phone trees, waits on
hold, conducts the conversation when a human picks up, extracts structured data,
and logs dispositions — freeing billers for higher-value work.

## Architecture overview

```
Work Queue (Postgres)
    │
    ▼
Session Manager (one per active call)
    ├── Pre-call: context assembly, payor profile, business hours check
    ├── Telephony Adapter (Twilio/Telnyx HIPAA)
    │       ├── Outbound call placement (PSTN/SIP)
    │       ├── DTMF sending (IVR navigation)
    │       └── Bidirectional audio stream (WebSocket)
    ├── Audio Pipeline
    │       ├── Inbound: G.711 decode → 16kHz upsample → VAD → STT
    │       └── Outbound: Brain text → TTS → downsample → G.711 encode
    ├── IVR Navigator (per-payor state machine)
    ├── Hold Handler (music detection, human pickup detection)
    ├── Brain (conversation LLM + script engine)
    │       ├── Goal-tree script execution
    │       ├── Entity extraction (real-time)
    │       └── Read-back verification
    ├── Escalation Handler (warm transfer or polite close)
    └── Post-call: disposition record, retry scheduling, audit log
```

## Build phase

Currently building **Tier 1** (lowest intensity/downside use cases):
- 1A: Claim status inquiry
- 1B: Eligibility / benefits verification
- 1C: Fax number / mailing address lookup
- 1D: Authorization status check

See `docs/TIER1_FEATURES.md` for the full 42-feature breakdown and build order.
See `docs/RCM_VOICE_AGENTS.md` for all tiers and the full feature requirements.

## Key constraints

- **HIPAA compliance is non-negotiable.** Every vendor needs a BAA. PHI
  encrypted in transit (SRTP) and at rest (AES-256). Minimum necessary
  disclosure. Immutable audit logs.
- **AI disclosure from day one.** Agent identifies itself as automated at
  the start of every call.
- **Shadow mode first.** v1 does NOT write back to the billing system.
  Dispositions are logged and reviewed by humans. Production write-back
  comes after 2 weeks of validated shadow-mode accuracy.
- **English only.** Primary language is English. No multilingual requirement.

## Tech stack (planned)

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.12 | async where possible |
| Telephony | Twilio HIPAA | BAA available, Media Streams for audio |
| STT | Granite 4.0 1b Speech (mlx-audio) or cloud STT with BAA | Keyword biasing for medical terms |
| TTS | OmniVoice or cloud TTS | Professional, telephony-optimized voice |
| Brain | TBD — Claude API, Gemma, or fine-tuned smaller model | Needs BAA if cloud; needs <2s latency |
| VAD | Silero VAD | Lightweight, MIT, runs on CPU |
| Queue | Postgres | Work items, dispositions, audit log |
| Monitoring | Grafana + Postgres | Call dashboard, metrics |
| Hosting | TBD — cloud with BAA | AWS/Azure/GCP |

## Project structure

```
voice-agent/
├── CLAUDE.md                    # this file
├── README.md
├── pyproject.toml
├── config/
│   └── payors/                  # per-payor YAML profiles (IVR maps, timeouts)
│       └── _template.yaml
├── src/voice_agent/
│   ├── __init__.py
│   ├── session.py               # session manager (call lifecycle orchestrator)
│   ├── telephony/               # telephony adapter (Twilio/Telnyx abstraction)
│   ├── audio/                   # audio pipeline (codec, VAD, AEC, resampling)
│   ├── stt/                     # STT backends (protocol + implementations)
│   ├── tts/                     # TTS backends (protocol + implementations)
│   ├── brain/                   # conversation LLM (protocol + implementations)
│   ├── scripts/                 # call scripts (goal trees per use case)
│   ├── extraction/              # entity extraction + confidence scoring
│   ├── ivr/                     # IVR navigation (per-payor state machines)
│   ├── queue/                   # work queue manager
│   ├── compliance/              # PHI guardrails, audit logging
│   └── monitoring/              # dashboard, metrics, alerting
├── tests/
├── docs/
│   ├── RCM_VOICE_AGENTS.md     # master requirements + use case tiers
│   ├── TIER1_FEATURES.md       # 42-feature breakdown for Tier 1
│   └── STT_FEATURES.md         # STT backend comparison + swappable architecture
└── scripts/                     # utility scripts (db setup, payor profile tools)
```

## Conventions

- Use `typing.Protocol` for backend interfaces (STT, TTS, brain, telephony).
  A new backend = a new file, not a refactor.
- Payor profiles are YAML in `config/payors/`. One file per payor.
- Call scripts in `src/voice_agent/scripts/` are goal trees, not linear sequences.
- All PHI access goes through `compliance/phi.py` — never access PHI directly
  from claim context without the guardrail layer.
- Audit log writes go through `compliance/audit.py` — immutable, append-only.
- Tests mirror `src/` structure in `tests/`.

## Build order (from TIER1_FEATURES.md §J)

1. Telephony hello-world (place call, play TTS, record, hang up)
2. Audio pipeline (bidirectional: send TTS to call, receive + transcribe)
3. IVR navigator for one payor (highest-volume)
4. Hold handler (detect hold, wait, detect human pickup)
5. Claim status script + brain (live call in shadow mode)
6. Entity extraction + disposition logging
7. Dashboard + review UI
8. Shadow mode on 3 payors (2 weeks)
9. Expand to 1B/1C/1D scripts
10. Promote to production (enable write-back for high-confidence dispositions)

## Related projects

- `~/Github/models/voxtral-tts/` — local voice agent prototype (Gemma-4 +
  OmniVoice). STT/TTS research and experiments. The R&D sandbox that led
  to this production project.
