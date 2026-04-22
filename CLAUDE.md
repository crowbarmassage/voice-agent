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
| Brain | Gemini API (gemini-3.1-flash-lite-preview) — v1 default | Fast, streaming, good instruction-following |
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
│   ├── STT_FEATURES.md         # STT backend comparison + swappable architecture
│   └── PROJECT_REVIEW_AND_PLAN.md  # gap analysis, phased plan, prioritized backlog
├── simulator/                   # call simulator (fake Twilio Media Streams endpoint)
└── scripts/                     # utility scripts (db setup, payor profile tools)
```

## Key decisions made

- **Brain: Gemini API (gemini-3.1-flash-lite-preview) for v1.** Fast streaming,
  good instruction-following for script execution. Validated at 785ms TTFT.
  Local models (Gemma-4) reserved for v2 cost optimization evaluation.
- **Shadow mode mandatory.** v1 never writes to billing system automatically.
  Human reviews all dispositions.
- **Call simulator before live calls.** All IVR/hold/conversation development
  iterates against a simulator built from recorded real calls. Saves hours
  of payor hold time per test cycle.

## Conventions

- Use `typing.Protocol` for backend interfaces (STT, TTS, brain, telephony).
  A new backend = a new file, not a refactor.
- Payor profiles are YAML in `config/payors/`. One file per payor.
- Call scripts in `src/voice_agent/scripts/` are goal trees, not linear sequences.
- All PHI access goes through `compliance/phi.py` — never access PHI directly
  from claim context without the guardrail layer.
- Audit log writes go through `compliance/audit.py` — immutable, append-only.
- Tests mirror `src/` structure in `tests/`.
- The call simulator lives in `simulator/` and speaks the Twilio Media Streams
  WebSocket protocol so the same code runs against simulated and real calls.

## Build order (from PROJECT_REVIEW_AND_PLAN.md, revised)

### Phase 0 — Foundation (Week 0–1)
0. Start Twilio HIPAA provisioning + BAA (long-pole dependency)
1. Commit to Claude API as v1 brain; begin Anthropic BAA
2. Revise protocol signatures (Telephony, STT, Brain — current stubs incomplete)
3. DB schema + migrations (Alembic)
4. Structured logging + metrics scaffolding
5. Core compliance tests (PHI whitelist, queue transitions)
6. Record 5–10 real claim status calls for ground-truth data

### Phase 1 — Tier 1A thin vertical (Week 1–3)
1. Build call simulator (fake Twilio Media Streams endpoint from recordings)
2. Telephony integration (Twilio — outbound, DTMF, audio streaming)
3. Session state machine
4. Audio pipeline (G.711, resampling, VAD)
5. Single STT + TTS wired end-to-end
6. One payor IVR state machine (from annotated recordings)
7. Claim status script + brain (Claude API)
8. Disposition + audit writes

### Phase 2 — Reliability + compliance hardening (Week 3–5)
### Phase 3 — Expand scope (Week 5+)

See `docs/PROJECT_REVIEW_AND_PLAN.md` for full details, exit criteria, and
success metrics.

## Related projects

- `~/Github/models/voxtral-tts/` — local voice agent prototype (Gemma-4 +
  OmniVoice). STT/TTS research and experiments. The R&D sandbox that led
  to this production project.
