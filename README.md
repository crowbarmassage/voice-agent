# Voice Agent — RCM Outbound Calling Platform

Production voice agents for healthcare revenue cycle management. Agents make
outbound calls to payors, SNFs, hospices, and HHAs to handle routine billing
tasks — claim status checks, eligibility verification, auth status, documentation
requests — so billers can focus on higher-value work.

## Status

Early development. Building Tier 1 (lowest-intensity use cases) first.

## Design docs

- [docs/RCM_VOICE_AGENTS.md](docs/RCM_VOICE_AGENTS.md) — Master requirements, use case tiers, build sequence
- [docs/TIER1_FEATURES.md](docs/TIER1_FEATURES.md) — 42-feature breakdown for Tier 1, build order
- [docs/STT_FEATURES.md](docs/STT_FEATURES.md) — STT backend comparison and swappable architecture

## Setup

```bash
cd ~/Github/voice-agent
uv venv --python 3.12
uv pip install -e ".[dev]"
```

## Project structure

See [CLAUDE.md](CLAUDE.md) for full architecture overview and conventions.
