# Remaining Work — Build Plan

Updated: 2026-04-22

## Current State

The core call loop works end-to-end on real phone calls. The agent:
- Places outbound calls via Twilio
- Introduces itself as a billing assistant
- Provides patient info (DOB, member ID, claim #) when asked
- Extracts structured entities from rep responses (claim status, dates,
  reference numbers, denial codes, rep name)
- Reads back key info for confirmation
- Enforces guardrails (no SSN, no clinical, no payments, admin only)
- Detects "goodbye" and ends the call cleanly

**171 unit tests + 6 E2E integration tests passing.**

Validated on a live 7-turn phone call with all guardrails firing correctly.
Brain latency: 785ms–1696ms (within 2s budget).

---

## Tier 1: Shadow Mode (Blocks 3-8)

### Block 3: Disposition + audit writes
**Priority: HIGH — next task**

After each call ends, persist the results to the database.

- [ ] Disposition writer: serialize extracted entities, transcript, durations,
  outcome, confidence score → `dispositions` table
- [ ] Audit log writer: PHI fields disclosed → `audit_log` table
- [ ] Wire into `scripts/live_call.py` (print + persist after call)
- [ ] Wire into `runner.py` SessionRunner post-call hook
- [ ] Tests for disposition writer

**Files to create/edit:**
- `src/voice_agent/db/disposition_writer.py` (new)
- `src/voice_agent/compliance/audit.py` (edit — add write method)
- `src/voice_agent/runner.py` (edit — add post-call hook)
- `scripts/live_call.py` (edit — add DB write)
- `tests/test_disposition_writer.py` (new)

### Block 4: Dashboard MVP
**Priority: HIGH — needed for human review in shadow mode**

Web UI for reviewing call results. FastAPI + Jinja2 templates.

- [ ] Call list page: sessions with status, payor, duration, outcome
- [ ] Call detail page: transcript + extracted entities side by side
- [ ] Review queue: escalated + random sample for human review
- [ ] Basic metrics: calls today, success rate, avg hold time
- [ ] Approve/reject/flag buttons on review page

**Files to create:**
- `src/voice_agent/monitoring/dashboard.py`
- `src/voice_agent/monitoring/templates/` (HTML templates)

### Block 5: Payor profiles + queue scheduler
**Priority: MEDIUM**

- [ ] Create YAML profiles for UHC, BCBS, Aetna (IVR rules, business hours,
  hold timeout, concurrency cap)
- [ ] Payor profile loader (YAML → IVRConfig)
- [ ] Queue scheduler: loop pulling pending items, checking business hours
  and concurrency, spawning sessions
- [ ] Business hours gate (timezone-aware)
- [ ] Concurrency limiter (per-payor)

**Files to create/edit:**
- `config/payors/uhc.yaml`, `bcbs.yaml`, `aetna.yaml` (new)
- `src/voice_agent/queue/scheduler.py` (new)

### Block 6: Hardening
**Priority: MEDIUM**

- [ ] Hold timeout enforcement (hang up + reschedule after max_hold_minutes)
- [ ] Max call duration safety (15 min → polite close)
- [ ] Graceful degradation (STT/brain failure → apologize + reschedule)
- [ ] Confidence flagging (entities < 0.8 → flag for human review)
- [ ] Review routing (all escalated + 10-20% random sample → review queue)

### Block 7: Real TTS
**Priority: LOW for shadow mode (Twilio Polly works)**

- [ ] Wire OmniVoice for WebSocket mode (24kHz → resample → G.711)
- [ ] Or upgrade Twilio voice (Polly.Joanna is fine for shadow mode)
- [ ] Test on real calls — does it sound professional on PSTN?

### Block 8: Expand Tier 1 scripts
**Priority: MEDIUM — after shadow mode proves 1A works**

- [ ] 1B: Eligibility/benefits verification script + entity schema
- [ ] 1C: Fax/address lookup script (simplest)
- [ ] 1D: Authorization status check script
- [ ] Stubs already exist in `src/voice_agent/scripts/`

### Shadow Mode Exit Criteria

- 20+ shadow calls complete end-to-end with human review
- No unlogged PHI disclosures
- Median response latency < 2s
- Entity accuracy ≥95% for reference numbers and status
- Call simulator covers happy path + 3 edge cases
- Dashboard shows all calls with review capability

---

## Tier 2: Medium Intensity (after shadow mode)

These use cases require more back-and-forth, some judgment, and
action-triggering information. Infrastructure from Tier 1 is reused.

### 2A: Documentation request to SNF/hospice/HHA
- Call facility medical records, request specific documents
- **New:** fax triggering, multi-branch conversation, facility profiles
- Script: `scripts/documentation_request.py`

### 2B: Denial reason inquiry
- Call payor about denied claim, get CARC/RARC codes, appeal deadline
- **New:** denial code knowledge base, appeal deadline tracking
- Script: `scripts/denial_inquiry.py`

### 2C: Payment posting discrepancy
- Call payor about payment mismatch
- **New:** adjustment reason code understanding, dollar comparisons
- Script: `scripts/payment_discrepancy.py`

### 2D: Timely filing dispute
- Claim denied for timely filing, call with proof of submission
- **New:** evidence presentation, supervisor escalation
- Script: `scripts/timely_filing.py`

### Tier 2 Infrastructure
- [ ] Billing system integration (read claim data, write dispositions)
- [ ] Clearinghouse pre-check (EDI 276/277 — skip resolved claims)
- [ ] Fax integration (trigger outbound fax after call)
- [ ] Multi-payor IVR library (top 20 payors)
- [ ] IVR regression detection (alert when success rate drops)

---

## Tier 3: High Intensity (after Tier 2 is proven)

Adversarial or complex calls. Real money at stake. Clinical content
may surface. Deploy only after Tier 1-2 are battle-tested.

### 3A: Formal appeal / reconsideration
- **New:** appeal template library, policy citation, clinical boundary enforcement
- **Risk:** Bad appeal = revenue lost permanently

### 3B: Peer-to-peer review scheduling
- **New:** calendar coordination, clinical context passing
- **Risk:** Missed P2P = service not authorized

### 3C: Complex multi-claim resolution
- **New:** multi-claim context management, partial resolution handling
- **Risk:** Compounded errors across multiple claims

### 3D: Patient balance calls
- **New:** empathetic tone, FDCPA compliance, payment plans, AI disclosure
- **Risk:** Reputational damage, regulatory scrutiny
- **Requires:** Legal review per state before deploying

### 3E: Credentialing / enrollment follow-up
- **Risk:** Very high per-error (wrong date = months of claims deny)

### Tier 3 Infrastructure
- [ ] Appeal template management system
- [ ] Clinical document reference engine
- [ ] Multi-language STT/TTS
- [ ] Legal compliance review pipeline per state
- [ ] Sentiment detection (hostile, confused, distressed)
- [ ] Real-time supervisor monitoring

---

## Cross-Cutting (All Tiers)

### Security + Compliance
- [ ] Encryption at rest (AES-256 for recordings, transcripts)
- [ ] Secret management (Vault / AWS Secrets Manager)
- [ ] Role-based access control
- [ ] Breach notification workflow
- [ ] State telecom regulation tracking

### Infrastructure + Deployment
- [ ] Docker containerization
- [ ] Cloud deployment with BAA (AWS/Azure/GCP)
- [ ] Auto-scaling (containerized per-call for 50+ concurrent)
- [ ] CI/CD pipeline
- [ ] Database backups + disaster recovery

### Monitoring
- [ ] Grafana dashboards (replace v1 FastAPI dashboard at scale)
- [ ] Alerting (PagerDuty/Opsgenie)
- [ ] SLOs + runbooks
- [ ] Cost tracking per call
- [ ] Monthly quality audit reports

### Optimization
- [ ] Local brain (Gemma-4) for cost reduction at scale
- [ ] STT cost/accuracy tradeoff (Granite vs cloud)
- [ ] Multi-claim batching (amortize hold time)
- [ ] Predictive hold time estimation
