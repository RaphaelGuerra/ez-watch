# AGENTS.md

## Purpose
This repository runs an **EZ-WATCH CV alert relay** for resort-sensitive zones.
The goal is to ingest CV events, apply zone policy, suppress duplicates/noise, and dispatch alerts.

Use this file as the first-read guide before changing code.

## Source of Truth
- Primary runtime (production): Cloudflare Worker + Durable Object
- Worker entrypoint: `cloudflare/worker/src/index.ts`
- Worker config: `wrangler.toml`
- Secondary runtime (legacy fallback/reference): FastAPI app in `app/`

If behavior differs, treat the Worker path as canonical unless a task explicitly targets legacy FastAPI rollback.

## Core Flows
1. CV event ingestion: `POST /v1/events/cv`
2. Zone + camera mapping validation
3. Active schedule validation (timezone-aware)
4. Dedupe + suppression window checks
5. Alert dispatch (Pushover in Worker, WhatsApp/Email in FastAPI)
6. Metrics emission for received/suppressed/sent

## API Surface
- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`
- `GET /v1/zones`
- `POST /v1/events/cv`
- `POST /v1/health/camera-ping`

## Important Config
- Worker vars/secrets: `wrangler.toml` + `wrangler secret put ...`
- Zone config (Worker): `ZONE_CONFIG_JSON` (in `wrangler.toml`)
- Zone config (FastAPI): `configs/zones.yaml`
- FastAPI env template: `.env.example`

## Dev Commands
- Python tests: `pytest -q`
- Worker local preview: `npm run cf:preview`
- Worker deploy: `npm run cf:deploy`
- Worker logs: `npm run cf:tail`

## Change Strategy
- Prefer small, behavior-preserving changes.
- Keep event contract stable unless asked for a versioned API change.
- When changing policy logic (schedule/dedupe/suppression), add or update tests in `tests/test_api.py`.
- When changing Worker behavior, reflect any contract-relevant changes in `README.md` and `docs/ARCHITECTURE.md`.

## Validation Checklist
- Run `pytest -q` for FastAPI logic regression coverage.
- For Worker changes, run `npm run cf:preview` and test:
  - `GET /health/live`
  - `GET /health/ready`
  - `GET /v1/zones`
  - `POST /v1/events/cv` with valid and invalid payloads
- Confirm `/metrics` still exposes expected counters.

## Data and State
- FastAPI stores runtime state in SQLite (`data/alert_relay.db` by default).
- Worker stores runtime state in Durable Object storage.
- Dedupe/suppression keys are time-window gates and must remain stable unless migration is intentional.

## Handoff Notes Template
When finishing a task, include:
- What changed (files + behavior)
- Validation performed (commands/endpoints)
- Known risks or follow-ups
- Whether Worker and FastAPI behavior are still aligned
