# Project Review & Plan of Attack

Date: 2026-04-22

## Executive summary

This repository is a **well-scoped architecture skeleton** for a healthcare RCM outbound voice-agent platform, with strong requirements and compliance framing but minimal executable implementation so far.

Current readiness is best described as:

- **Product / requirements maturity:** high
- **Architecture maturity:** medium-high
- **Implementation maturity:** low (mostly protocol definitions, stubs, and data models)
- **Operational readiness:** low

The fastest path to value is to ship a narrow **Tier 1A claim-status MVP** for one payor in shadow mode, with strict compliance controls and aggressive observability, before expanding use cases.

---

## What the repo does well today

### 1) Excellent problem framing and sequencing

The docs clearly define use-case tiers, risk boundaries, and a practical build order. This reduces product thrash and makes technical decisions easier.

### 2) Sound modular architecture

The package split (`telephony`, `audio`, `stt`, `tts`, `brain`, `ivr`, `queue`, `compliance`, etc.) is a strong basis for swappable backends and staged implementation.

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

---

## Plan of attack (recommended)

## Phase 0 (Week 0–1): Foundation that de-risks everything

1. **Define interfaces concretely**
   - Freeze protocol signatures for Telephony, STT, TTS, Brain.
   - Add typed domain events (call_started, ivr_prompt_detected, hold_started, etc.).

2. **Create persistence baseline**
   - Add Postgres schema + migration tooling.
   - Tables: `work_items`, `call_sessions`, `dispositions`, `audit_log`, `payor_profiles`.

3. **Introduce observability scaffolding**
   - Structured logging (JSON) with correlation IDs (`work_item_id`, `call_sid`, `session_id`).
   - Basic metrics counters/timers.

4. **Write non-negotiable tests first**
   - PHI whitelist enforcement tests.
   - Disposition model validation tests.
   - Queue state-transition tests.

## Phase 1 (Week 1–3): Tier 1A thin vertical slice (one payor)

Goal: complete one real claim-status call path in shadow mode.

1. **Telephony integration (Twilio)**
   - Place outbound call, stream audio, send DTMF, hang up, retrieve recording metadata.

2. **Session state machine implementation**
   - Implement deterministic lifecycle with explicit transitions and timeouts.

3. **Basic audio pipeline**
   - G.711 decode/encode + resampling + chunk transport.
   - Integrate VAD onset/offset signals.

4. **Single STT + TTS backend wired end-to-end**
   - Start with one stable STT path and one stable TTS path.
   - Favor reliability over model experimentation.

5. **One payor IVR state machine**
   - Hardcode known prompts + fallback strategies.

6. **Script engine v0 for claim status**
   - Goal tracking + read-back of high-risk entities (reference number/date).

7. **Disposition + audit writes**
   - Ensure append-only audit behavior in DB operations.

Exit criteria:
- 20+ shadow calls complete end-to-end with human review.
- No unlogged PHI disclosures.
- Median response latency and call-completion metrics collected.

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
- Implement `Session` orchestration and transition table.
- Implement concrete `TwilioBackend` MVP methods.
- Implement queue repository + DB schema/migrations.
- Add core tests for PHI and queue transitions.
- Add structured logging and metrics hooks.

### P1 (next)
- Implement `AudioPipeline` real codec path.
- Implement `IVRNavigator` for first payor with loop detection.
- Implement extraction + read-back verification mechanics.
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

1. Implement DB schema and queue repository.
2. Implement Session state machine skeleton with explicit transition guards.
3. Wire Twilio outbound call + DTMF + hangup happy path.
4. Add first end-to-end integration test with mocked telephony audio events.
5. Add a small CLI to execute one work item in shadow mode for debugging.

These five items create the minimum backbone needed to iterate safely and quickly.
