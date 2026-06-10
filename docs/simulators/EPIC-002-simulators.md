# EPIC-002: Source Simulators

**Goal**: Six **source-side simulators** that imitate real upstream systems (PI Web API, Maximo OSLC, SAP OData, OPC UA, MQTT, SharePoint REST) so connectors (see [EPIC-013](EPIC-013-connectors.md)) can be developed and tested without customer access.

**Duration**: Week 1–4 — **fully parallel with everything else**. Can start day 1.

**Dependencies**: None inside this repo. Simulators read YAML fixtures and speak off-the-shelf source protocols. They do **not** import `packages/contracts`, do **not** call MAR or TRS, do **not** depend on `connector_sdk`.

**Parallelism**: All six stories below can run simultaneously by different engineers. They share only the fixture tree (S2.1) and the realism harness (S2.8).

**Reference**: [ADR-0008](../adrs/0008-simulators-first.md), [ADR-0012](../adrs/0012-connectors-own-the-contract.md), [SPEC-007 Simulator Behavior](SPEC-007-simulator-behavior.md), [SPEC-008 Scenario Catalog](SPEC-008-scenario-catalog.md), [SPEC-014 Simulator Fixture Schema](SPEC-014-simulator-fixture-schema.md)

> **Why this can finish first**: Simulators are dumb — they replay a YAML scenario as a source-protocol response. No business logic, no canonical contracts, no asset/signal resolution. The hard parts (provenance, units, time, retries, validation) live on **connectors** ([EPIC-013](EPIC-013-connectors.md)), which sit on the critical path.

> **Scope change (2026-06-04)**: Simulators do **not** expose MCP. MCP lives on **connectors** ([EPIC-013](EPIC-013-connectors.md)). Each simulator exposes the same source-side protocol as the real system it imitates.

## Stories (all parallelizable)

### S2.1 — Shared fixture loader [BLOCKER FOR S2.2–S2.7]
- YAML loaders for plant, assets, signals, scenarios per [SPEC-014](SPEC-014-simulator-fixture-schema.md).
- Validation against Pydantic schemas.
- Fixture data for reference plant (4 centrifugal pumps in different services).

**DoD**: Loader fully validates `fixtures/refplant/`; scenario expansion compiles into per-second time series for simulators.

### S2.2 — PI Historian simulator (source-side: PI Web API REST subset)
- HTTP server implementing `/streams/{webId}/recorded`, `/interpolated`, `/summary`, `/eventframes`.
- Synthesized time series from fixture (baseline + perturbations + scenario injection).
- Honors PI Web API `mode` (stored / interpolated / aggregated) semantics.
- Injectable realism (clock skew, drops, bad-quality).

**DoD**: PI connector (EPIC-013 S13.2) successfully reads data; 4 scenarios produce expected anomalies in simulated data.

### S2.3 — Maximo simulator (source-side: Maximo OSLC REST)
- HTTP server implementing `/maxrest/oslc/os/mxwo`, `mxsr`, `mxfailrep` endpoints.
- Local-time-without-TZ timestamps to exercise connector normalization.
- Idempotent write-back endpoints.

**DoD**: Maximo connector reads work orders and writes back; scenarios produce expected WO history.

### S2.4 — SAP PM simulator (source-side: SAP OData v2)
- OData v2 service for notifications with CSRF token dance.
- Different field names from Maximo for the same events.

**DoD**: SAP PM connector reads notifications; overlap with Maximo for shared assets is correctly modeled.

### S2.5 — OPC UA simulator (source-side: actual OPC UA server)
- `asyncua`-backed OPC UA server on `opc.tcp://localhost:4840`.
- 1 Hz current values mirroring AF hierarchy.

**DoD**: OPC UA connector subscribes and reads current values.

### S2.6 — SharePoint / S3 simulator (source-side: HTTP REST)
- HTTP server mirroring SharePoint Search + Graph drive item endpoints.
- Optional S3-compatible bucket alternative (MinIO with seeded objects).
- Fixture documents: datasheets, P&IDs, prior RCA reports.

**DoD**: Documents connector returns relevant docs for scenario queries.

### S2.7 — MQTT Sparkplug B simulator (source-side: actual MQTT broker)
- Mosquitto/EMQX in compose; Python publisher that emits Sparkplug B-encoded payloads.
- BIRTH messages declaring metadata; DATA messages at 1 Hz.

**DoD**: UNS connector subscribes and TRS can ingest aliases from BIRTH messages.

### S2.8 — Realism injection harness
- Shared library all simulators import for clock skew, drop, latency, error-rate behavior.
- Configurable via env vars per [SPEC-007](SPEC-007-simulator-behavior.md).

**DoD**: Configurable knobs work; default settings exercise connector retry / circuit-breaker paths in tests.

## Suggested parallel build order (single engineer)

If one engineer builds all six, this minimizes context switches:

1. **Day 1–2**: S2.1 fixture loader + S2.8 realism harness (foundation for everything else).
2. **Day 3–4**: S2.7 MQTT (simplest — just publish bytes).
3. **Day 5–7**: S2.5 OPC UA (asyncua server, well-documented).
4. **Week 2**: S2.6 SharePoint/S3 (FastAPI + MinIO).
5. **Week 3**: S2.2 PI Web API (most surface area, most semantics).
6. **Week 4**: S2.3 Maximo + S2.4 SAP PM in parallel (both are REST + business-object mapping).

If two engineers work in parallel, split at week 1 — historian/realtime track (S2.2, S2.5, S2.7) vs CMMS/docs track (S2.3, S2.4, S2.6).

## Out of scope (moved to EPIC-013)

- MCP server implementation
- Pydantic-validated tool responses
- Provenance stamping
- Unit / timestamp normalization to canonical forms
- Connector contract tests
