# Agent Changelog Template

Use this file to append one entry per agent task/PR so future contributors can quickly understand what changed, why, and how it was verified.

## Entry Template

```text
## YYYY-MM-DD - <short change title>
Owner: <agent or person>
Scope: worker | fastapi | both | docs | infra

Summary
- <what changed>
- <what changed>

Files
- <absolute-or-repo-relative-path>
- <absolute-or-repo-relative-path>

Behavior Impact
- API: none | backward-compatible | breaking (<details>)
- Runtime impact: <latency/throughput/reliability notes or "none">
- Data/state impact: <schema/key changes or "none">

Validation
- Commands:
  - `<command>`
  - `<command>`
- Manual checks:
  - <endpoint/check>
  - <endpoint/check>

Risks / Follow-ups
- <known risk>
- <next step>
```

## Example Entry

```text
## 2026-02-22 - Add agent architecture and orchestration docs
Owner: codex
Scope: docs

Summary
- Added AGENTS.md with runtime guardrails and validation checklist.
- Added architecture and orchestration docs for multi-agent onboarding.

Files
- AGENTS.md
- docs/ARCHITECTURE.md
- docs/ORCHESTRATION.md
- README.md

Behavior Impact
- API: none
- Runtime impact: none
- Data/state impact: none

Validation
- Commands:
  - `pytest -q`
- Manual checks:
  - Confirmed docs are linked from README project structure section.

Risks / Follow-ups
- Worker path still lacks dedicated automated tests.
- Add worker-focused test harness in a future change.
```
