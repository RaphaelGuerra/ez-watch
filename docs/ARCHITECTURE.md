# EZ-WATCH Architecture

## 1. System Summary
EZ-WATCH is an alert relay for computer-vision events from Intelbras/Hikvision-compatible upstream systems.
It enforces zone policy and forwards actionable alerts.

Current production architecture is Cloudflare Worker + Durable Object.
FastAPI remains in-repo as rollback/reference.

## 2. Runtime Topology

### Production Path (Canonical)
- Entry: `cloudflare/worker/src/index.ts`
- Edge runtime: Cloudflare Worker
- Stateful gate/metrics store: Durable Object (`AlertRelayContainer`)
- Delivery channel: Pushover API

### Legacy Path (Reference/Fallback)
- Entry: `app/main.py`
- Framework: FastAPI
- Stateful store: SQLite via `app/store.py`
- Delivery channels: WhatsApp webhook, Email SMTP

## 3. Request Lifecycle (`POST /v1/events/cv`)
1. Parse and validate payload (vendor, event_type, camera_id, zone_id, timestamp_utc, optional confidence/media/raw_payload).
2. Increment received metric.
3. Resolve zone config by `zone_id`.
4. Validate camera belongs to zone (`camera_id` in `zone.camera_ids`).
5. Evaluate active schedule window in configured timezone.
6. Apply dedupe window (`zone + camera + event_type`).
7. Apply suppression window (`zone + camera`).
8. Build human-readable alert message.
9. Dispatch alert to configured channel.
10. Update dedupe/suppression timestamps and counters.
11. Return result (`sent`, `suppressed`, `rejected`, `failed`).

## 4. Policy Model
Zone policy shape (both runtimes conceptually align):
- `zone_id`
- `site_id`
- `camera_ids[]`
- `severity`
- `active_schedule.timezone`
- `active_schedule.windows[]` with `days`, `start`, `end`
- `alert_destinations[]`
- `suppression_window_sec`
- `dedupe_window_sec`

### Schedule Behavior
- Empty window list means always active.
- Supports same-day windows (`00:00` to `23:59`) and overnight windows (`18:00` to `06:00`).
- Uses zone timezone; falls back to default timezone when needed.

### Decision Reasons
- `outside_active_schedule`
- `dedupe_window`
- `suppression_window`
- `unknown_zone`
- `camera_not_mapped_to_zone`
- Delivery failures (for example `pushover_send_failed`, `pushover_timeout`)

## 5. State and Persistence

### Durable Object (Worker)
Stored keys include:
- Dedupe timestamps: `dedupe:<zone_id>:<camera_id>:<event_type>`
- Suppression timestamps: `suppress:<zone_id>:<camera_id>`
- Heartbeats: `heartbeat:<camera_id>`
- Metrics counters with prefixes:
  - `metric:events_received:`
  - `metric:events_suppressed:`
  - `metric:alerts_sent:pushover:`

### SQLite (FastAPI)
Tables in `app/store.py`:
- `events`
- `alerts`
- `dedupe_state`
- `camera_heartbeat`
- `health_alert_state`

## 6. Observability
Exposed endpoints:
- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`
- `GET /v1/zones`

Prometheus counters include:
- `cv_events_received_total`
- `cv_events_suppressed_total`
- `cv_alerts_sent_total`

FastAPI also exposes:
- `cv_event_processing_seconds`
- `cv_camera_health_alerts_total`

## 7. Configuration Sources
- Worker runtime config: `wrangler.toml`
- Worker zone config: `ZONE_CONFIG_JSON` in `wrangler.toml`
- Worker secrets (required for delivery):
  - `PUSHOVER_APP_TOKEN`
  - `PUSHOVER_USER_KEY`
- FastAPI env template: `.env.example`
- FastAPI zone file: `configs/zones.yaml`

## 8. Known Divergences (Important)
- Worker is Pushover-based and treats `whatsapp` destination as allowed for Pushover path compatibility.
- FastAPI uses WhatsApp webhook + Email fallback.
- FastAPI has background camera-offline monitor; Worker currently stores heartbeat but does not trigger offline alerts.

If tasks must keep both runtimes aligned, explicitly update both code paths.

## 9. Test Coverage
FastAPI behavior tests live in `tests/test_api.py` and cover:
- Successful alert send
- Dedupe suppression
- Outside-schedule suppression
- Email fallback when WhatsApp fails

Worker currently has no dedicated test suite in this repository.
