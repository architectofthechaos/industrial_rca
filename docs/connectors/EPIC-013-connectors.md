# EPIC-013: Connectors (Product Code)

**Goal**: Six **connectors** that own the MCP tool contracts with the agent, translate to source-side protocols, and work identically against [simulators (EPIC-002)](EPIC-002-simulators.md) in dev and against real systems in production.

**Duration**: Week 4–6 — connectors are **on the critical path**. They depend on contracts, MAR, TRS, and the connector_sdk.

**Dependencies**:
- `packages/contracts` (EvidenceBundle, AssetDescriptor, SignalDescriptor, Provenance, ToolError) — from EPIC-001
- MAR (`assets.resolve`, `assets.get`) — from EPIC-012
- TRS (`trs.resolve_tag`, `trs.get_signal`) — from EPIC-003
- `connector_sdk` (S13.1) — builds first within this epic
- Either a matching [EPIC-002 simulator](EPIC-002-simulators.md) or a real source to test against

**Reference**: [ADR-0012](../adrs/0012-connectors-own-the-contract.md), [SPEC-002 MCP Tool Contracts](SPEC-002-mcp-tool-contracts.md), [SPEC-007 Simulator Behavior](../simulators/SPEC-007-simulator-behavior.md), [SPEC-013 Tenant Onboarding](../foundations/SPEC-013-tenant-onboarding.md)

> **Connectors are product code.** They ship to customers. Simulators do not. This epic is the line between "we have a demo" and "we have a product."

> **Why connectors sit on the critical path while simulators don't**: A connector translates MCP ↔ source protocol, stamps provenance, normalizes units and time, validates against Pydantic contracts, resolves IDs through MAR and TRS, and handles credentials and retries. Every one of those depends on internal code. A simulator just replays YAML over an off-the-shelf protocol library.

## Common platform (S13.1)

A `packages/connector_sdk/` library every connector imports:

- **MCP server skeleton** (FastMCP) with tier-aware tool registration.
- **Pydantic validators** wrapping every outbound tool response against `packages/contracts`.
- **Provenance stamper** — one decorator that injects `Provenance` into every response ([ADR-0010](../adrs/0010-provenance-and-audit.md)).
- **Unit normalizer** — QUDT-based ([ADR-0002](../adrs/0002-units-of-measure.md)).
- **Time normalizer** — source-local → UTC, with `TimeBasis` carried through ([ADR-0006](../adrs/0006-time-handling.md)).
- **Credential broker client** — reads endpoint + secret refs from connector config; never logs secrets.
- **Retry + circuit breaker** — tenacity-based; budget-aware.
- **Tool error mapper** — source errors → standard `ToolError` ([SPEC-002](SPEC-002-mcp-tool-contracts.md)).
- **Cost accounting** — emits budget metrics per call.

**DoD**: A toy "echo connector" against a toy "echo simulator" passes a 50-line example test using only the SDK.

## Stories

### S13.2 — PI connector (`pi-connector`)
- MCP tools: `pi.get_series`, `pi.get_event_frames`, `pi.get_summary`.
- Translates to PI Web API REST (`/streams/.../{recorded,interpolated,summary}`).
- Pagination + WebID resolution + AF attribute traversal.
- Unit normalization (psig → kPa, °F → °C, etc.).
- Honors `mode` semantics and surfaces `is_interpolated` per measurement.

**DoD**: Runs identically against EPIC-002 PI simulator and the OSIsoft PI Web API demo image (parity check).

### S13.3 — Maximo connector (`maximo-connector`)
- MCP tools: `maximo.get_workorders`, `maximo.get_failure_history`, `maximo.preview_writeback`, `maximo.commit_writeback`.
- Translates to OSLC REST.
- Cookie / Maxauth handling.
- Idempotent commit via `idempotency_key` header + server-side dedup table.

**DoD**: Round-trip write-back against EPIC-002 Maximo simulator; commit replays return prior result, never duplicate.

### S13.4 — SAP PM connector (`sap-pm-connector`)
- MCP tools: `sap_pm.get_notifications`.
- OData v2 CSRF token dance.
- Field-name and code-scheme normalization to canonical contract.

**DoD**: Reads same scenario events as Maximo connector for overlap assets; contracts match.

### S13.5 — OPC UA connector (`opc-ua-connector`)
- MCP tools: `opc_ua.get_current_values`, `opc_ua.subscribe`.
- Uses `asyncua` client; long-lived subscription with reconnect.
- Maps OPC UA NodeIds to canonical `SignalID` via TRS.

**DoD**: Subscribe survives a simulator restart; current value reads match within 1 Hz.

### S13.6 — Documents connector (`documents-connector`)
- MCP tools: `documents.search`, `documents.fetch`.
- SharePoint Graph implementation **and** S3 implementation, behind a single MCP contract.
- BM25 + embedding hybrid (embeddings cached in MinIO).

**DoD**: Same MCP query against simulator and a real SharePoint dev tenant returns matching top-3.

### S13.7 — UNS / MQTT connector (`mqtt-uns-connector`)
- MCP tools: `uns.browse_namespace`, `uns.get_recent_messages`.
- Long-lived MQTT client subscribed to Sparkplug B namespaces.
- BIRTH parsing → emits alias-candidate events to TRS.

**DoD**: TRS receives alias candidates from simulator BIRTH; reconnect after broker bounce.

### S13.8 — Connector contract tests
- For every connector, a test matrix: `(connector × simulator)` and `(connector × real_source)`.
- All MCP responses validate against Pydantic models.
- `ToolError` shapes match SPEC-002.
- Provenance non-empty.
- Latency budgets enforced.

**DoD**: Green CI on every PR; nightly job runs real-source matrix against vendor demo images where licensed.

### S13.9 — Credential broker integration
- Connectors read `endpoint_url` + `credential_ref` from `connector_config` table.
- Credentials fetched from vault per call (no in-memory caching > 5 min).
- Onboarding workflow ([SPEC-013](../foundations/SPEC-013-tenant-onboarding.md) Stage 1) writes configs.

**DoD**: Rotating a credential in vault is picked up on next call without connector restart.

## Dependencies

- EPIC-001 (Foundations): contracts package must exist.
- EPIC-002 (Simulators): source-side endpoints must be reachable for dev/CI.
- EPIC-012 (MAR): asset resolution backs all `asset_id` fields.
- EPIC-003 (TRS): signal resolution backs all `signal_id` fields.

## Out of scope (post-MVP)

- Customer-specific connector forks. We ship one connector per source type; per-customer behavior is config + overlay only.
- Connector for vibration spectra (separate post-MVP epic).
- Connector for DCS SOE (separate epic; needs OPC HDA or vendor-specific binding).
