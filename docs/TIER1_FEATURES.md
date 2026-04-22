# Tier 1 Feature Breakdown — Every Feature Needed

Exhaustive list of what must be built, bought, or integrated to ship Tier 1
(claim status, eligibility, auth status, fax/address lookup). Organized by
the lifecycle of a single outbound call, then cross-cutting concerns.

---

## A. Pre-Call

Everything that happens before the phone rings.

### A1. Work queue
- Pull next work item from a queue (claim to check, eligibility to verify,
  etc.). Each item has: use case type, payor/facility name, phone number,
  and a structured context payload.
- Mark item as `in_progress` so no other agent picks it up.
- For v1 this can be a Postgres table, a Redis queue, or even a CSV-to-API
  bridge. Does not need to be the billing system directly — a nightly export
  or manual upload is fine to start.

### A2. Claim context assembly
- For each work item, assemble the data the agent needs to carry into the
  call. Per use case:

  | Use case | Context fields |
  |---|---|
  | **1A. Claim status** | Patient name, DOB, member ID, claim #, date of service, billed CPT/HCPCS, billed amount, payor name, payor phone #, NPI, tax ID |
  | **1B. Eligibility** | Patient name, DOB, member ID, subscriber name (if different), payor name, payor phone #, plan type (if known), NPI, tax ID |
  | **1C. Fax/address** | Facility name, facility phone #, department (medical records, billing, etc.), reason for request (e.g. "medical records request for [patient name]") |
  | **1D. Auth status** | Patient name, DOB, member ID, auth #, service requested, date of service, payor name, payor phone #, NPI, tax ID |

- Source: billing system export, clearinghouse pull, or manual entry for v1.

### A3. Pre-call electronic check (optional but saves calls)
- Before calling about claim status (1A), check EDI 276/277 (electronic
  claim status) via clearinghouse. If the claim just paid or is already in
  a known terminal state, skip the call.
- Before calling about eligibility (1B), check EDI 270/271. If electronic
  eligibility is current and complete, skip the call.
- This is an optimization — not required for v1 but cuts call volume by
  20–40% on day one.

### A4. Payor profile lookup
- Each payor has a profile:
    - Phone number(s) per department (claims, eligibility, auth, provider
      services)
    - IVR navigation map (see B3)
    - Expected hold time range
    - Max hold timeout before hangup-and-retry
    - Business hours + time zone
    - Concurrency cap (max simultaneous calls to this number)
    - Whether AI disclosure is required (based on state of the payor's
      call center, if known)
    - Known quirks ("UHC always asks for tax ID before NPI", "Aetna's
      claims line disconnects after 90 min hold")
- For v1: a YAML/JSON config file per payor. 3–5 payors to start (your
  highest-volume ones).
- Long-term: a payor profile database maintained by ops.

### A5. Business hours gate
- Check: is the destination within business hours right now?
- If not, reschedule the work item to the next valid window.
- Needs: payor/facility timezone, business hours per destination, holiday
  calendar (federal holidays for Medicare, payor-specific closures).

### A6. Concurrency check
- Check: are we already at the concurrent call limit for this destination
  phone number?
- If yes, hold the item in queue until a slot opens.

---

## B. Call Placement & IVR Navigation

From dialing through reaching a human (or automated status system).

### B1. Outbound call origination
- Place a PSTN call via telephony API (Twilio, Telnyx, Bandwidth, Vonage).
- Present a valid, callback-capable caller ID with STIR/SHAKEN A-attestation.
- Handle: busy signal, no answer (ring timeout ~45s), fast busy, network
  error. Each triggers a reschedule with backoff.
- Start call recording from the first ring.

### B2. AI disclosure (call opening)
- When the call connects (before IVR or after a human picks up — depends
  on the call flow), deliver a disclosure if required:
  "This is an automated assistant calling from [Practice] billing office
  on behalf of [Biller Name]."
- Whether to disclose is driven by the payor profile (A4) and a global
  policy flag. Build it in from day one even if not all states require it.

### B3. IVR detection and navigation
- **DTMF prompt detection.** Detect "Press 1 for claims, press 2 for..."
  via STT transcription of the IVR audio. Agent reads the transcript,
  matches it against the payor's IVR map, and sends the correct DTMF
  tone via the telephony API.
- **Speech prompt detection.** Some IVRs require spoken input ("say
  'claims' or 'billing'"). Agent uses TTS to speak the correct response.
- **NPI/tax ID/member ID entry.** Some IVRs ask for these via keypad.
  Agent sends the digits as DTMF from the claim context.
- **IVR map per payor.** A structured script (state machine or decision
  tree) that says: "when you hear X, press Y" or "when you hear X, say Y."
  Per payor, per department. Updated when the IVR changes (detected via
  regression monitoring — see G4).
- **Unknown prompt fallback.** If the IVR says something not in the map,
  the agent tries a generic strategy (press 0 for operator, say "agent",
  say "representative"). If that fails, log the failure, hang up, and
  flag for human review of the IVR map.
- **IVR loop detection.** If the agent has been in the IVR for >3 minutes
  or has hit the same prompt twice, it's stuck. Escalate or retry with a
  different path.

### B4. Voicemail detection
- Detect if the call goes to voicemail (answering machine detection / AMD).
  Twilio and most telephony APIs have built-in AMD.
- Policy per use case:
    - Payor calls: hang up and retry (payors don't return voicemails from
      billing offices).
    - Facility calls (1C — fax/address lookup): optionally leave a short
      message with callback number. **No PHI in voicemail.**

### B5. Hold detection and patience
- **Hold music classifier.** Detect that we've been placed on hold.
  Approach: a lightweight audio classifier (silence + music + periodic
  spoken messages = hold). Can be simple: if no speech is detected for
  >15 seconds + audio energy is present (music), we're on hold.
- **Periodic message detection.** "Your call is important to us, please
  continue to hold." Detect these via STT, confirm they're hold messages
  (not a human returning), and continue waiting.
- **Hold timer.** Track how long we've been on hold. If it exceeds the
  payor profile's max hold timeout, hang up and reschedule.
- **Human pickup detection.** When a human finally comes on the line after
  hold, detect the transition. Cues: speech directed at the caller ("thank
  you for holding, how can I help you?"), silence after hold music stops,
  a greeting pattern. The agent must respond within ~1 second of detecting
  a human — any longer and the rep thinks the line is dead.

### B6. Transfer detection
- The rep may transfer the agent to another department. Detect: hold music
  resuming briefly, a new voice greeting, "let me transfer you to..."
- When transferred, the agent resets its conversation state for the new
  rep (re-identifies, re-states purpose) but retains the claim context
  and any info already gathered.
- If transferred to an unexpected department (not in the script), log and
  adapt if possible, or escalate.

---

## C. Conversation — Speaking and Listening

The actual exchange with the counterparty once a human (or automated system)
is reached.

### C1. STT — real-time transcription of counterparty
- Transcribe the counterparty's speech in near-real-time.
- **Latency budget:** <500ms from end-of-utterance to transcript available.
- **Audio conditions:** 8kHz G.711 PSTN audio (narrow-band, compressed,
  noisy). The STT model must handle this. If using a model trained on 16kHz
  clean audio (Whisper, Granite), either:
    - Upsample the 8kHz PSTN audio (quality loss but functional), or
    - Use an STT model fine-tuned on telephony audio, or
    - Use a telephony-aware STT service (Google Speech-to-Text telephony
      model, AWS Transcribe Call Analytics, Azure conversational).
- **VAD (voice activity detection).** Detect when the counterparty starts
  and stops speaking. Drives turn-taking: the agent doesn't talk while the
  rep is talking (unless barged in on). Silero VAD.
- **Endpointing.** Detect when the counterparty has finished their turn.
  Not just silence — natural pauses (the rep looking something up) should
  not be misinterpreted as turn-completion. Configurable silence threshold:
  1.5–2s for normal turns, 8–12s for "rep is working" pauses.
- **Confidence scores.** Per-utterance or per-word confidence from the STT.
  Low-confidence transcripts trigger verification (read-back) or are
  flagged in the disposition.

### C2. TTS — agent voice output
- Generate speech from the agent's text responses.
- **Voice quality:** Professional, calm, clear. Not uncanny-valley. Must
  sound like a competent billing office employee. Consistent voice
  throughout the call.
- **Telephony-optimized.** Output must survive G.711 codec compression
  and sound good on the other end. 8kHz/16kHz output, no wideband
  features that degrade on narrowband. Test with actual PSTN round-trip,
  not just local playback.
- **Alphanumeric verbalization.** Claim numbers, member IDs, NPI, tax ID
  must be spoken clearly. "Claim number ending in 4-4-7-2" (digit by
  digit, with pauses). Dates: "March third, twenty twenty-five." Dollar
  amounts: "one thousand two hundred and thirty-four dollars."
- **Speed and pacing.** Slightly slower than normal conversational speed.
  Payor reps are typing while listening — give them time.
- **Barge-in support.** If the counterparty starts talking while the agent
  is speaking, the agent must stop TTS output immediately, switch to
  listening mode, and process what the counterparty said.
  Requires: VAD running on incoming audio concurrently with TTS output.
  AEC (acoustic echo cancellation) so the agent's own output doesn't
  trigger its own VAD.

### C3. Turn-taking and silence management
- **Turn protocol:** Agent speaks → waits → counterparty speaks → agent
  processes → agent speaks. Natural conversational flow.
- **Don't jump the gun.** After asking a question, wait at least 2s before
  assuming the rep didn't hear. Some reps are slow.
- **Working silence tolerance.** If the rep says "let me look that up" and
  goes quiet for 30 seconds, that's fine. Don't reprompt. After the
  configured patience timeout (8–12s of silence with no "working" cue),
  gently ask: "Are you still there?" or "Take your time, I'm here."
- **Simultaneous speech handling.** If both parties start talking at the
  same time, agent yields (stops talking, lets the rep go first). This is
  the polite behavior and prevents confusion.

### C4. Script execution engine
- The brain executes a structured script per use case. Each script is a
  goal tree, not a linear sequence. Goals for Tier 1:

  **1A. Claim status script goals:**
  1. Identify self and practice (name, NPI, tax ID)
  2. State purpose ("checking status of a claim")
  3. Provide claim identifiers (patient name, DOB, member ID, claim #, DOS)
     — in whatever order the rep asks for them
  4. Ask: "What is the current status of this claim?"
  5. Extract: status (paid, denied, pending, in process, etc.), and if
     applicable: denial reason, expected payment date, any required action
  6. If rep gives partial info, ask follow-up questions
  7. Read-back: confirm key info ("So the claim is currently pending and
     expected to process by May 30th?")
  8. Thank and close

  **1B. Eligibility script goals:**
  1. Identify self and practice
  2. State purpose ("verifying eligibility for a patient")
  3. Provide patient identifiers
  4. Ask: active/inactive, plan name, effective dates, copay, coinsurance,
     deductible (met/remaining), out-of-pocket max, any auth requirements
  5. Read-back key financials
  6. Thank and close

  **1C. Fax/address script goals:**
  1. Identify self and practice
  2. Ask for the correct fax number or mailing address for [department]
  3. Read-back the number/address
  4. Thank and close

  **1D. Auth status script goals:**
  1. Identify self and practice
  2. State purpose ("checking status of a prior authorization")
  3. Provide auth # and patient identifiers
  4. Ask: approved/pending/denied, if approved — effective dates and
     approved units/services, if denied — reason and appeal process
  5. Read-back
  6. Thank and close

- **Dynamic reordering.** The rep may ask for identifiers in a different
  order than the script expects. The brain must respond to "what's the
  date of birth?" with the DOB from context, regardless of where in the
  script it currently is.
- **Unexpected question handling.** Rep asks something not in the script
  ("what's the diagnosis code?" during a claim status call). If the answer
  is in the claim context, provide it. If not, say "I don't have that
  information available, but I can have someone call back with it."

### C5. Entity extraction
- As the counterparty speaks, extract structured entities from the
  transcript in real time. Per use case:

  | Use case | Entities to extract |
  |---|---|
  | **1A. Claim status** | Claim status (enum: paid/denied/pending/in-process/other), denial reason code (CARC/RARC), expected payment date, check/EFT number, adjustment amount, rep name, reference/call ID |
  | **1B. Eligibility** | Active (Y/N), plan name, effective date, term date, copay, coinsurance %, deductible ($), deductible met ($), OOP max ($), OOP met ($), auth required (Y/N), rep name, reference/call ID |
  | **1C. Fax/address** | Fax number, mailing address, department name, contact name |
  | **1D. Auth status** | Auth status (approved/pending/denied), approved services, approved units, effective dates, denial reason, appeal deadline, rep name, reference/call ID |

- **Extraction method.** Two approaches, not mutually exclusive:
    - LLM-based: the brain (same model running the conversation) extracts
      entities from its own transcript context. Natural but needs
      prompt engineering to output structured data.
    - Post-processing: after each counterparty turn, run a lightweight
      extraction pass (regex for phone/fax numbers, NER for names/dates,
      pattern match for claim statuses). Faster, more reliable for
      well-structured data.
- **Confidence tagging.** Each extracted entity gets a confidence level.
  Source: STT confidence on the words that contained the entity, plus
  whether the entity was verified via read-back.

### C6. Verification / read-back
- For every high-value extracted entity (reference number, deadline, fax
  number, dollar amount, date), the agent reads it back:
  "Just to confirm, the reference number is Alpha Bravo 4-4-7-2?"
- If the rep corrects it, update the extraction.
- If the rep confirms, mark the entity as verified (high confidence).
- **When to read back:** always for reference numbers, fax numbers, dates,
  and dollar amounts. Skip for low-value entities (rep name, general
  status).
- **NATO phonetic alphabet for alphanumerics** (optional but reduces
  errors on PSTN): "A as in Alpha, B as in Bravo."

### C7. Escalation to human
- Trigger conditions for Tier 1:
    - Rep asks a question the agent can't answer and it's not in the claim
      context
    - Rep becomes hostile, confused, or asks to speak to a person
    - Rep transfers to an unexpected department
    - STT confidence is too low to continue (can't understand the rep)
    - Agent has been in the conversation for >10 minutes without completing
      any script goals (something is off)
    - Compliance trigger: rep asks agent to confirm clinical information
- **Escalation action:** warm transfer to a human biller (if available) or
  polite close + reschedule:
    - Warm transfer: "One moment please, let me connect you with my
      colleague." Transfer the call with transcript + context to the human's
      softphone.
    - Polite close: "I apologize, I'm not able to help with that. A member
      of our team will call back. Thank you for your time."
- **Log the escalation reason.** Every escalation is a data point for
  improving the agent.

---

## D. Post-Call

### D1. Call disposition record
- Structured record written after every call:
  ```
  {
    work_item_id: "...",
    use_case: "claim_status",
    payor: "UHC",
    phone_number: "1-800-...",
    call_start: "2026-04-21T10:03:22Z",
    call_end: "2026-04-21T10:47:15Z",
    hold_duration_s: 2340,
    conversation_duration_s: 195,
    outcome: "completed" | "escalated" | "failed" | "voicemail" | "no_answer",
    extracted_entities: { ... },
    entities_verified: ["reference_number", "expected_date"],
    escalation_reason: null | "...",
    rep_name: "...",
    reference_number: "...",
    full_transcript: "...",
    recording_path: "s3://...",
    confidence_score: 0.92,
    retry_needed: false,
    next_action: "none" | "retry" | "human_review"
  }
  ```

### D2. Write-back to billing system
- For v1 / shadow mode: **do not write back automatically.** Log the
  disposition and let a human review and enter it manually.
- For v2+: write the extracted entities back to the billing system
  (claim status updated, eligibility record updated, fax number stored).
  Only write entities with high confidence + verification. Flag
  low-confidence entities for human review.
- Idempotent: if the same claim is checked twice, the second write
  overwrites the first cleanly.

### D3. Retry scheduling
- If the call failed (busy, no answer, IVR failure, hold timeout,
  escalation without resolution), reschedule the work item.
- Backoff schedule: 30 min → 2 hr → next business day → 2 business days.
- Max retries per item per week: configurable (default 3).
- If max retries exhausted, move to a human-action-required queue.

### D4. Call recording storage
- Save the full call recording (both sides) encrypted at rest.
- Index by work item ID, payor, date, outcome.
- Retention per policy (6–10 years for billing records).
- Access-controlled: only authorized RCM staff.

### D5. Queue advancement
- Mark the work item as completed (if resolved) or rescheduled (if retry).
- If the call surfaced a new action (e.g., "claim denied, you need to
  appeal" — discovered during a status check), optionally create a new
  work item for Tier 2 follow-up (or just flag it for human triage).

---

## E. Compliance — Tier 1 Minimum

### E1. HIPAA — minimum necessary
- Agent discloses only the PHI needed for the call purpose:
    - Claim status: patient name, DOB, member ID, claim #, DOS. Do NOT
      volunteer diagnosis, procedure details, or dollar amounts unless the
      rep asks.
    - Eligibility: patient name, DOB, member ID.
    - Fax/address: facility name, department. May need patient name only if
      requesting records for a specific patient.
    - Auth status: patient name, DOB, member ID, auth #.
- PHI disclosure is **reactive** (in response to rep's request), not
  proactive (agent doesn't dump all context at once).

### E2. Encryption
- Audio in transit: SRTP (Twilio/Telnyx support this natively).
- Audio at rest: AES-256 encrypted storage.
- Transcripts at rest: encrypted. PHI fields additionally tokenized or
  redacted in logs that don't need them.
- No PHI in plaintext application logs.

### E3. BAA chain
- Signed BAA with every vendor:
    - Telephony provider (Twilio has a HIPAA-eligible product with BAA)
    - Cloud hosting (AWS/Azure/GCP — all offer BAAs for HIPAA-eligible
      services)
    - STT provider (if cloud-hosted, e.g., Google Speech, AWS Transcribe —
      both offer BAAs; if self-hosted, no BAA needed for STT)
    - TTS provider (if cloud-hosted; if self-hosted, not needed)
    - Call recording storage (S3 with BAA, or HIPAA-eligible storage)
- No vendor without a BAA touches PHI. Period.

### E4. AI disclosure
- Agent identifies itself as automated at the start of every call where
  required (see payor profile A4).
- Default-on for v1 — better to over-disclose than under-disclose.
- Script: "Hi, this is [Agent Name], an automated assistant calling from
  [Practice Name] billing office."

### E5. Audit log
- Every call logged with: timestamp, work item ID, payor, PHI fields
  accessed, PHI fields disclosed, outcome, escalation events.
- Immutable append-only log. Separate from application logs.
- Queryable for compliance audits ("show me all calls where patient DOB
  was disclosed to payor X in Q1 2026").

### E6. No clinical content
- Hard guardrail in the brain's system prompt: the agent is administrative
  only. It does not interpret clinical information, does not comment on
  medical necessity, does not discuss diagnoses beyond reading a code
  if asked. If the conversation goes clinical, the agent deflects:
  "I'm only able to help with billing questions. A clinical team member
  can follow up on that."

---

## F. Infrastructure

### F1. Session manager
- Orchestrates the lifecycle of a single call: pre-call setup → call
  placement → IVR → hold → conversation → post-call.
- Manages the state machine for one call session.
- Holds the claim context, conversation history, extracted entities, and
  script state in memory for the duration of the call.

### F2. Telephony adapter
- Abstraction over the telephony provider (Twilio, Telnyx, etc.).
  Interface:
    - `place_call(to, from, callback_url) → call_sid`
    - `send_dtmf(call_sid, digits)`
    - `play_audio(call_sid, audio_stream)` (for TTS output)
    - `get_audio_stream(call_sid) → audio_stream` (incoming audio for STT)
    - `transfer(call_sid, to)`
    - `hangup(call_sid)`
    - `get_recording(call_sid) → url`
  Twilio Media Streams (WebSocket) or Telnyx Media Forking provide the
  real-time bidirectional audio stream needed for STT + TTS.

### F3. Audio pipeline
- **Inbound path:** telephony audio stream (8kHz G.711 μ-law) → decode →
  upsample to 16kHz (for STT models expecting 16kHz) → VAD → STT →
  transcript.
- **Outbound path:** brain text → TTS → audio → downsample to 8kHz if
  needed → G.711 encode → telephony audio stream.
- Both paths run concurrently. Full-duplex audio.
- **AEC:** The outbound TTS audio must be subtracted from the inbound
  stream before hitting VAD/STT, otherwise the agent hears itself.
  Options: software AEC (speexdsp, WebRTC APM), or handle at the
  telephony layer (Twilio Media Streams sends a separate inbound stream
  that excludes the agent's own audio — verify this).

### F4. Concurrency runtime
- Multiple calls run simultaneously. Each call is an independent session
  with its own state, audio streams, STT instance, and brain context.
- Architecture options:
    - **Async Python (asyncio):** One process, many coroutines. Good for
      I/O-bound work (hold waiting, network calls). STT/TTS/brain are
      CPU/GPU-bound — offload to thread pools or separate processes.
    - **Worker processes:** One process per active call. Simpler isolation
      but heavier resource footprint.
    - **Containerized:** Each call in a container. Cleanest isolation,
      easiest to scale horizontally, heaviest overhead.
- For v1 with <10 concurrent calls: async Python + thread pool for
  STT/TTS. For scale (50+): containerized with a job scheduler (K8s,
  ECS).

### F5. STT service
- Hosts the STT model and exposes a streaming transcription API.
- For v1: single GPU instance running Granite or Whisper, shared across
  concurrent calls. Batch incoming audio chunks and return transcripts.
- For scale: STT-as-a-service with auto-scaling (or use a managed service
  like Google Speech / AWS Transcribe with BAA).

### F6. TTS service
- Same pattern as STT. Hosts OmniVoice or equivalent, exposes a synth API.
- Voice: one consistent voice across all calls. Pre-generated reference
  (like the auntie.wav pattern) for voice cloning, or a fixed voice-design
  instruct.
- For scale: TTS-as-a-service. Latency budget: <1s from text to first
  audio byte (streaming TTS preferred so the agent can start speaking
  before the full utterance is synthesized).

### F7. Brain service
- Hosts the conversation LLM. Receives: system prompt (with script + claim
  context via PHI accessor) + conversation history + latest counterparty
  utterance. Returns: agent's next response.
- **v1: Claude API (Anthropic) with BAA.** Best instruction-following for
  complex script execution with dynamic branching. Streaming support for
  low latency. Managed infrastructure eliminates GPU provisioning. BAA
  available for HIPAA compliance.
- Local models (Gemma-4, fine-tuned smaller models) reserved for v2
  evaluation if cost optimization is needed at scale.
- **Latency budget:** <2s from receiving counterparty transcript to first
  TTS audio byte reaching the telephony stream. This is the total of:
  brain inference + TTS synthesis + audio encoding. Streaming both brain
  and TTS (brain streams tokens → TTS synthesizes sentence-by-sentence →
  audio streams to telephony) is the right architecture to hit this budget.

### F8. Call simulator (dev/test infrastructure)
- A fake telephony endpoint that speaks the Twilio Media Streams WebSocket
  protocol. Replays recorded IVR audio, simulates hold music, and responds
  with scripted rep dialogue from annotated real call recordings.
- All IVR navigation, hold handling, and conversation development iterates
  against the simulator first — not live calls. Saves hours of payor hold
  time per test cycle and makes development repeatable and deterministic.
- Extend with edge cases over time: unexpected transfers, hostile reps,
  garbled audio, IVR loops, mid-call disconnects, simultaneous speech.
- Lives in `simulator/` directory, separate from production code.

---

## G. Monitoring & QA — Tier 1 Minimum

### G1. Call dashboard
- Real-time: calls in progress, on hold, in IVR, in conversation,
  completed, failed, escalated.
- Per-payor metrics: avg hold time, avg conversation time, success rate,
  IVR failure rate.
- For v1: a simple web dashboard or even a CLI monitor. Grafana + Postgres
  is fine.

### G2. Transcript review queue
- All escalated calls go into a human review queue.
- Random sample (10–20%) of successful calls also queued for review.
- Reviewer scores: accuracy of extracted entities, appropriateness of
  agent responses, compliance adherence.
- For v1: a simple web UI that shows transcript + extracted entities
  side by side, with approve/reject/flag buttons.

### G3. Confidence flagging
- Extracted entities below a confidence threshold (e.g., 0.8) are flagged
  for human verification before being written to the billing system.
- Surfaced in the disposition record and the review queue.

### G4. IVR regression detection
- Track IVR navigation success rate per payor per week.
- If success rate drops (e.g., UHC claims IVR was 95% navigable, now 60%),
  alert. Probable cause: IVR menu changed. Human reviews a failed
  recording, updates the IVR map (A4/B3).

### G5. Cost tracking
- Per-call cost: telephony minutes (inbound pricing varies; outbound is
  typically $0.01–0.02/min) + compute (GPU time for STT/TTS/brain).
- Compare to: estimated human cost per call (salary ÷ calls/hour, typically
  $3–8/call including hold time). This ratio is the ROI metric.

---

## H. Feature Count Summary

| Layer | Features | Build vs Buy |
|---|---|---|
| A. Pre-call | 6 | Build (queue, context assembly, payor profiles, scheduling) |
| B. Call & IVR | 6 | Build + Buy (telephony API from vendor, IVR logic is custom) |
| C. Conversation | 7 | Build (brain, scripts, extraction, read-back, escalation) |
| D. Post-call | 5 | Build (disposition, retry, storage) |
| E. Compliance | 6 | Build + Legal (BAA procurement, audit logging, guardrails) |
| F. Infrastructure | 8 | Build + Buy (telephony, hosting, possibly managed STT/TTS, simulator) |
| G. Monitoring | 5 | Build (dashboard, review UI, alerting) |
| **Total** | **43** | |

### What you buy vs build

**Buy / subscribe:**
- Telephony provider with HIPAA BAA (Twilio HIPAA, Telnyx HIPAA)
- Cloud hosting with BAA (AWS / Azure / GCP)
- Possibly managed STT (AWS Transcribe, Google Speech) with BAA
- Possibly managed TTS (if self-hosted quality is insufficient)
- Possibly managed LLM API (Claude / GPT) with BAA

**Build:**
- Everything else. The IVR navigation, hold handling, script engine,
  entity extraction, read-back, escalation, work queue, disposition
  logging, review UI, payor profiles, and the glue that connects all of
  it — that's the product.

---

## I. What You Can Skip for Tier 1

Features from `RCM_VOICE_AGENTS.md` that are NOT needed for Tier 1:

- Multi-claim batching (Tier 3)
- Fax triggering integration (Tier 2 — 1C just collects the fax number)
- Billing system write-back (v1 is shadow mode — human enters dispositions)
- Clearinghouse pre-check (optimization, not required)
- Payment posting / adjustment knowledge (Tier 2)
- Denial argumentation / appeal logic (Tier 3)
- Patient-facing calls (Tier 3)
- Clinical content guardrails beyond "don't go there" (Tier 1 conversations
  don't involve clinical content)
- Warm transfer to human (nice-to-have for v1; polite close + reschedule
  is acceptable initially)
- Sophisticated AEC (headset/speakerphone mode — Tier 1 is agent-to-payor
  over PSTN, AEC is handled at the telephony layer)

---

## J. Suggested Build Order for Tier 1

**Note:** This section is the original build order. See
`docs/PROJECT_REVIEW_AND_PLAN.md` for the revised phased plan that
incorporates lessons from the project review (Twilio provisioning as
long-pole, brain model commitment, call simulator, real-world data
collection). The revised plan supersedes this section where they differ.

### Phase 0 — Foundation (before building features)

0. **Start Twilio HIPAA provisioning + BAA.** Long-pole dependency. In
   parallel, get a standard Twilio dev account for non-PHI testing.
1. **Commit brain model.** Claude API (Anthropic) for v1. Begin BAA.
2. **Record 5–10 real claim status calls.** Human biller, highest-volume
   payor. Transcribe and annotate IVR/hold/human/entity segments.
3. **DB schema + migrations.** Postgres, Alembic.
4. **Core tests.** PHI whitelist, queue transitions, disposition validation.
5. **Structured logging + metrics scaffolding.**
6. **Revise protocol signatures.** Telephony (add audio streaming, recording),
   STT (async streaming), Brain (PHI accessor + script state coupling).
   Add HoldHandler + TransferDetector abstractions.

### Phase 1 — Tier 1A vertical slice

1. **Call simulator.** Fake Twilio Media Streams endpoint. Replay recorded
   IVR, hold, and rep dialogue. All development iterates here first.

2. **Telephony hello-world.** Place an outbound call via Twilio, play a
   canned "hello" TTS message, record the call, hang up. Proves the
   telephony adapter works.

3. **Audio pipeline.** Bidirectional audio: send TTS to the call, receive
   audio from the call, transcribe it via STT. No brain yet — just echo
   back a transcript of what the counterparty said.

4. **IVR navigator for one payor.** Build from annotated call recordings.
   Test against the simulator. Then validate against the live payor IVR.
   This is the hardest single feature.

5. **Hold handler.** Detect hold, wait patiently, detect human pickup.
   Test against simulator first, then live.

6. **Claim status script + brain.** Wire Claude API with the 1A script,
   PHI accessor, and conversation history. Test against simulated rep
   dialogue, then run a live call in shadow mode.

7. **Entity extraction + disposition logging.** Extract structured data
   from the conversation, write the disposition record.

8. **Dashboard + review UI.** Minimal web UI to monitor calls and review
   transcripts.

9. **Shadow mode on 3 payors.** Run claim status calls for your top 3
   payors in shadow mode for 2 weeks. Human reviews every disposition.
   Track accuracy, escalation rate, IVR success rate.

10. **Expand to 1B/1C/1D.** Add eligibility, fax lookup, auth status
    scripts. These reuse 90% of the infrastructure — mostly new scripts
    and entity schemas.

11. **Promote to production.** Enable billing system write-back for
    high-confidence dispositions. Human review drops to 10–20% sample.
