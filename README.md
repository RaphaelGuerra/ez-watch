# EZ-WATCH Alert Relay (MVP)

Intelbras-first computer vision alert relay for sensitive resort zones (almoxarifado, bars, cash/backoffice), with Hikvision-compatible event ingestion.

## What is implemented

- `POST /v1/events/cv` for CV events from VMS/NVR (`intelbras` or `hikvision`).
- Zone policy engine loaded from YAML:
  - camera-to-zone mapping validation,
  - active schedule checks,
  - dedupe + suppression windows.
- Alert delivery:
  - primary: WhatsApp webhook,
  - fallback: SMTP email.
- Structured event and alert persistence in SQLite.
- 30-day retention cleanup (configurable).
- Camera heartbeat endpoint + offline alert monitor.
- Prometheus metrics endpoint.

## Project structure

- `app/main.py`: FastAPI app and endpoints.
- `app/relay.py`: core processing logic.
- `app/store.py`: SQLite persistence.
- `app/channels.py`: WhatsApp/email integrations.
- `app/zones.py`: YAML zone loader.
- `configs/zones.yaml`: zone policy file.

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

## Cloudflare Workers (same style as ez-match)

This repo now uses root-level `wrangler.toml` and `npm run cf:*` scripts, like `ez-match`.
Cloudflare Containers currently requires Docker running locally during `wrangler deploy`.

1. Install JS tooling:

```bash
npm install
```

2. Set required Worker secrets:

```bash
npx wrangler secret put WHATSAPP_WEBHOOK_URL
```

Optional secrets:

```bash
npx wrangler secret put WHATSAPP_BEARER_TOKEN
npx wrangler secret put SMTP_HOST
npx wrangler secret put SMTP_USERNAME
npx wrangler secret put SMTP_PASSWORD
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

## Zone config format

`configs/zones.yaml`

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

All settings are documented in `.env.example`.

Minimum required for WhatsApp delivery:

- `WHATSAPP_ENABLED=true`
- `WHATSAPP_WEBHOOK_URL=<provider webhook>`

For email fallback:

- `EMAIL_ENABLED=true`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `EMAIL_TO_CSV`

## Test

```bash
pytest -q
```

## Operational notes

- Configure Intelbras Defense IA / SIM Next `URL command` action pointing to:
  - `POST https://<relay-host>/v1/events/cv`
- Keep VMS email action as native fallback in addition to relay fallback.
- Face recognition is intentionally excluded from MVP workflows.
