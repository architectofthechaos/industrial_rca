# SPEC-007: Simulator Behavior

- **Status**: Draft — reframed by [ADR-0012](../adrs/0012-connectors-own-the-contract.md)
- **Owner**: gvishnu
- **Related ADRs**: [0008](../adrs/0008-simulators-first.md), [0012](../adrs/0012-connectors-own-the-contract.md)

## Purpose

Defines how each simulator behaves **as a stand-in for a real source system** so connectors (and through them the agent) experience the same protocol surface as production. Simulators are dev/test infrastructure; **connectors** are product code.

## Where simulators sit in the stack

```
  Agent  ──MCP──▶  Connector (product code)  ──source protocol──▶  Simulator  OR  Real source
                                                              (dev/CI)         (prod)
```

- Simulators speak **source-side protocols** (PI Web API, OSLC REST, OPC UA, MQTT, SharePoint REST) — **not MCP**.
- The MCP tool contract lives on the **connector** (see [SPEC-002](SPEC-002-mcp-tool-contracts.md)).
- Swapping simulator ↔ real source is a **connector config change** (endpoint URL + auth), not a code change.

## Common architecture

Each simulator is a Python service that:
1. Exposes a **source-side protocol endpoint** matching the production system it imitates (PI Web API REST, Maximo OSLC, SAP OData, OPC UA server, MQTT broker, SharePoint Graph-like REST).
2. Reads from a shared **scenario fixture** describing the reference plant and time-bounded events (see [SPEC-014](SPEC-014-simulator-fixture-schema.md)).
3. Computes responses on demand from the fixture, including injected realism (latency, errors, partial data).

## Shared scenario fixture

```
fixtures/
├── plant.yaml                   # site/area/unit/equipment hierarchy
├── assets/
│   ├── P-101A.yaml              # centrifugal pump, charge service
│   ├── P-101B.yaml              # centrifugal pump, BFW service
│   ├── P-102A.yaml              # injection pump
│   └── P-103A.yaml              # transfer pump
├── signals/                     # one yaml per signal with role, units, range, source-system tag(s)
├── scenarios/
│   ├── seal_leak_progression.yaml
│   ├── cavitation_event.yaml
│   ├── bearing_failure.yaml
│   └── motor_trip_overload.yaml
└── time_axis.yaml               # base time T0 and clock-skew offsets per source
```

Each scenario YAML declares:
- Affected asset
- Failure mode (ISO 14224 code)
- Timeline of events (operating conditions, alarms, work orders, lab samples, operator notes)
- Expected RCA outcome (for evaluation harness)

## PI Historian simulator

**Source-side protocol**: subset of PI Web API REST (`/streams/{webId}/recorded`, `/interpolated`, `/summary`, `/eventframes`). The **PI connector** (product code) translates `pi.get_series` / `pi.get_event_frames` / `pi.get_summary` MCP calls into PI Web API HTTP requests.

Implementation:
- Synthesizes time series from scenario fixture using a baseline + perturbation model (sine for diurnal load, noise floor, scenario-injected anomalies).
- Honors `mode` parameter — stored vs interpolated vs aggregated behave differently:
  - `stored` — returns only points where the value crossed a compression deviation since the previous stored point.
  - `interpolated` — returns linear/previous/step interpolation between stored points; flags each value's `is_interpolated`.
  - `aggregated` — returns true aggregates over the requested intervals.
- Injectable realism: configurable clock skew (default ±2s drift vs UTC), occasional dropped intervals (1%), occasional bad-quality flags (0.5%).

## Maximo simulator

**Source-side protocol**: subset of Maximo OSLC REST (`/maxrest/oslc/os/mxwo`, `mxsr`, `mxfailrep`). The **Maximo connector** translates `maximo.*` MCP calls into OSLC requests and handles auth/cookies.

Implementation:
- Pre-seeded work order history per asset matching scenario timelines.
- Failure codes follow ISO 14224 where present; some legacy records have plant-specific codes (real-world messiness).
- Local-time-without-TZ timestamps by default (configurable per tenant), exercising our normalization path.
- Write-back: stores notification payloads to a local table; idempotency enforced.
- Realism: occasional 5xx responses (1%) to exercise retry policies.

## SAP PM simulator

**Source-side protocol**: SAP OData v2 service for notifications (`/sap/opu/odata/sap/PM_NOTIFICATION_SRV`). Connector handles CSRF token dance and namespace prefixes.

- Subset of plant uses SAP PM instead of Maximo; some assets appear in both.
- Different field names and coding schemes vs Maximo to exercise normalization in the **connector**.

## OPC UA simulator

**Source-side protocol**: actual OPC UA server (binary protocol, `opc.tcp://...`) using `asyncua`. Connector uses an OPC UA client library to read/subscribe.

- Exposes current values for a subset of signals at 1 Hz.
- Used for real-time triggers, not historical evidence (that's PI).
- Implements OPC UA address space mirroring AF hierarchy.

## SharePoint / S3 simulator

**Source-side protocol**: HTTP REST API mirroring SharePoint Search + Graph drive item endpoints (S3 variant uses the S3 GetObject/ListObjectsV2 API). Connector calls these directly.

- Pre-seeded with datasheets, simplified P&IDs, prior RCA reports, operator narratives matched to scenarios.
- Documents have realistic OCR noise on some PDFs (exercising downstream extraction).
- Search uses local BM25 + embedding index over fixture documents.

## MQTT Sparkplug B simulator

**Source-side protocol**: actual MQTT broker (Mosquitto/EMQX in docker) publishing Sparkplug B-encoded payloads. Connector is an MQTT client.

- Publishes BIRTH messages declaring tag metadata at startup.
- Publishes DATA messages at 1 Hz for subscribed metrics.
- Used as one of the authoritative sources for TRS ingestion.

## Realism flags (per simulator)

Each simulator accepts env vars or a config block to inject realism:
```
SIM_CLOCK_SKEW_SECONDS=2.4
SIM_DROP_RATE=0.01
SIM_BAD_QUALITY_RATE=0.005
SIM_5XX_RATE=0.01
SIM_LATENCY_MEAN_MS=120
SIM_LATENCY_P99_MS=2500
```

## Contract tests

Contract tests live **on connectors**, not simulators. The test pattern is:

1. Start simulator container.
2. Point connector at simulator endpoint.
3. Invoke each MCP tool the connector exposes.
4. Validate every response against `packages/contracts` Pydantic models.
5. Assert tool names, input shapes, and output shapes match [SPEC-002](SPEC-002-mcp-tool-contracts.md).
6. Assert errors use the standard `ToolError` shape.

The same test suite must pass against a real source in the production-parity stage. A CI job runs the connector↔simulator contract tests on every PR.

## Production parity contract

Before any simulator-trained agent claims "production-ready," we must:
1. Connect to at least one real instance per simulator type.
2. Run the same scenarios against the real instance and compare contracts.
3. Document any discrepancies in `docs/simulator_parity.md`.
