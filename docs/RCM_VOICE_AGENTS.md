# RCM Voice Agents — Feature Requirements & Use Cases

Production voice agents for revenue cycle management outbound calling. Agents
call counterparties (payors, SNFs, hospices, HHAs, provider offices, patients)
on behalf of the RCM team to resolve claims, chase documentation, check
statuses, and handle routine phone work that currently burns hours of human hold
time.

---

## Part 1: Production Feature Requirements

Organized by layer, from "must have on day one" to "differentiating at scale."

### 1.1 Telephony & Call Infrastructure

- **PSTN/SIP origination.** Agent places real outbound phone calls. Twilio,
  Vonage, Bandwidth, or Telnyx as the carrier layer. SIP trunking for
  volume/cost optimization later.
- **Caller ID management.** Display a real, callback-capable number tied to the
  billing office. Spoofed/unrecognizable numbers get ignored or blocked by
  payor phone systems. Must comply with STIR/SHAKEN attestation.
- **IVR navigation.** Payors front-end every call with a phone tree (press 1
  for claims, press 3 for provider services, enter your NPI, etc.). The agent
  must detect DTMF prompts, speech prompts, and menu structures, then navigate
  them autonomously. This is non-trivial — trees change without notice, some
  require speech input, some loop. Needs a fallback: "I couldn't navigate the
  menu, escalating to a human."
- **Hold detection and patience.** Payor hold times regularly exceed 30–60
  minutes. The agent must detect hold music / periodic "your call is important"
  messages, stay on the line silently, and re-engage instantly when a human
  picks up. Timeout policy configurable per-payor (e.g., hang up after 90 min
  on UHC, retry tomorrow).
- **Multi-line concurrency.** The value proposition is parallelism — 50 calls
  on hold simultaneously while humans do higher-value work. Architecture must
  support N concurrent sessions without degradation. Each session holds its own
  conversation state, call context, and PHI scope.
- **Call recording.** Every call recorded (WAV or compressed), stored encrypted,
  retention policy per state/federal regs. Recording consent: most payor lines
  already announce recording; confirm agent discloses if required by state
  two-party consent laws.
- **Voicemail detection.** Detect answering machines / voicemail greetings.
  Policy: leave a message (with approved script, no PHI in voicemail) or hang
  up and retry.

### 1.2 Speech Pipeline (STT + TTS)

- **Low-latency STT.** The counterparty (a human at the payor, SNF, etc.) is
  talking. Agent must transcribe in near-real-time to feed the brain. Latency
  budget: <500ms from end-of-utterance to brain seeing the transcript. Granite
  or Whisper, per `STT_FEATURES.md`.
- **Barge-in / interruption handling.** The counterparty may interrupt the
  agent mid-sentence (common in fast-paced payor calls). Agent must detect
  incoming speech, stop talking, listen, and respond. AEC is mandatory —
  the agent's own TTS output must not be mistaken for the counterparty's
  speech.
- **Natural, professional TTS.** The agent sounds like a calm, competent
  billing office employee. Not robotic, not overly cheerful. Consistent voice
  across the entire call. Must handle:
    - Medical terminology (ICD-10 codes read aloud, procedure names, drug
      names)
    - Alphanumeric strings (claim numbers, NPI, tax ID, member ID) — spelled
      out clearly, with confirmation pauses
    - Phone numbers, dates, dollar amounts — spoken in standard US convention
- **Silence and pacing.** Agent must tolerate natural pauses (the rep is
  looking something up). Don't re-prompt too quickly. Configurable silence
  timeout before "are you still there?" (recommend 8–12 seconds for payor
  reps actively working a claim).
- **Noise robustness.** Call center backgrounds, hold music bleed-through,
  compression artifacts on PSTN audio (8kHz G.711). STT must be trained on
  or fine-tuned for telephone-quality audio, not clean studio conditions.

### 1.3 Conversation Intelligence (Brain)

- **Structured call scripts with dynamic branching.** Each use case has a
  script: identify yourself, state the purpose, provide claim details, ask
  the target question, handle responses. But calls are never linear — the
  rep asks for info in a different order, transfers you, gives a partial
  answer. The brain must hold the script as a goal tree, not a fixed
  sequence, and adapt.
- **Claim context injection.** Before each call, the agent is loaded with
  structured data: patient name, DOB, member ID, claim number, date of
  service, billed amount, denial code (if applicable), what we're asking
  for. This context comes from the billing system and is injected into the
  brain's working memory.
- **Entity extraction in real-time.** As the counterparty speaks, the brain
  extracts structured data from the conversation: reference numbers, appeal
  deadlines, fax numbers, names of reps, denial reason codes, promised
  actions. These get written to a structured call disposition record, not
  just a raw transcript.
- **Verification and read-back.** For any critical piece of info (reference
  number, deadline, fax number), the agent reads it back: "Just to confirm,
  the appeal deadline is June 15th and I should fax the records to
  555-0123?" This catches STT errors before they propagate.
- **Escalation triggers.** The agent must recognize when it's out of its
  depth and hand off to a human:
    - Counterparty asks a question outside the script
    - Counterparty becomes hostile or uncooperative
    - Call is transferred to an unexpected department
    - Agent has low confidence in what it heard (STT confidence score)
    - Compliance-sensitive situation (e.g., counterparty asks agent to
      confirm a diagnosis)
  Escalation = warm transfer to a human with full transcript + context,
  not a dropped call.
- **Multi-turn memory within a call.** "Like I said earlier, the date of
  service was March 3rd" — the agent must not re-ask info already
  established. Full call history stays in context.
- **Multi-claim handling.** Experienced billers batch: "While I have you, I
  also need to check on claims ending in 4472 and 8891." The agent should
  support this when the queue has multiple claims for the same payor, to
  amortize hold time.

### 1.4 Integrations

- **Billing system / PM system.** Read claim data, patient demographics,
  denial details before the call. Write back call dispositions, next actions,
  reference numbers after the call. Common targets: Epic (Resolute), Cerner
  Revenue Cycle, Waystar, Availity, Athena, AdvancedMD, Kareo. API or
  RPA depending on system.
- **Clearinghouse integration.** Pull real-time claim status (EDI 276/277)
  before calling — no point calling about a claim that just paid. Availity,
  Change Healthcare, Trizetto.
- **Fax integration.** Many documentation requests end with "fax it to
  this number." Agent should be able to trigger an outbound fax of the
  relevant documents from the document management system. Fax API: Phaxio,
  SRFax, or EHR-native fax.
- **Task/workflow queue.** Calls originate from a work queue (e.g., "all
  denials >30 days with no appeal filed"). Agent pulls the next item, makes
  the call, logs the result, and advances the item's workflow state.
  Integrates with whatever workflow the RCM team uses — could be Epic
  Work Queue, a custom tool, or a spreadsheet-to-API bridge for v1.
- **Scheduling / callback.** If the agent can't resolve on the first call
  ("call back after 3pm when the supervisor is available"), it schedules
  a retry in the queue with the callback context preserved.

### 1.5 Compliance & Security

- **HIPAA.** This is a covered entity (or BA) handling PHI over the phone.
    - **Minimum necessary.** Agent only discloses the PHI needed for the call
      purpose. Don't volunteer diagnosis codes if the call is about a billing
      address.
    - **Verification before disclosure.** When the counterparty asks for PHI
      (to look up the claim), the agent provides it. When an *unexpected*
      party asks (wrong transfer, random person), the agent declines and
      escalates.
    - **BAA chain.** Every vendor in the stack (telephony provider, cloud
      infra, STT/TTS if cloud-hosted, call recording storage) must have a
      signed BAA. This is non-negotiable and the single biggest constraint
      on vendor selection.
    - **Encryption.** Audio in transit (SRTP), at rest (AES-256), transcripts
      at rest. PHI never in plaintext logs.
    - **Access controls.** Call recordings and transcripts accessible only to
      authorized RCM staff. Role-based access. Audit trail on every access.
    - **Retention and destruction.** Call recordings retained per policy
      (typically 6–10 years for billing records), then securely destroyed.
    - **Breach notification.** If a call inadvertently discloses PHI to the
      wrong party, that's a potential breach. Incident detection and
      reporting workflow must exist.
- **State telecom regulations.** Two-party consent states (CA, FL, IL, etc.)
  require all parties to consent to recording. Payor IVRs usually cover
  their end; agent must disclose its own recording at call start if required.
  Some states require disclosure that the caller is an AI — emerging
  legislation, track actively.
- **AI disclosure.** Several states and the FTC are moving toward requiring
  AI callers to identify themselves as non-human. Build this in from day one:
  "This is [Name] calling from [Practice] billing office. I'm an automated
  assistant calling on behalf of [Biller Name]." Transparent, professional,
  not deceptive. Some counterparties will refuse to engage — that's an
  escalation-to-human trigger.
- **No medical advice, no clinical decisions.** Agent is strictly
  administrative. It never interprets clinical information, never advises on
  treatment, never makes coverage determinations. If the conversation drifts
  clinical, escalate.
- **Audit logging.** Every call: timestamp, counterparty, purpose, duration,
  full transcript, extracted entities, disposition, escalation events, PHI
  accessed. Immutable log. This is your compliance safety net and your QA
  data source.

### 1.6 Quality Assurance & Monitoring

- **Call disposition dashboard.** Real-time view: calls in progress, on hold,
  completed, escalated, failed. Per-payor success rates. Average handle time.
  Average hold time. Claims resolved per hour.
- **Transcript review queue.** Random sample of calls flagged for human QA
  review. Escalated calls always reviewed. Scored on: accuracy of info
  extracted, appropriateness of responses, compliance adherence, tone.
- **Confidence scoring.** Each extracted entity (reference number, deadline,
  fax number) gets a confidence score from the STT + brain pipeline. Low-
  confidence extractions are flagged for human verification before being
  written to the billing system.
- **Regression detection.** Track success rate per use case per payor over
  time. If UHC denial calls suddenly drop from 80% resolved to 40%, that
  probably means UHC changed their IVR or their phone reps got a new script.
  Alert, investigate, retrain.
- **Cost tracking.** Per-call cost (telephony minutes + compute). Compare
  to human cost per call. This is how you justify the project.

### 1.7 Reliability & Operations

- **Graceful degradation.** If STT fails mid-call, don't go silent — say
  "I'm sorry, I'm having trouble hearing you, let me transfer you to a
  colleague." If the brain hangs, same. Never leave a counterparty in
  silence wondering what happened.
- **Retry with backoff.** Busy signals, no answers, IVR failures — retry
  with configurable backoff (e.g., 30 min, 2 hr, next business day).
  Max retry count per claim per time window.
- **Business hours awareness.** Don't call at 2am. Respect payor and
  facility business hours (which vary — Medicare contractors vs. commercial
  payors vs. SNFs). Time zone aware.
- **Rate limiting.** Don't hit the same payor number with 50 simultaneous
  calls. They'll block you. Configurable concurrency cap per destination
  number.
- **Disaster recovery.** If the system goes down mid-call-batch, resume
  from the queue without re-calling claims already resolved. Idempotent
  call execution.

---

## Part 2: Use Cases — Low to High Intensity/Downside

Ranked by: what goes wrong if the agent makes a mistake, how adversarial
the conversation is, and how much domain expertise is required.

### Tier 1 — Low intensity, low downside

Mistakes are recoverable, calls are formulaic, counterparties are neutral.
**Start here.**

#### 1A. Claim status inquiry
- **What:** Call payor, navigate IVR to claims, provide claim number, ask
  "what is the status of this claim?"
- **Counterparty:** Payor automated system or front-line rep
- **Script complexity:** Linear. Identify → provide claim # → record status.
- **Downside of error:** Low. Wrong status just means you check again later.
  No financial harm from asking.
- **Why start here:** Most calls are this. Massive volume, pure drudgery,
  agents mostly just sit on hold. Zero clinical content. Perfect
  proof-of-concept.
- **Success metric:** % of status checks completed without human
  intervention.

#### 1B. Eligibility / benefits verification
- **What:** Call payor, verify patient is active, confirm plan details,
  copay/coinsurance, deductible remaining.
- **Counterparty:** Payor benefits line (often separate from claims)
- **Script complexity:** Low-medium. May need to provide DOB, member ID,
  subscriber info.
- **Downside of error:** Low-medium. Wrong eligibility info could lead to
  billing a wrong payor, but this is caught downstream at claim submission.
- **Why it's Tier 1:** Routine, high-volume, low-stakes per call. Most of
  this should be done via EDI 270/271 first — the voice agent handles the
  cases where electronic eligibility is stale or missing.

#### 1C. Request fax number / mailing address
- **What:** Call a facility (SNF, hospice, HHA, provider office) and ask
  where to send a records request or where to fax documentation.
- **Counterparty:** Front desk / medical records dept
- **Script complexity:** Minimal. "Hi, I'm calling from [Practice]. What
  fax number should I use to send a medical records request?"
- **Downside of error:** Very low. Wrong fax number = failed fax, retry.
- **Why it's Tier 1:** Nearly zero PHI in the conversation. Pure logistics.

#### 1D. Authorization status check
- **What:** Call payor to check if a prior authorization is approved,
  pending, or denied. Provide auth number or claim details.
- **Counterparty:** Payor auth/utilization management line
- **Script complexity:** Low-medium. Similar to claim status but different
  IVR path and sometimes different department.
- **Downside of error:** Low. Status check is read-only.

### Tier 2 — Medium intensity, medium downside

Calls require more back-and-forth, some judgment, and the agent handles
PHI or action-triggering information. Mistakes have operational cost.

#### 2A. Documentation request to SNF / hospice / HHA
- **What:** Call the facility's medical records department. Request specific
  documents: face-to-face encounter notes, plan of care, physician orders,
  discharge summary, nursing notes for specific date range.
- **Counterparty:** Medical records clerk, sometimes a nurse
- **Script complexity:** Medium. Must specify exactly which documents, for
  which patient, which dates. May need to provide the request via fax
  after the call. The clerk may say "we already sent that" or "we need a
  signed authorization" — agent must handle these branches.
- **Downside of error:** Medium. Wrong documents requested = wasted time.
  Missing documents = appeal deadline missed. But recoverable with a
  follow-up call.
- **Why it's Tier 2:** Real PHI exchange (patient name, DOB, dates of
  service, sometimes diagnosis). Multi-turn negotiation ("we need an
  authorization form first" → "I'll fax one over, can you give me the
  fax number?"). The agent needs to be adaptive, not just script-reading.

#### 2B. Denial reason inquiry
- **What:** Call payor about a denied claim. Get the specific denial reason
  (CARC/RARC codes or plain-language), appeal deadline, appeal submission
  method (fax, portal, mail), and what additional documentation is needed.
- **Counterparty:** Payor claims rep
- **Script complexity:** Medium-high. The rep may give partial info, may
  need to transfer to a different department, may quote policy language
  the agent needs to capture verbatim. May involve multiple denial reasons
  on the same claim.
- **Downside of error:** Medium. Missing the appeal deadline = lost revenue
  (could be thousands). Misunderstanding the denial reason = filing a
  wrong appeal = more wasted time. But the call itself doesn't cause harm;
  the risk is in acting on bad info downstream.
- **Success metric:** % of denial calls that return a complete, accurate
  disposition (reason + deadline + method + docs needed).

#### 2C. Payment posting discrepancy follow-up
- **What:** Call payor about a payment that doesn't match the expected
  amount. "We billed $X, you paid $Y, the EOB says [reason]. Can you
  explain the adjustment?"
- **Counterparty:** Payor payment/adjustment dept
- **Script complexity:** Medium. Requires understanding of adjustment reason
  codes, contractual vs. non-contractual adjustments, patient responsibility
  calculations. The rep may say "that's correct per your contract" — agent
  needs to know whether to accept that or push back.
- **Downside of error:** Medium. Accepting a wrong underpayment = lost
  revenue. Disputing a correct payment = wasted effort + possible
  relationship damage with payor.

#### 2D. Timely filing dispute
- **What:** Claim denied for timely filing (too late). Call payor with proof
  of timely submission (original claim date, acknowledgment, etc.) to
  request override.
- **Counterparty:** Payor claims/appeals rep
- **Script complexity:** Medium. Need to reference specific dates, provide
  evidence, potentially request a supervisor.
- **Downside of error:** Medium-high. Failed dispute = written-off claim.
  But the claim was already denied, so downside is limited to the lost
  recovery opportunity.

### Tier 3 — High intensity, high downside

Adversarial or complex conversations. Real money at stake. Clinical content
may surface. Mistakes have financial or compliance consequences.

#### 3A. Formal appeal call / reconsideration request
- **What:** Call payor to initiate or discuss a formal appeal of a denied
  claim. May involve reading appeal language, citing policy or regulation,
  referencing clinical documentation.
- **Counterparty:** Payor appeals dept, sometimes a clinician reviewer
- **Script complexity:** High. Adversarial by nature — the payor denied it
  and the agent is arguing it should be paid. The rep may cite contract
  terms, medical necessity criteria, or policy exclusions. Agent needs
  to respond with specific counter-arguments from the appeal template.
- **Downside of error:** High. Bad appeal = final denial = revenue lost
  permanently (some payors only allow one appeal level). Saying the wrong
  thing ("we acknowledge this wasn't medically necessary") could waive
  rights. Compliance risk if agent oversteps into clinical argumentation.
- **When to deploy here:** Only after Tier 1–2 agents are battle-tested.
  Start with simple reconsiderations (e.g., "this was denied for timely
  filing but here's proof we filed on time") before moving to medical
  necessity appeals.

#### 3B. Peer-to-peer review scheduling
- **What:** Call payor to schedule a peer-to-peer review — where the
  ordering physician discusses medical necessity with the payor's medical
  director.
- **Counterparty:** Payor utilization management, sometimes clinical staff
- **Script complexity:** High. The agent is scheduling on behalf of a
  physician, needs to coordinate availability, may need to provide clinical
  context to justify why the P2P is warranted.
- **Downside of error:** High. Missed or botched P2P = service not
  authorized. Wrong clinical information conveyed = compliance risk.
  But note: the agent is scheduling, not conducting, the P2P — the
  actual clinical conversation happens between physicians.

#### 3C. Complex multi-claim resolution
- **What:** Call a payor with a batch of related claims (same patient,
  same episode of care, or same denial pattern) and resolve them in one
  call.
- **Counterparty:** Payor claims rep, possibly a supervisor
- **Script complexity:** Very high. Juggling multiple claims, different
  statuses, different issues. The conversation branches unpredictably.
  Rep may resolve 3 of 5 and say "the other two need to go to a different
  department."
- **Downside of error:** Compounded — errors on multiple claims in one
  call. But the upside is also compounded — one call resolves what would
  have been five.
- **When to deploy:** Only after single-claim calls are reliable.

#### 3D. Patient balance calls (collections-adjacent)
- **What:** Call patient to discuss outstanding balance, explain charges,
  offer payment plan or financial assistance screening.
- **Counterparty:** The patient (or their family)
- **Script complexity:** Medium, but emotionally complex. Patients are
  often confused, stressed, or upset about medical bills.
- **Downside of error:** High — but reputational/regulatory, not just
  financial. Aggressive or confusing calls → patient complaints, bad
  reviews, potential FDCPA issues if the balance is in collections.
  AI disclosure is most sensitive here — patients may feel deceived if
  they don't know they're talking to a bot.
- **Why it's Tier 3:** Not because the script is hard, but because the
  human dynamics are. Getting tone wrong here has outsized consequences.
  This is the use case most likely to attract regulatory scrutiny.

#### 3E. Credentialing / enrollment follow-up
- **What:** Call payor credentialing dept to check on provider enrollment
  application status, provide missing documents, resolve enrollment holds.
- **Counterparty:** Payor credentialing staff
- **Script complexity:** Medium. But credentialing errors (wrong NPI linked,
  wrong taxonomy, wrong effective date) can cause months of claims to deny.
- **Downside of error:** Very high per-error — a wrong effective date can
  mean every claim for that provider in that period must be resubmitted.
  But call frequency is low and the conversations are relatively structured.

---

## Part 3: Recommended Build Sequence

Phase 1 — **Proof of concept (Tier 1A: claim status)**
- Build the telephony + STT + brain + TTS pipeline end to end on one use
  case. Prove the IVR navigation works for 2–3 major payors (UHC, BCBS,
  Aetna). Prove hold tolerance works. Prove entity extraction is accurate.
- Run in shadow mode first: agent makes the call, human listens and
  verifies, disposition is logged but not written to billing system.

Phase 2 — **Expand Tier 1 + start Tier 2A**
- Add eligibility checks, auth status, fax/address lookups. These share
  80% of the infrastructure with claim status — the IVR navigation,
  hold handling, and call lifecycle are identical; only the script and
  entities change.
- Start documentation request calls to SNFs/hospices. This is the first
  use case where the agent talks to a human who talks back (not just a
  payor IVR → hold → brief exchange).

Phase 3 — **Tier 2 denial management**
- Denial reason inquiry, timely filing disputes, payment discrepancy
  follow-up. This is where the financial ROI gets real — denied claims
  are the highest-value work in RCM, and human billers spend most of
  their phone time on payor hold.

Phase 4 — **Tier 3, selectively**
- Appeal calls and P2P scheduling only after the agent has a track record
  of reliability in lower tiers. Patient balance calls only after legal
  review of AI disclosure requirements in your operating states.

---

## Part 4: Key Open Questions

1. **Cloud vs. on-prem.** The local Apple Silicon stack is great for R&D
   but production telephony at scale (50+ concurrent calls) likely needs
   cloud GPUs. Every cloud vendor in the stack needs a BAA. Evaluate:
   Azure (HIPAA-ready, Whisper API available), AWS (Bedrock, Transcribe
   Medical), GCP (Vertex, Speech-to-Text Medical). Or: self-hosted on
   dedicated GPU instances with your own BAA.

2. **Build vs. buy.** Companies doing exactly this today: Thoughtful AI,
   Infinitus Health, Olive AI (defunct but the space is active), Akasa,
   Notable Health. Evaluate whether the right move is building from scratch
   vs. licensing/white-labeling an existing RCM voice agent platform and
   customizing it.

3. **Payor IVR mapping.** Each major payor's phone tree is different and
   changes periodically. Maintaining a library of IVR navigation maps
   for the top 20 payors is ongoing operational work, not a one-time build.
   Consider whether this is crowdsourced across customers or maintained
   internally.

4. **Which brain for production?** Gemma-4 26B is great locally but may not
   be the right choice for production telephony where you need sub-second
   response latency under concurrency. Smaller models fine-tuned on RCM
   call scripts, or a Claude/GPT API call with a well-crafted system prompt,
   may outperform a large open model on this narrow task. This is a
   latency/quality/cost tradeoff to benchmark.

5. **Regulatory trajectory.** FTC, FCC, and several states are actively
   legislating AI calling. What's legal today may require modifications in
   6–12 months. Build AI disclosure in from the start and track legislation
   actively.
