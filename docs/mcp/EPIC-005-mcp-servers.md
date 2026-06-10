# EPIC-005: MCP Servers (production-shaped, simulator-backed)

**Goal**: All MCP servers from [SPEC-002](../connectors/SPEC-002-mcp-tool-contracts.md) wired to simulators for MVP. Production connector swap is a config change.

**Duration**: Week 4–6

## Stories

### S5.1 — MCP server base class
- Common: provenance injection, audit logging hook, error wrapping, budget enforcement.

**DoD**: One reference tool uses it end-to-end.

### S5.2 — Scope-tier servers
- `assets`, `kg`, `probe`, plus `trs` (from EPIC-003) and `templates` (from EPIC-004).

**DoD**: Tier catalog reachable; tool list matches SPEC-002.

### S5.3 — Evidence-tier servers
- `pi`, `dcs`, `alarms`, `maximo`, `sap_pm`, `documents`, `vibration`, `lab` — all backed by simulators.

**DoD**: An evidence bundle covering all sources can be assembled.

### S5.4 — Reason-tier servers
- `evidence.score_failure_mode`, `causemap.*`, `kg.traverse_neighborhood`.

**DoD**: Cause map can be constructed for a scenario.

### S5.5 — Govern-tier servers
- `probe.submit_for_review`, `probe.record_review_decision`, `cmms.*`, `corpus.index_probe`, `overlay.*`.

**DoD**: CMMS write-back preview + commit works against Maximo simulator.

### S5.6 — Cross-cutting: budget tracker
- Per-probe budget accounting.
- Tool calls check against budget; `budget_exceeded` returned cleanly.

**DoD**: Probe with low budget halts gracefully.
