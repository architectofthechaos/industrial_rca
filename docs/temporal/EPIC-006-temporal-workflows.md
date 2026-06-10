# EPIC-006: Temporal Workflows

**Goal**: Implement the four tier workflows and ProbeOrchestrator per [SPEC-004](SPEC-004-probe-workflow.md).

**Duration**: Week 6–8

## Stories

### S6.1 — Temporal setup + worker
- Local Temporal cluster in docker-compose (already from EPIC-001).
- Python worker package wiring activities + workflows.
- Health check, graceful shutdown.

**DoD**: Empty workflow runs end-to-end against local Temporal.

### S6.2 — ProbeOrchestrator
- Parent workflow per SPEC-004.
- Child workflow invocations.
- Cancellation propagation.

**DoD**: Orchestrator runs a stubbed probe through all 4 tiers.

### S6.3 — ScopeWorkflow
- Calls `run_agent_tier("scope", ...)` activity.
- Awaits `tag_confirmation_response` signal when needed.

**DoD**: A probe scopes against the reference plant successfully.

### S6.4 — EvidenceWorkflow
- Parallel fan-out activities for each evidence tool.
- Bundle assembly + persistence to object storage.

**DoD**: Bundle for a scenario contains all expected components.

### S6.5 — ReasonWorkflow
- Calls `run_agent_tier("reason", ...)` activity.
- Inconclusive-loop handling.

**DoD**: For each scenario, top failure mode candidate matches expected.

### S6.6 — GovernWorkflow
- HITL signals: `review_decision`, `cmms_writeback_authorization`.
- Timeout + escalation.

**DoD**: End-to-end probe completes with reviewer approval flow.

### S6.7 — Versioning
- `workflow.get_version` checks for each workflow.
- Replay tests against stored histories.

**DoD**: A v1 probe replays cleanly after a v2 deploy.
