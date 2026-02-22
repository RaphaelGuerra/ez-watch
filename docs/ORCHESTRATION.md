# Agent Orchestration Playbook

## Goal
Enable multiple agents to collaborate on EZ-WATCH safely and with minimal rework.

## 1. Suggested Agent Roles
- Runtime Agent: Worker routing, Durable Object behavior, `wrangler.toml` changes.
- Policy Agent: Zone policy model, schedule logic, dedupe/suppression semantics.
- Delivery Agent: Pushover/WhatsApp/Email integrations and failure handling.
- Quality Agent: Tests, regression checks, docs and contract verification.

For small tasks, one agent can cover all roles.

## 2. Task Intake Contract
Before implementation, capture:
- Target runtime: `worker`, `fastapi`, or `both`
- Affected endpoints
- Expected behavior deltas (if any)
- Compatibility requirement (must remain backward-compatible or not)
- Validation scope (tests, local run, endpoint checks)

If target runtime is not provided, default to `worker`.

## 3. Work Partitioning Rules
- Avoid parallel edits in the same file.
- Partition by boundary:
  - API surface: `cloudflare/worker/src/index.ts` vs `app/main.py`
  - Policy model: `app/models.py`, `app/relay.py`, zone config docs
  - Persistence/metrics: `app/store.py`, Worker metric key paths
- Each agent owns one boundary at a time and submits a handoff note before another agent continues.

## 4. Handoff Checklist (Required)
Each agent should hand off with:
- Files changed
- Behavior changed
- Compatibility impact
- Commands executed
- Remaining risks

Use this format:

```text
Handoff
- Files: ...
- Behavior: ...
- Compatibility: none | breaking (...)
- Validation: ...
- Risks/Follow-ups: ...
```

## 5. Integration Sequence
1. Runtime Agent updates route/transport concerns.
2. Policy Agent aligns decision logic and reason codes.
3. Delivery Agent verifies outbound alert behavior and fallbacks.
4. Quality Agent runs tests, smoke checks, and doc updates.

## 6. Validation Matrix
Minimum checks before merge:
- `pytest -q`
- Event happy path returns `status=sent`
- Dedupe path returns `status=suppressed`, `reason=dedupe_window`
- Invalid zone/camera paths return expected 400s
- `/metrics` includes expected counter families
- `/health/live` and `/health/ready` are healthy

## 7. Change Safety Rules
- Do not silently change event contract fields.
- Keep reason strings stable; external consumers may parse them.
- Keep dedupe/suppression key formats stable unless migration is intentional and documented.
- Reflect behavior changes in docs (`README.md`, `docs/ARCHITECTURE.md`).

## 8. Coordination with Larger Project Environment
When EZ-WATCH is part of a multi-repo effort:
- Pin contracts first (payload schema, statuses, reasons, endpoint paths).
- Assign one integration owner to coordinate upstream (VMS/NVR), relay, and downstream notification stakeholders.
- Publish a single cutover checklist with exact environment vars/secrets and validation URLs.

## 9. Fast Start for New Agents
1. Read `AGENTS.md`.
2. Read `docs/ARCHITECTURE.md`.
3. Confirm target runtime.
4. Run baseline tests (`pytest -q`).
5. Implement smallest viable change.
6. Update docs if behavior changed.
