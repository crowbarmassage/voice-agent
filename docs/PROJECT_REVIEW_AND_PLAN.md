# Project Review & Plan of Attack

Date: 2026-04-22

## Executive summary

This repository is a **well-scoped architecture skeleton** for a healthcare RCM outbound voice-agent platform, with strong requirements and compliance framing but minimal executable implementation so far.

Current readiness is best described as:

- **Product / requirements maturity:** high
- **Architecture maturity:** medium (decomposition is sound; interfaces will need significant revision once real telephony integration begins)
- **Implementation maturity:** low (mostly protocol definitions, stubs, and data models)
- **Operational readiness:** low

The fastest path to value is to ship a narrow **Tier 1A claim-status MVP** for one payor in shadow mode, with strict compliance controls and aggressive observability, before expanding use cases.

---

## What the repo does well today

### 1) Excellent problem framing and sequencing

The docs clearly define use-case tiers, risk boundaries, and a practical build order. This reduces product thrash and makes technical decisions easier.

### 2) Sound modular decomposition

The package split (`telephony`, `audio`, `stt`, `tts`, `brain`, `ivr`, `queue`, `compliance`, etc.) is a strong basis for swappable backends and staged implementation. Note: the *decomposition* is right but the current *interfaces* are incomplete — `TelephonyBackend` is missing audio streaming and recording methods, `STTBackend` uses synchronous chunks where a streaming async iterator is needed, and `BrainBackend` doesn't account for its coupling to the PHI accessor and script engine. These protocols will undergo revision in Phase 0 when interfaces are frozen against real integration needs. No hold handler or transfer detector abstraction exists yet.

### 3) Early compliance-first posture

The explicit PHI gate (`PHIAccessor`) and audit-entry model point in the right direction for HIPAA minimum-necessary workflows and traceability.

### 4) Good type-safe primitives

`Protocol` usage for subsystem backends and Pydantic models for core records should scale well once real implementations are added.

---

## Gaps and risks

### 1) Implementation gap (largest)

Most core runtime classes are stubs (`Session`, `AudioPipeline`, `IVRNavigator`, backend implementations). The project currently cannot place or complete a real call.

### 2) Missing persistence and workflow mechanics

No DB schema/migrations or queue repository layer exist yet, and there is no scheduler/backoff engine for retries/business-hours gating.

### 3) Limited test safety net

`tests/` currently has no behavioral tests. This is a high-risk area given IVR variability and compliance constraints.

### 4) Security/compliance hardening incomplete

No implemented encryption/key-management strategy, access-control enforcement, or immutable-storage guarantees are present in code.

### 5) Operational controls not yet implemented

No metrics pipeline, alerting, SLOs, or failure-mode playbooks are implemented.

### 6) No telephony account or BAA chain started

Twilio HIPAA is a separate product tier requiring a sales conversation, BAA signing, and potentially weeks of provisioning. No telephony credentials, test phone numbers, or BAA agreements exist. This is a long-pole dependency that blocks all call-related development.

### 7) Brain model not committed

The brain is listed as "TBD" in the tech stack. This decision affects the entire architecture (cloud vs local, latency budget, cost model, BAA requirements) and cannot be deferred past Phase 0.

### 8) No real-world conversation data

No recordings of actual payor calls exist in the project. Without ground-truth data on what IVR trees look like, how reps actually respond, and what "unexpected" conversations contain, the script engine and brain prompts are designed in a vacuum. There is no test harness that can simulate a payor call for development iteration.

---

## Plan of attack (recommended)

## Phase 0 (Week 0–1): Foundation that de-risks everything

0. **Start Twilio HIPAA provisioning + BAA (day 1)**
   - Contact Twilio sales for HIPAA-eligible product access. This requires
     a signed BAA and may take 1–3 weeks to provision.
   - Obtain a test phone number for development.
   - In parallel, sign up for a standard Twilio account with a dev number
     for non-PHI integration testing (IVR navigation against live payors
     with dummy data). This unblocks telephony development immediately
     while the HIPAA tier is provisioned.
   - Begin BAA conversations with cloud hosting provider (AWS/Azure/GCP).

1. **Commit to a brain model for v1**
   - Recommendation: **Claude API (Anthropic)** for v1. Rationale:
     best-in-class instruction following for complex script execution,
     streaming support for low latency, managed infrastructure eliminates
     GPU provisioning complexity. Anthropic offers BAA for HIPAA use cases.
   - Fallback: GPT-4o (OpenAI BAA program) if Anthropic BAA timeline
     doesn't align.
   - Decision affects: architecture (cloud-first, no self-hosted GPU for
     brain), latency budget (API round-trip ~200-500ms + generation),
     cost model (~$0.01-0.05 per call for brain tokens), and BAA chain.
   - Local models (Gemma-4) reserved for v2 evaluation if cost optimization
     is needed at scale.

2. **Define interfaces concretely**
   - Freeze protocol signatures for Telephony, STT, TTS, Brain.
   - Revise `TelephonyBackend` to include: `get_audio_stream`,
     `play_audio`, `transfer`, `get_recording` (currently missing).
   - Revise `STTBackend` to use async streaming iterator instead of
     synchronous `transcribe_chunk`.
   - Revise `BrainBackend` to accept `PHIAccessor` + script state, not
     just raw strings.
   - Add `HoldHandler` and `TransferDetector` abstractions (currently
     not stubbed at all).
   - Add typed domain events (call_started, ivr_prompt_detected,
     hold_started, human_detected, transfer_detected, etc.).

3. **Create persistence baseline**
   - Add Postgres schema + migration tooling (Alembic).
   - Tables: `work_items`, `call_sessions`, `dispositions`, `audit_log`,
     `payor_profiles`.

4. **Introduce observability scaffolding**
   - Structured logging (JSON) with correlation IDs (`work_item_id`,
     `call_sid`, `session_id`).
   - Basic metrics counters/timers.

5. **Write non-negotiable tests first**
   - PHI whitelist enforcement tests.
   - Disposition model validation tests.
   - Queue state-transition tests.

6. **Collect real-world call data**
   - Have a human biller record 5–10 real claim status calls to your
     highest-volume payor (with appropriate consent/disclosure).
   - These recordings become ground truth for: IVR mapping, rep
     interaction patterns, entity extraction accuracy baselines, and
     the call simulator's scripts.
   - Transcribe and annotate: mark IVR prompts, hold segments, human
     pickup points, entities spoken by the rep.
   - This data directly feeds Phase 1 items 5 (IVR) and 7 (script engine).

## Phase 1 (Week 1–3): Tier 1A thin vertical slice (one payor)

Goal: complete one real claim-status call path in shadow mode.

1. **Build a call simulator (high-leverage dev tool)**
   - Replay recorded IVR audio from Phase 0 step 6 through a fake
     telephony endpoint (WebSocket server that speaks the same protocol
     as Twilio Media Streams).
   - Simulate: IVR prompts → hold music → human pickup → scripted rep
     dialogue (from annotated recordings).
   - All IVR navigation, hold handling, and conversation development
     iterates against the simulator first — not live calls. This saves
     hours of payor hold time per test cycle and makes development
     repeatable.
   - Gradually extend the simulator with edge cases: unexpected transfers,
     hostile reps, garbled audio, IVR loops, disconnects.

2. **Telephony integration (Twilio)**
   - Place outbound call, stream audio via Media Streams WebSocket, send
     DTMF, hang up, retrieve recording metadata.
   - Validate against both the call simulator and one real test call
     (to a non-PHI number like your own cell or a Twilio test endpoint).

3. **Session state machine implementation**
   - Implement deterministic lifecycle with explicit transitions and
     timeouts.

4. **Basic audio pipeline**
   - G.711 decode/encode + resampling + chunk transport.
   - Integrate VAD onset/offset signals.

5. **Single STT + TTS backend wired end-to-end**
   - Start with one stable STT path and one stable TTS path.
   - Favor reliability over model experimentation.
   - v1 recommendation: cloud STT with BAA (Google Speech or AWS
     Transcribe — telephony-optimized models, proven at 8kHz) for STT
     reliability. OmniVoice or cloud TTS for output.

6. **One payor IVR state machine**
   - Build from the annotated call recordings (Phase 0 step 6).
   - Hardcode known prompts + fallback strategies.
   - Test against the call simulator before live calls.

7. **Script engine v0 for claim status**
   - Goal tracking + read-back of high-risk entities (reference
     number/date).
   - Wire brain (Claude API) with system prompt containing: script goals,
     PHI accessor output (not raw context), conversation history.
   - Test brain responses against recorded rep dialogue from Phase 0.

8. **Disposition + audit writes**
   - Ensure append-only audit behavior in DB operations.

Exit criteria:
- 20+ shadow calls complete end-to-end with human review.
- No unlogged PHI disclosures.
- Median response latency and call-completion metrics collected.
- Call simulator covers the happy path + 3 edge cases (IVR loop,
  hold timeout, unexpected transfer).

## Phase 2 (Week 3–5): Reliability + compliance hardening

1. **Failure handling and retries**
   - Busy/no-answer/IVR-loop/hold-timeout policies with exponential backoff.

2. **Security controls**
   - At-rest encryption strategy, secret management, role-based access boundaries.

3. **Confidence scoring + review queue**
   - Flag low-confidence extractions for mandatory human validation.

4. **Runbooks + SLO draft**
   - Escalation and incident response docs.

Exit criteria:
- Repeatable performance over 100+ calls.
- Regression alerts operational.

## Phase 3 (Week 5+): Expand scope carefully

1. Add 1B (eligibility), then 1C (fax lookup), then 1D (auth status).
2. Expand payor count only after each new script stabilizes.
3. Introduce optional cloud/local backend swapping after baseline SLAs are met.

---

## Prioritized backlog (P0 / P1 / P2)

### P0 (immediate)
- Start Twilio HIPAA provisioning + BAA (long-pole, start day 1).
- Commit to Claude API as v1 brain; begin Anthropic BAA process.
- Revise protocol signatures (Telephony, STT, Brain) per gap analysis.
- Add `HoldHandler` and `TransferDetector` abstractions.
- Implement `Session` orchestration and transition table.
- Implement concrete `TwilioBackend` MVP methods.
- Implement queue repository + DB schema/migrations.
- Add core tests for PHI and queue transitions.
- Add structured logging and metrics hooks.
- Record 5–10 real claim status calls for ground-truth data.

### P1 (next)
- Build call simulator (fake Twilio Media Streams endpoint).
- Implement `AudioPipeline` real codec path.
- Implement `IVRNavigator` for first payor with loop detection.
- Implement `HoldHandler` (music classifier + human pickup detection).
- Implement extraction + read-back verification mechanics.
- Wire Claude API brain with PHI accessor + script state.
- Add dashboard MVP for call/disposition monitoring.

### P2 (later)
- Multi-backend STT/TTS routing.
- Cost optimization heuristics.
- Advanced IVR auto-adaptation and prompt clustering.

---

## Suggested success metrics for first 30 days

- **Completion rate (Tier 1A shadow):** target >60% with no human handoff.
- **Median hold handling stability:** no dropped calls during hold transitions.
- **Entity accuracy (human-reviewed):**
  - reference number ≥95%
  - status classification ≥95%
- **Compliance:** 100% audit coverage for PHI accesses/disclosures.
- **Ops:** <2% unclassified failures (every failure mapped to a reason code).

---

## Practical next actions (this week)

1. **Start Twilio HIPAA provisioning** — contact sales, begin BAA. In
   parallel, sign up for a standard Twilio dev account to unblock
   telephony integration testing with non-PHI data.
2. **Commit brain model** — lock in Claude API, begin Anthropic BAA
   conversation. Spike a test: send a claim-status system prompt +
   simulated rep dialogue to Claude, evaluate response quality.
3. **Record 3–5 real claim status calls** — highest-volume payor. Have
   a biller record them (with consent). Transcribe, annotate IVR/hold/
   human-pickup/entity segments.
4. Implement DB schema and queue repository.
5. Implement Session state machine skeleton with explicit transition guards.
6. Revise protocol signatures per gap analysis (Telephony, STT, Brain).
7. Add core tests for PHI whitelist and queue transitions.

Items 1–3 are new and de-risk the hardest unknowns (vendor provisioning,
brain quality, real-world call data). Items 4–7 are infrastructure that
can proceed in parallel. The call simulator (Phase 1 step 1) follows
once the recordings from item 3 are available.
