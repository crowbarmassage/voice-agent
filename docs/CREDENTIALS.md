# Credentials & Accounts

## Where Credentials Live

All credentials are in `~/Github/.env` (NOT in the repo). The `.env` file
is gitignored. Copy `.env.example` as a starting point.

## Accounts

### Twilio (Telephony)
- **Account type:** Trial (free tier)
- **Console:** https://console.twilio.com
- **Phone number:** +1-414-350-7739 (this is both the Twilio FROM number
  and the owner's personal cell)
- **Trial restriction:** Can only call **verified** numbers. Verify new
  numbers at Console → Phone Numbers → Verified Caller IDs.
- **Trial message:** Every call starts with a ~10 second "You have a trial
  account..." message before the agent speaks. Upgrading ($20 credit)
  removes this.
- **Env vars:** `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`

### Gemini (Brain LLM)
- **Model:** `gemini-3.1-flash-lite-preview`
- **Console:** https://aistudio.google.com
- **Env var:** `GEMINI_API_KEY`

### Verified Phone Numbers for Testing
- +1-414-350-7739 (owner's cell / Twilio number — don't use as TO, same as FROM)
- +1-847-323-9223 (verified)
- +1-773-354-3139 (verified)
- +1-224-402-8455 (verified)

## For Production (Not Yet Set Up)

- **Twilio HIPAA:** Requires upgrade to HIPAA-eligible product + BAA signing.
  Contact Twilio sales.
- **Cloud hosting:** AWS/Azure/GCP with BAA for HIPAA.
- **Postgres:** Production database (dev uses SQLite in-memory for tests).
- **Anthropic (optional):** Claude API as alternative brain. BAA available.

## Local Model Weights

These are NOT credentials but are needed for local STT:

- **Granite 4.0 1B Speech:** `~/Github/models/granite-4.0-1b-speech/`
  (3 safetensors shards + tokenizer)
- **Gemma-4 26B:** `~/Github/models/gemma-4/` (for future local brain)
- **OmniVoice:** Available via `k2-fsa/OmniVoice` (for future local TTS)

## Adding a New Test Number

1. Go to Twilio Console → Phone Numbers → Verified Caller IDs
2. Click "Add a new Caller ID"
3. Enter the phone number
4. Twilio calls it with a verification code
5. Now you can call that number from the live call script
