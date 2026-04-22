# Getting Started

## Prerequisites

- Python 3.13+ (managed via pyenv)
- Postgres (for production; tests use SQLite in-memory)
- cloudflared (`brew install cloudflared`) — for live call testing
- Twilio account with a phone number
- Gemini API key

## Environment Setup

1. Clone the repo and set Python version:
   ```bash
   cd voice-agent
   pyenv local 3.13.11
   ```

2. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

3. Create `.env` file (or use `~/Github/.env`):
   ```bash
   cp .env.example .env
   # Edit with your credentials:
   # TWILIO_ACCOUNT_SID=ACxxxxxxxx
   # TWILIO_AUTH_TOKEN=xxxxxxxx
   # TWILIO_FROM_NUMBER=+1xxxxxxxxxx
   # GEMINI_API_KEY=xxxxxxxx
   ```

4. Verify Twilio numbers:
   - Your Twilio FROM number is in the env
   - Any TO numbers must be **verified** in Twilio Console →
     Phone Numbers → Verified Caller IDs (trial account restriction)

## Running Tests

```bash
# All unit tests (fast, ~1.5s)
PYTHONPATH=src python3 -m pytest tests/ --timeout=60 --ignore=tests/test_e2e.py -v

# E2E tests against simulator (~3 min, loads Silero VAD)
PYTHONPATH=src python3 -m pytest tests/test_e2e.py -v --timeout=60

# Full suite
PYTHONPATH=src python3 -m pytest tests/ -v --timeout=60
```

## Placing a Live Test Call

1. Make sure the destination number is **verified** in Twilio (trial restriction)

2. Run the live call script:
   ```bash
   PYTHONPATH=src python3 scripts/live_call.py --to +1XXXXXXXXXX --port 8001
   ```

3. What happens:
   - cloudflared tunnel starts (gives a public HTTPS URL)
   - FastAPI webhook server starts on localhost:8001
   - Twilio places the call, pointing webhooks at the tunnel URL
   - When answered: Twilio trial message plays (~10s), then agent speaks
   - Agent introduces itself as "Riverside Medical billing"
   - Conversation loops: Twilio STT → Gemini brain → Twilio TTS

4. After the call ends, you'll see:
   - Full transcript (REP and AGENT turns)
   - Extracted entities with confidence scores
   - PHI fields that were disclosed

5. Share `docs/TEST_PERSONA.md` with whoever is receiving the call so they
   know what to say.

## Running the Call Simulator

The simulator replays scripted call scenarios over WebSocket without
using Twilio. Useful for development iteration.

```bash
# List available scenarios
python3 -m simulator.server --list

# Run a scenario (starts WebSocket server on port 8765)
python3 -m simulator.server --scenario happy_path

# Run E2E: simulator + session runner
PYTHONPATH=src python3 scripts/run_simulator_e2e.py --scenario happy_path

# With Gemini brain (makes real API calls)
PYTHONPATH=src python3 scripts/run_simulator_e2e.py --with-brain

# With Granite STT (requires model weights in ~/Github/models/)
PYTHONPATH=src python3 scripts/run_simulator_e2e.py --with-stt
```

## Database Setup

Only needed for disposition persistence (not required for live calls yet):

```bash
# Create Postgres database
bash scripts/db_setup.sh

# Or manually:
createdb voice_agent
PYTHONPATH=src alembic upgrade head
```

## Key Files to Understand

| File | What it does |
|---|---|
| `scripts/live_call.py` | Places a real phone call with Gemini brain |
| `src/voice_agent/runner.py` | SessionRunner — orchestrates the full call flow |
| `src/voice_agent/session.py` | Session state machine (8 states) |
| `src/voice_agent/brain/gemini.py` | Gemini brain with system prompt assembly |
| `src/voice_agent/extraction/patterns.py` | Pattern-based entity extraction |
| `src/voice_agent/ivr/__init__.py` | IVR navigator (rule engine) |
| `src/voice_agent/compliance/phi.py` | PHI whitelist enforcement |
| `simulator/server.py` | Call simulator (Twilio protocol) |
| `docs/TEST_PERSONA.md` | Instructions for test call recipients |

## Common Issues

**"The number +1XXX is unverified"** — Twilio trial accounts can only call
verified numbers. Go to Twilio Console → Phone Numbers → Verified Caller IDs
→ add the number.

**Call connects but agent doesn't speak** — The person hung up during the
Twilio trial message (~10 seconds). Tell them to stay on the line.

**Port already in use** — Kill old processes:
```bash
lsof -ti:8001 | xargs kill -9
kill $(pgrep -f cloudflared)
```

**ngrok interstitial page** — Don't use ngrok free tier. Use cloudflared
instead (already configured in `live_call.py`).
