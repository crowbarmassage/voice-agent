# Code Conventions

## Architecture Patterns

- **Protocol-based backends.** STT, TTS, Brain, and Telephony all use
  `typing.Protocol`. Adding a new backend = adding a new file, not
  refactoring. Example: `brain/gemini.py` implements `BrainBackend`.

- **One session per call.** The `Session` class holds all state for a single
  call. `SessionRunner` orchestrates it. Never share session state between
  calls.

- **PHI goes through the accessor.** Never access claim context fields
  directly. Always use `PHIAccessor.get(field)` which enforces the
  minimum-necessary whitelist and logs access for audit.

- **Events for everything.** All significant call events are emitted as
  `CallEvent` objects (see `events.py`). The session accumulates them.
  They feed into audit logs and disposition records.

## File Organization

- `src/voice_agent/` — production code
- `tests/` — mirrors `src/` structure. Each source module has a test file.
- `scripts/` — operational scripts (live call, simulator E2E, DB setup)
- `simulator/` — call simulator (speaks Twilio Media Streams protocol)
- `config/payors/` — per-payor YAML profiles
- `docs/` — requirements, architecture, plans
- `alembic/` — database migrations

## Code Style

- Python 3.13, `from __future__ import annotations` everywhere
- Type hints on all function signatures
- `ruff` for linting (config in `pyproject.toml`, line length 99)
- `pytest` + `pytest-asyncio` for tests
- Structured logging via `structlog` (use `get_logger(__name__)`)
- Pydantic for data models, SQLAlchemy for DB tables

## Testing

- Tests use SQLite in-memory (no Postgres needed)
- Twilio tests are mocked (no real API calls)
- E2E tests start the simulator in-process
- Brain tests validate prompt construction, not API calls
- Run unit tests: `PYTHONPATH=src python3 -m pytest tests/ --ignore=tests/test_e2e.py`
- Run everything: `PYTHONPATH=src python3 -m pytest tests/ --timeout=60`

## Naming

- Session states: `pre_call`, `dialing`, `ivr`, `hold`, `conversation`, `post_call`, `done`, `failed`
- Work item statuses: `pending`, `in_progress`, `completed`, `failed`, `retry_scheduled`, `human_required`
- Entity sources: `"pattern"` (regex) or `"llm"` (Gemini)
- Date labels: `date`, `received_date`, `expected_date`, `payment_date`, `effective_date`, `term_date`

## Adding a New Use Case (e.g., Tier 1B Eligibility)

1. Create the script: `src/voice_agent/scripts/eligibility.py`
   - Define `create_eligibility_script()` returning a `CallScript` with goals
2. Add PHI whitelist entry in `compliance/phi.py` → `PERMITTED_PHI`
3. Add entity extraction patterns if needed in `extraction/patterns.py`
4. Add a simulator scenario in `simulator/scenarios.py`
5. Write tests mirroring the claim status tests
6. Update the live call script to accept `--use-case eligibility`

## Adding a New Brain Backend

1. Create `src/voice_agent/brain/new_backend.py`
2. Implement `respond()` (streaming) and `analyze_response()` (structured)
3. Accept `BrainContext` — build your own system prompt from it
4. Never access PHI directly — only through `context.phi.get(field)`
5. Add unit tests for prompt construction

## Adding a New Payor

1. Copy `config/payors/_template.yaml` to `config/payors/<name>.yaml`
2. Fill in: phone numbers, IVR rules, business hours, hold timeout, quirks
3. The IVR rules are pattern-match rules: `prompt_contains` → `action` + `value`
4. Context variables like `{npi}` and `{tax_id}` are substituted from claim context
