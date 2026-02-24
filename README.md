# EZ-WATCH Alert Relay (MVP)

Last updated: 2026-02-24

## Table of Contents

<!-- TOC start -->
- [What is implemented](#what-is-implemented)
- [Project structure](#project-structure)
- [Quick start (local)](#quick-start-local)
- [Quick start (Docker)](#quick-start-docker)
- [Cloudflare Workers (pure Worker MVP, no Docker)](#cloudflare-workers-pure-worker-mvp-no-docker)
- [Zone config format](#zone-config-format)
- [API contracts](#api-contracts)
  - [`POST /v1/events/cv`](#post-v1eventscv)
  - [`POST /v1/health/camera-ping`](#post-v1healthcamera-ping)
  - [Health and metrics](#health-and-metrics)
- [Environment variables](#environment-variables)
- [Test](#test)
- [Operational notes](#operational-notes)
<!-- TOC end -->

Intelbras-first computer vision alert relay for sensitive resort zones (almoxarifado, bars, cash/backoffice), with Hikvision-compatible event ingestion.

## What is implemented

- `POST /v1/events/cv` for CV events from VMS/NVR (`intelbras` or `hikvision`).
- Zone policy engine loaded from Worker env (`ZONE_CONFIG_JSON`):
  - camera-to-zone mapping validation,
  - active schedule checks,
  - dedupe + suppression windows.
- Alert delivery:
  - primary: Pushover API.
- Runtime persistence for dedupe/suppression/metrics in Durable Object storage.
- Camera heartbeat endpoint (offline monitor intentionally out of pure Worker MVP scope).
- Prometheus-style metrics endpoint.

## Project structure

- `cloudflare/worker/src/index.ts`: pure Worker + Durable Object runtime.
- `wrangler.toml`: deployment config and `ZONE_CONFIG_JSON`.
- `app/`: legacy FastAPI implementation kept as rollback/reference.
- `Dockerfile`, `docker-compose.yml`: legacy local/container path (not used for Cloudflare deploy).
- `AGENTS.md`: first-read guide for coding agents working in this repo.
- `docs/ARCHITECTURE.md`: detailed runtime, policy, and state behavior.
- `docs/ORCHESTRATION.md`: multi-agent collaboration and handoff playbook.

## Quick start (local)

```bash
cp .env.example .env
cp configs/zones.example.yaml configs/zones.yaml
python -m venv .venv
source .venv/bin/activate
pip install .[dev]
uvicorn app.main:app --reload
```

Service will be available at `http://localhost:8000`.

## Quick start (Docker)

```bash
cp .env.example .env
docker compose up --build
```

- API: `http://localhost:8000`
- MailPit UI (if email fallback is enabled): `http://localhost:8025`

## Cloudflare Workers (pure Worker MVP, no Docker)

This repo uses root-level `wrangler.toml` and `npm run cf:*` scripts, like `ez-match`.
Cloudflare deployment is pure Worker + Durable Object and does not require Docker.

1. Install JS tooling:

```bash
npm install
```

2. Set required Worker secrets:

```bash
npx wrangler secret put PUSHOVER_APP_TOKEN
npx wrangler secret put PUSHOVER_USER_KEY
```

Optional secrets:

```bash
# optional: tune timeout in wrangler.toml (milliseconds)
# PUSHOVER_TIMEOUT_MS = "8000"
```

3. Preview locally with Wrangler:

```bash
npm run cf:preview
```

4. Deploy:

```bash
npm run cf:deploy
```

5. Verify:
   - `https://<worker>.workers.dev/health/live`
   - `https://<worker>.workers.dev/health/ready`
   - `https://<worker>.workers.dev/v1/zones`
   - `https://<worker>.workers.dev/metrics`

## Zone config format

Worker runtime uses `ZONE_CONFIG_JSON` in `wrangler.toml`, equivalent to this structure:

```yaml
zones:
  - zone_id: almoxarifado
    site_id: resort-a
    camera_ids: ["cam-001", "cam-002"]
    severity: high
    active_schedule:
      timezone: America/Sao_Paulo
      windows:
        - days: [mon, tue, wed, thu, fri, sat, sun]
          start: "00:00"
          end: "23:59"
    alert_destinations: ["whatsapp", "email"]
    suppression_window_sec: 60
    dedupe_window_sec: 30
```

## API contracts

### `POST /v1/events/cv`

Example payload:

```json
{
  "vendor": "intelbras",
  "event_type": "intrusion",
  "camera_id": "cam-001",
  "camera_name": "Almox Entrance",
  "zone_id": "almoxarifado",
  "timestamp_utc": "2026-02-22T15:10:00Z",
  "confidence": 0.93,
  "media_url": "https://nvr.local/clip/abc123",
  "raw_payload": {
    "event_code": "tripwire",
    "source": "defense-ia"
  }
}
```

Successful response:

```json
{
  "status": "sent",
  "reason": null,
  "event_id": "f3f440fe-7c9c-4ad1-b8d4-8eff7ea49f19"
}
```

Possible statuses:

- `sent`
- `suppressed` (`outside_active_schedule`, `dedupe_window`, `suppression_window`)
- `rejected` (`unknown_zone`, `camera_not_mapped_to_zone`)
- `failed` (delivery failure)

### `POST /v1/health/camera-ping`

```json
{
  "camera_id": "cam-001",
  "timestamp_utc": "2026-02-22T15:10:00Z"
}
```

### Health and metrics

- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`
- `GET /v1/zones`

## Environment variables

Cloudflare Worker runtime is configured by `wrangler.toml` vars and Worker secrets.

Required for Pushover delivery:

- `PUSHOVER_ENABLED=true`
- Worker secret `PUSHOVER_APP_TOKEN=<pushover app token>`
- Worker secret `PUSHOVER_USER_KEY=<pushover user/group key>`

Optional:

- `PUSHOVER_TIMEOUT_MS=8000` (milliseconds)

## Test

```bash
pytest -q
```

## Operational notes

- Configure Intelbras Defense IA / SIM Next `URL command` action pointing to:
  - `POST https://<relay-host>/v1/events/cv`
- Keep VMS email action as native fallback if you need fallback outside pure Worker MVP.
- Face recognition is intentionally excluded from MVP workflows.
