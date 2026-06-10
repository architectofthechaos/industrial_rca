# EPIC-002 — Executable Task Breakdown (Simulators)

One task per story. Each task is a self-contained unit of work for Claude Code.
Reference docs: [EPIC-002](EPIC-002-simulators.md), [SPEC-007](SPEC-007-simulator-behavior.md), [SPEC-008](SPEC-008-scenario-catalog.md), [SPEC-014](SPEC-014-simulator-fixture-schema.md).

Stack: Python 3.12, uv workspace (per ADR-0009). All simulators live under `packages/simulators/`. They read the shared fixture tree and speak source-native protocols — they do NOT import `packages/contracts`, MAR, TRS, or `connector_sdk`.

Dependency order: **S2.1 blocks S2.2–S2.7.** S2.8 can be built alongside S2.1. The six simulators are mutually independent after S2.1.

---

## TASK-S2.1 — Shared fixture loader and reference-plant fixtures

**Description**
Build the shared fixture layer that every simulator reads from: Pydantic models for the fixture YAML schemas (plant, asset, signal, scenario, time_axis), a loader that parses and validates `fixtures/refplant/`, a scenario expander that compiles a scenario into a per-second time series per affected signal (baseline + diurnal + noise + trajectory + injected events), and the full reference-plant fixture data (4 centrifugal pumps in different services and the 4 MVP scenarios). Includes the `_validate.py` validator enforcing all referential-integrity rules in SPEC-014 (asset refs resolve, signal roles exist on the asset template, canonical units are valid QUDT, scenario assets/roles exist, no two scenarios concurrently affect one asset, t0+duration within time bounds). This is the single source of truth shared across all six simulators.

**Files modified**
- `packages/simulators/fixtures/__init__.py`
- `packages/simulators/fixtures/schema.py` (Pydantic models per SPEC-014)
- `packages/simulators/fixtures/loader.py`
- `packages/simulators/fixtures/scenario_expander.py`
- `packages/simulators/fixtures/_validate.py`
- `fixtures/refplant/plant.yaml`
- `fixtures/refplant/assets/{P-101A,P-101B,P-102A,P-103A}.yaml`
- `fixtures/refplant/signals/*.yaml` (discharge_pressure, suction_pressure, motor_amps, vibration_radial, bearing_temp per pump)
- `fixtures/refplant/scenarios/{seal_leak_progression,cavitation_event,bearing_failure,motor_trip_overload}.yaml`
- `fixtures/refplant/work_orders/{seed_2025_q4,seed_2026_q1}.yaml`
- `fixtures/refplant/time_axis.yaml`
- `fixtures/refplant/VERSION`
- `packages/simulators/pyproject.toml`
- `packages/simulators/tests/test_fixture_loader.py`

**Expected behaviour**
`loader.load("fixtures/refplant/")` returns a fully-validated object graph. Running the validator on the reference fixtures passes; 12 deliberately-broken fixture variants each fail with a specific, named error. The scenario expander turns any scenario into a deterministic per-second series for each affected signal that agrees across calls (seeded). Cross-fixture coherence holds: a scenario's events reference only assets/signals/roles that exist. Invalid fixtures cause the loader to raise rather than return partial data.

---

## TASK-S2.8 — Realism injection harness

**Description**
Build the shared library that every simulator imports to inject source-side realism: clock skew, dropped intervals/messages, added latency (mean + p99), error-rate (5xx for HTTP sources), and bad-quality flags. Behaviour is configured per simulator via env vars (`SIM_CLOCK_SKEW_SECONDS`, `SIM_DROP_RATE`, `SIM_BAD_QUALITY_RATE`, `SIM_5XX_RATE`, `SIM_LATENCY_MEAN_MS`, `SIM_LATENCY_P99_MS`) per SPEC-007, with sane defaults. Exposes hooks/decorators the simulators wrap their response paths in (e.g. `maybe_drop()`, `apply_latency()`, `maybe_error()`, `skew_timestamp()`). Deterministic when seeded so tests are repeatable.

**Files modified**
- `packages/simulators/realism/__init__.py`
- `packages/simulators/realism/config.py` (env-var parsing + defaults)
- `packages/simulators/realism/inject.py` (skew/drop/latency/error/quality hooks)
- `packages/simulators/tests/test_realism.py`

**Expected behaviour**
With all knobs at default, the harness exercises connector retry/circuit-breaker paths (occasional 5xx, drops, latency spikes) without breaking normal operation. Each knob is independently controllable via env var and verifiably changes output distribution under a seeded test. With realism disabled (all rates 0, skew 0), responses are clean and deterministic. The same harness instance is importable and usable identically by an HTTP, OPC UA, or MQTT simulator.

---

## TASK-S2.2 — PI Historian simulator (PI Web API REST subset)

**Description**
Build an HTTP server implementing the PI Web API REST subset the PI connector calls: `/streams/{webId}/recorded`, `/streams/{webId}/interpolated`, `/streams/{webId}/summary`, and `/eventframes`. Synthesize time series on demand from the fixture via the scenario expander (baseline + diurnal sine + noise floor + scenario-injected anomalies). Honour PI `mode` semantics: `stored` returns only points crossing the compression deviation since the last stored point; `interpolated` returns interpolated values each flagged `is_interpolated`; `aggregated` returns true aggregates over requested intervals. Wrap response paths in the S2.8 realism harness (clock skew default ±2s, 1% dropped intervals, 0.5% bad-quality flags).

**Files modified**
- `packages/simulators/pi/__init__.py`
- `packages/simulators/pi/app.py` (FastAPI server + routes)
- `packages/simulators/pi/webid.py` (WebID encode/decode for fixture signals)
- `packages/simulators/pi/synthesize.py` (series synthesis + mode semantics)
- `packages/simulators/pi/Dockerfile`
- `packages/simulators/tests/test_pi_simulator.py`

**Expected behaviour**
Server boots on the reference fixture and serves all four endpoints. `recorded`, `interpolated`, and `aggregated` modes return materially different, mode-correct responses for the same WebID and time range. For each of the 4 scenarios, the affected signals show the expected anomaly shape at the expected scenario offsets. WebIDs resolve back to fixture signals. Realism flags are present and configurable. (DoD: the PI connector in EPIC-013 reads this successfully.)

---

## TASK-S2.3 — Maximo simulator (Maximo OSLC REST)

**Description**
Build an HTTP server implementing the Maximo OSLC REST subset: `/maxrest/oslc/os/mxwo` (work orders), `/maxrest/oslc/os/mxsr` (service requests), `/maxrest/oslc/os/mxfailrep` (failure reports), including the read query surface (`oslc.where`, `oslc.select`, paging) the connector uses, plus idempotent write-back endpoints. Seed work-order/notification history per asset matching each scenario's timeline (from the fixture). Emit local-time-without-TZ timestamps by default and include some legacy plant-specific (non-ISO-14224) failure codes to exercise connector normalization. Inject occasional 5xx via the realism harness to exercise retry.

**Files modified**
- `packages/simulators/maximo/__init__.py`
- `packages/simulators/maximo/app.py` (FastAPI OSLC routes)
- `packages/simulators/maximo/oslc.py` (oslc.where/select parsing, paging, response shaping)
- `packages/simulators/maximo/seed.py` (scenario → WO/SR/failrep history)
- `packages/simulators/maximo/Dockerfile`
- `packages/simulators/tests/test_maximo_simulator.py`

**Expected behaviour**
Server boots on the reference fixture and serves the three OSLC object structures. Querying work orders for an affected asset returns the scenario's WO history (e.g. seal-leak P-101A returns WO-50012345 and WO-50012402 at the right times). Timestamps are local-without-TZ and at least one failure record uses a legacy code. Write-back is idempotent — replaying the same notification payload does not duplicate. Occasional 5xx appear and are configurable. (DoD: Maximo connector reads work orders and writes back.)

---

## TASK-S2.4 — SAP PM simulator (SAP OData v2)

**Description**
Build an OData v2 service for plant maintenance notifications (`/sap/opu/odata/sap/PM_NOTIFICATION_SRV`) including the full CSRF token dance (`X-CSRF-Token: Fetch` handshake before writes), `$metadata`, and the `$filter`/`$expand`/`$select` query surface the connector uses, with SAP-style namespace prefixes. Model the same shared assets that also appear in Maximo but with different field names and coding schemes, so the connector's normalization/dedup path is exercised. Seed notification history from the scenario fixtures for the subset of plant that uses SAP PM.

**Files modified**
- `packages/simulators/sap_pm/__init__.py`
- `packages/simulators/sap_pm/app.py` (FastAPI OData v2 routes + CSRF)
- `packages/simulators/sap_pm/odata.py` ($metadata, $filter/$expand parsing, entity serialization)
- `packages/simulators/sap_pm/seed.py` (scenario → notifications, SAP field naming)
- `packages/simulators/sap_pm/Dockerfile`
- `packages/simulators/tests/test_sap_pm_simulator.py`

**Expected behaviour**
Server boots and serves `$metadata` and the notification entity set. A write without a valid fetched CSRF token is rejected; the fetch-then-write sequence succeeds. `$filter` and `$expand` return correctly shaped OData v2 payloads with namespace prefixes. For assets shared with Maximo, the same underlying event appears under SAP's different field names/codes. (DoD: SAP PM connector reads notifications; overlap with Maximo for shared assets is correctly modeled.)

---

## TASK-S2.5 — OPC UA simulator (real OPC UA server)

**Description**
Build an `asyncua`-backed OPC UA server listening on `opc.tcp://localhost:4840` that mirrors the AF/plant hierarchy as an OPC UA address space and exposes current values for a subset of signals, updating at 1 Hz. Drive current values from the scenario expander so real-time values track the active scenario. This is the real-time trigger source (not historical evidence — that is PI). Apply realism (clock skew, occasional bad quality) via the S2.8 harness.

**Files modified**
- `packages/simulators/opcua/__init__.py`
- `packages/simulators/opcua/server.py` (asyncua server, address-space build, 1 Hz updater)
- `packages/simulators/opcua/address_space.py` (fixture hierarchy → OPC UA nodes)
- `packages/simulators/opcua/Dockerfile`
- `packages/simulators/tests/test_opcua_simulator.py`

**Expected behaviour**
Server starts on `opc.tcp://localhost:4840` with an address space mirroring the reference plant hierarchy. An OPC UA client can browse the hierarchy, subscribe to a node, and read current values that update at ~1 Hz. When a scenario is active, the subscribed values reflect the scenario trajectory in real time. Node IDs/browse paths map deterministically to fixture signals. (DoD: OPC UA connector subscribes and reads current values.)

---

## TASK-S2.6 — SharePoint / S3 document simulator (HTTP REST)

**Description**
Build an HTTP server mirroring SharePoint Search + Microsoft Graph drive-item endpoints (with an optional S3-compatible MinIO bucket variant) serving the fixture documents: datasheets, simplified P&IDs, prior RCA reports, and operator narratives matched to scenarios. Implement a local search over fixture documents (BM25 + embedding index) behind the Search endpoint. Include realistic OCR noise on some PDFs to exercise downstream extraction. Apply realism (latency, occasional errors) via the harness.

**Files modified**
- `packages/simulators/documents/__init__.py`
- `packages/simulators/documents/app.py` (FastAPI Search + Graph drive-item routes)
- `packages/simulators/documents/search_index.py` (BM25 + embedding index over fixtures)
- `packages/simulators/documents/s3_variant.py` (MinIO seeding + GetObject/ListObjectsV2)
- `fixtures/refplant/documents/{datasheets,pids,rca_reports}/...` (doc metadata + PDF bytes)
- `packages/simulators/documents/Dockerfile`
- `packages/simulators/tests/test_documents_simulator.py`

**Expected behaviour**
Server boots and serves Search + drive-item endpoints (and, in S3 mode, GetObject/ListObjectsV2 against a seeded MinIO bucket). A scenario-relevant query (e.g. "mechanical seal" for the seal-leak scenario) returns the matching seeded documents ranked sensibly. Drive-item/GetObject returns the correct document bytes, some with injected OCR noise. (DoD: documents connector returns relevant docs for scenario queries.)

---

## TASK-S2.7 — MQTT Sparkplug B simulator (real broker + publisher)

**Description**
Stand up a real MQTT broker (Mosquitto or EMQX in compose) plus a Python publisher that emits Sparkplug B-encoded payloads driven by the fixture. On startup publish BIRTH (NBIRTH/DBIRTH) messages declaring tag metadata and aliases; then publish DATA messages at 1 Hz for subscribed metrics with correct `seq` sequencing, driven by the scenario expander. This is one of the authoritative sources for TRS alias ingestion. Apply realism (drops, clock skew) via the harness.

**Files modified**
- `packages/simulators/mqtt/__init__.py`
- `packages/simulators/mqtt/publisher.py` (Sparkplug B BIRTH/DATA, seq handling, 1 Hz loop)
- `packages/simulators/mqtt/sparkplug.py` (protobuf payload encode/decode helpers)
- `packages/simulators/mqtt/compose.yaml` (broker)
- `packages/simulators/mqtt/Dockerfile`
- `packages/simulators/tests/test_mqtt_simulator.py`

**Expected behaviour**
Broker comes up and the publisher connects. On connect, BIRTH messages declare tag metadata and aliases for the fixture signals; DATA messages then flow at ~1 Hz with monotonically increasing `seq`. A subscribing client can decode Sparkplug B payloads and resolve aliases from BIRTH to read values that track the active scenario. (DoD: UNS connector subscribes and TRS can ingest aliases from BIRTH messages.)
