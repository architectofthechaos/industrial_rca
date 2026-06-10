# EPIC-002 Simulators — Implementation Plan

> **Status**: Plan only — no code yet. Project/package structure is a separate step (Step 1, later).
> **Authoritative sources**: [EPIC-002](EPIC-002-simulators.md), [TASKS-EPIC-002](TASKS-EPIC-002.md), [SPEC-007](SPEC-007-simulator-behavior.md), [SPEC-008](SPEC-008-scenario-catalog.md), [SPEC-014](SPEC-014-simulator-fixture-schema.md), [SPEC-015](../templates/SPEC-015-equipment-template-schema.md), [ADR-0008](../adrs/0008-simulators-first.md), [ADR-0009](../adrs/0009-monorepo-uv-workspaces.md), [ADR-0012](../adrs/0012-connectors-own-the-contract.md).
> **Layout convention**: flat (per TASKS-EPIC-002) — `packages/simulators/{fixtures,realism,pi,maximo,sap_pm,opcua,documents,mqtt}/`. Final paths + fixtures location confirmed in the structure step.

## 1. Guardrails (non-negotiable invariants)

These come straight from the ADRs/specs and constrain every task:

1. **Simulators stand in for SOURCES, not MCP.** Each speaks the *source-native* protocol (PI Web API REST, OSLC, OData v2, OPC UA binary, MQTT/Sparkplug B, SharePoint/Graph REST). No MCP anywhere here — MCP lives on connectors (EPIC-013).
2. **No imports from product code.** Simulators must NOT import `packages/contracts`, MAR, TRS, or `connector_sdk`. They read YAML fixtures and emit source-native responses. (This is what lets EPIC-002 finish before the critical path.)
3. **The fixture is the single source of truth.** Every simulator derives its output from the same `refplant` fixture + scenario set, so cross-source data is coherent (PI series, Maximo WOs, alarms all align on `t0 + offset`).
4. **Determinism when seeded.** Series synthesis and realism injection must be reproducible given a seed, so tests and eval replays are stable.
5. **Realism is opt-in and configurable.** All messiness (skew/drop/latency/5xx/bad-quality) flows through the S2.8 harness, driven by env vars, off by default-to-zero in clean tests.
6. **Python 3.12, uv workspace** (ADR-0009). Pydantic v2 for fixture schemas.

## 2. Dependency graph & build phases

```
        ┌──────────────┐     ┌──────────────┐
        │ S2.1 fixtures│     │ S2.8 realism │   (parallel — Phase 1)
        │  + loader    │     │   harness    │
        └──────┬───────┘     └──────┬───────┘
               │  (blocks)          │ (imported by all sims)
   ┌───────────┼────────────────────┼───────────────┐
   ▼           ▼          ▼          ▼        ▼       ▼
 S2.7 MQTT  S2.5 OPCUA  S2.6 Docs  S2.2 PI  S2.3 Maximo  S2.4 SAP PM
   └── Phase 2 ──┘     └── Phase 3 ──┘     └──── Phase 4 ────┘
```

**Phase 0 — Workspace bootstrap** (prereq; deferred to the structure step)
Root `pyproject.toml` (uv workspace), `.python-version`=3.12, ruff/mypy/pytest config, `packages/simulators/pyproject.toml`. No Track-A packages required.

**Phase 1 — Foundations**: S2.1 + S2.8 (parallelizable). Nothing else can be correct until S2.1 exists.

**Phase 2 — Simplest real-protocol sims**: S2.7 (MQTT) then S2.5 (OPC UA). These are the Week-1 quickstart targets; they validate the fixture+realism foundation against a real broker and a real OPC UA server early.

**Phase 3 — Document + historian**: S2.6 (SharePoint/S3), then S2.2 (PI — most surface area, `mode` semantics).

**Phase 4 — CMMS**: S2.3 (Maximo), then S2.4 (SAP PM, intentionally diverging field names for shared assets).

Rationale for ordering: do the load-bearing foundation first and prove it against the two simplest real protocols before tackling the high-surface-area HTTP sims. This front-loads risk on the fixture/expander (the thing everything depends on) and the realism harness (the thing every sim imports).

## 3. Cross-cutting design decisions to settle in Phase 1

| Topic | Proposal | Notes |
|---|---|---|
| **Series synthesis model** | `value(t) = baseline.mean + diurnal(t) + noise(seed,t) + trajectory(scenario,t) + events` | diurnal = sine of `diurnal_amplitude` over 24h; noise = seeded Gaussian at `stddev`; trajectory per scenario `signal_trajectories` (linear_decay/linear_growth/step_then_growth). |
| **Determinism** | seed = hash(signal_id, t_bucket) so any time range recomputes identically across calls/sims | Required by SPEC-014 test plan ("agrees across calls"). |
| **Time** | UTC ISO-8601 internally; per-source clock skew applied at the edge from `time_axis.yaml` | PI is reference (skew 0). Maximo emits local-without-TZ on purpose. |
| **Units** | Fixtures carry both `units_raw` (source) and `canonical_units` (QUDT). Sims emit **source/raw** units — normalization is the connector's job. | Don't normalize in the simulator. |
| **QUDT validation** | `_validate.py` checks `canonical_units` against a known QUDT symbol set | Need a QUDT symbol list/allowlist; scope = the units used by centrifugal_pump template (kPa, A, MilliM-PER-SEC, DEG_C, M3-PER-HR, L-PER-MIN). |
| **Template coupling** | Validator rule #3 (signal role ∈ template `signal_roles`) needs the centrifugal_pump template. Simulators must NOT import `packages/templates`. | Resolve by reading the template YAML as data (a copy/snapshot under fixtures), not importing the package. **Open question — see §7.** |

## 4. Task-by-task plan

### TASK-S2.1 — Shared fixture loader + reference-plant fixtures  *(Phase 1, blocker)*

**Objective**: the canonical fixture layer every sim reads.

**Build**
- `schema.py` — Pydantic v2 models for each YAML in SPEC-014: `Plant/Site/Area/Unit/EquipmentRef`, `Asset` (nameplate, external_ids, template ref), `Signal` (role, source_systems[], units_raw, canonical_units, range, baseline), `Scenario` (affected_asset, failure_mode_iso14224, duration, t0, `signal_trajectories[]`, `events[]`, `expected_rca`), `TimeAxis` (reference_time, clock_skews).
- `loader.py` — `load("fixtures/refplant/")` → fully-validated object graph; raise on any invalid/partial fixture rather than returning partial data.
- `scenario_expander.py` — compile a scenario into a **deterministic per-second series** per affected signal (baseline + diurnal + seeded noise + trajectory + injected events). Plus discrete-event extraction (operator_log → documents, alarm → alarms, work_order → maximo, etc.) keyed by sink so each downstream sim can pull the events it owns.
- `_validate.py` — enforce all 8 SPEC-014 referential-integrity rules:
  1. every `plant.yaml` asset_ref resolves under `assets/`
  2. every `signals/` file references an existing asset
  3. every signal `role` exists in the asset's template `signal_roles`
  4. every `canonical_units` is a valid QUDT symbol
  5. every scenario `affected_asset` exists
  6. every scenario signal `role` exists for the affected asset
  7. no two scenarios concurrently affect the same asset
  8. `t0 + duration_days` within `time_axis.yaml` bounds
- **Fixture data** (the actual refplant): `plant.yaml`; `assets/{P-101A,P-101B,P-102A,P-103A}.yaml` (4 pumps in different services — charge/BFW/injection/transfer); `signals/<asset>.<role>.yaml` for discharge_pressure, suction_pressure, motor_amps, vibration_radial, bearing_temp (+ seal_flush_flow where scenarios need it); `scenarios/{seal_leak_progression,cavitation_event,bearing_failure,motor_trip_overload}.yaml`; `work_orders/{seed_2025_q4,seed_2026_q1}.yaml`; `time_axis.yaml`; `VERSION`.

**Scenario↔asset mapping** (from SPEC-008): seal_leak→P-101A, cavitation→P-101B, bearing→P-102A, motor_trip→P-103A. Note rule #7 (one scenario per asset) is satisfied by this 1:1 mapping. **Watch**: SPEC-014's example uses failure code `LEK` for seal leak; SPEC-008 uses `ELP`. Reconcile during authoring (§7).

**Test strategy** (`test_fixture_loader.py`): golden refplant validates clean; **12 deliberately-broken variants** each fail with a *specific named error* (one per rule + edge cases like duplicate asset_ref, bad QUDT unit, out-of-bounds t0, overlapping scenarios, missing role on template, signal→nonexistent asset, etc.); expander produces identical series across two calls (determinism); scenario isolation (running P-101A scenario leaves P-101B series at baseline).

**DoD**: loader fully validates refplant; expander compiles to per-second series; 12 broken variants fail named errors.

---

### TASK-S2.8 — Realism injection harness  *(Phase 1, parallel)*

**Objective**: shared, deterministic messiness library every sim wraps its response path in.

**Build**
- `config.py` — parse env vars with sane defaults: `SIM_CLOCK_SKEW_SECONDS`, `SIM_DROP_RATE`, `SIM_BAD_QUALITY_RATE`, `SIM_5XX_RATE`, `SIM_LATENCY_MEAN_MS`, `SIM_LATENCY_P99_MS`.
- `inject.py` — hooks/decorators usable by HTTP, OPC UA, and MQTT sims identically: `maybe_drop()`, `apply_latency()` (mean + p99 tail), `maybe_error()` (5xx for HTTP sources), `maybe_bad_quality()`, `skew_timestamp()`.
- Seeded RNG so behavior is reproducible in tests.

**Test strategy** (`test_realism.py`): each knob independently and verifiably shifts the output distribution under a seed; all-zero/skew-0 ⇒ clean deterministic output; same instance importable by HTTP/OPC UA/MQTT paths; default settings produce occasional 5xx/drop/latency that would exercise connector retry/circuit-breaker (asserted via rate over N trials).

**DoD**: knobs work, defaults exercise retry paths, disabled = clean.

---

### TASK-S2.7 — MQTT Sparkplug B simulator  *(Phase 2)*

**Objective**: real broker + publisher emitting Sparkplug B driven by the fixture; authoritative source for TRS alias ingestion.

**Build**
- `compose.yaml` — Mosquitto (or EMQX) broker.
- `sparkplug.py` — protobuf BIRTH/DATA encode/decode helpers (Sparkplug B payload schema).
- `publisher.py` — on connect: NBIRTH/DBIRTH declaring tag metadata + **aliases** for fixture signals; then DATA at ~1 Hz with monotonically increasing `seq`, values from the scenario expander. Realism: drops, clock skew via S2.8.

**Test strategy**: broker boots, publisher connects; a subscribing client decodes Sparkplug B, resolves aliases from BIRTH, reads values tracking the active scenario; `seq` is monotonic; drop knob removes messages.

**DoD**: UNS connector subscribes and TRS can ingest aliases from BIRTH (verified for now via a test subscriber, since the connector doesn't exist yet).

---

### TASK-S2.5 — OPC UA simulator  *(Phase 2)*

**Objective**: real `asyncua` server mirroring the plant hierarchy, 1 Hz live values; the real-time trigger source (not historical evidence — that's PI).

**Build**
- `address_space.py` — build OPC UA nodes from the fixture plant/asset/signal hierarchy; deterministic NodeId/browse-path ↔ fixture-signal mapping.
- `server.py` — asyncua server on `opc.tcp://localhost:4840`; 1 Hz updater driving current values from the scenario expander. Realism: skew + occasional bad quality via S2.8.

**Test strategy**: client browses hierarchy, subscribes, reads ~1 Hz updates; active scenario reflected in real time; node→signal mapping stable.

**DoD**: OPC UA connector subscribes and reads current values (verified via a test client now).

---

### TASK-S2.6 — SharePoint / S3 document simulator  *(Phase 3)*

**Objective**: serve fixture documents (datasheets, P&IDs, prior RCA reports, operator narratives) via SharePoint Search + Graph drive-item endpoints, with an optional MinIO S3 variant.

**Build**
- `app.py` — FastAPI Search + Graph drive-item routes.
- `search_index.py` — local BM25 + embedding index over fixture docs.
- `s3_variant.py` — MinIO seeding + GetObject/ListObjectsV2.
- Fixture docs under `documents/{datasheets,pids,rca_reports}/` — metadata + PDF bytes, some with injected OCR noise. Documents must be scenario-matched (e.g. a "mechanical seal" doc for seal_leak).

**Test strategy**: scenario-relevant query returns matching seeded docs ranked sensibly; drive-item/GetObject returns correct bytes; OCR noise present on some PDFs; latency/error knobs apply.

**DoD**: documents connector returns relevant docs for scenario queries (verified via direct HTTP/S3 calls now).

---

### TASK-S2.2 — PI Historian simulator  *(Phase 3, highest surface area)*

**Objective**: PI Web API REST subset the PI connector calls, synthesizing series on demand.

**Build**
- `webid.py` — WebID encode/decode mapping to fixture signals.
- `synthesize.py` — series synthesis (baseline + diurnal + noise + scenario anomalies) + **`mode` semantics**:
  - `stored` — only points crossing compression deviation since last stored point.
  - `interpolated` — interpolated values, each flagged `is_interpolated`.
  - `aggregated` — true aggregates over requested intervals.
- `app.py` — FastAPI routes: `/streams/{webId}/recorded`, `/interpolated`, `/summary`, `/eventframes`. Realism defaults: skew ±2s, 1% dropped intervals, 0.5% bad-quality.

**Test strategy**: all 4 endpoints serve; recorded/interpolated/aggregated return materially different, mode-correct responses for the same WebID+range; each scenario's affected signals show expected anomaly shape at expected offsets; WebIDs round-trip to fixture signals; realism flags present and configurable.

**DoD**: PI connector reads successfully (verified via direct HTTP for now); 4 scenarios produce expected anomalies.

---

### TASK-S2.3 — Maximo simulator  *(Phase 4)*

**Objective**: Maximo OSLC REST subset with idempotent write-back, seeded WO/SR/failrep history matching scenario timelines.

**Build**
- `oslc.py` — `oslc.where`/`oslc.select` parsing, paging, OSLC response shaping.
- `seed.py` — scenario events → WO/SR/failrep history (e.g. seal-leak P-101A → WO-50012345 @ day18, WO-50012402 @ day28).
- `app.py` — FastAPI routes `/maxrest/oslc/os/{mxwo,mxsr,mxfailrep}` + idempotent write-back. Local-time-without-TZ timestamps; ≥1 legacy non-ISO-14224 failure code. Realism: occasional 5xx.

**Test strategy**: query WOs for affected asset returns scenario history at correct times; timestamps local-without-TZ; legacy code present; write-back idempotent (replay doesn't duplicate); 5xx configurable.

**DoD**: Maximo connector reads WOs and writes back (verified via direct HTTP now).

---

### TASK-S2.4 — SAP PM simulator  *(Phase 4)*

**Objective**: SAP OData v2 notification service with the full CSRF dance, modeling shared assets with *different field names/codes* than Maximo to exercise connector dedup/normalization.

**Build**
- `odata.py` — `$metadata`, `$filter`/`$expand`/`$select` parsing, entity serialization with SAP namespace prefixes.
- `seed.py` — scenario → notifications using SAP field naming for the subset of plant on SAP PM (overlapping some Maximo assets).
- `app.py` — FastAPI routes `/sap/opu/odata/sap/PM_NOTIFICATION_SRV` + `X-CSRF-Token: Fetch` handshake before writes.

**Test strategy**: `$metadata` + notification entity set served; write without valid fetched CSRF rejected, fetch-then-write succeeds; `$filter`/`$expand` return correctly shaped OData v2 with namespaces; shared-asset event appears under SAP's different field names.

**DoD**: SAP PM connector reads notifications; Maximo overlap correctly modeled.

## 5. Verification strategy (interim, pre-connectors)

Every task's DoD references an EPIC-013 connector that doesn't exist yet. Until then, verification = **(a)** the simulator's own pytest suite, plus **(b)** a protocol-level smoke test that proves scenario data is coherent and correctly shaped:

- MQTT: `mosquitto_sub -t 'spBv1.0/#'` shows BIRTH then DATA; decode + alias-resolve in a test subscriber.
- OPC UA: a test `asyncua` client browses + subscribes + reads 1 Hz values.
- PI/Maximo/SAP/Docs: `httpx` calls against the running FastAPI app asserting mode/shape/content.
- **Cross-source coherence test** (SPEC-014 test plan #3): for `seal_leak_progression`, assert PI series anomaly offsets, the Maximo WO timestamps, and alarm events all align on `t0 + offset`. This is the single most valuable integration test and should exist as soon as S2.1 + S2.2 + S2.3 land.

## 6. Risks & watch-items

1. **S2.1 is the schedule risk** — everything depends on it and on getting the fixture data internally consistent. Budget extra time; land the validator + cross-coherence test before building HTTP sims.
2. **Determinism leaks** — any use of wall-clock time or unseeded RNG in synthesis breaks reproducibility. Centralize all randomness/time behind the expander + S2.8.
3. **Source-protocol fidelity** — PI `mode` semantics, OSLC query grammar, OData CSRF + `$metadata`, Sparkplug B `seq`/aliases are each fiddly. These are exactly where "production parity" bugs hide (ADR-0008 negative consequence). Lean on real client libraries to validate (asyncua client, an MQTT client, OData/OSLC sample requests).
4. **Don't leak product code in** — easy to accidentally `import packages.contracts` for a model. Keep simulators pure-fixture.

## 7. Open questions to resolve before/with Phase 1

1. **Project/package structure** — deferred to Step 1 (per your instruction). Paths above are provisional (flat TASKS layout).
2. **Fixtures location** — repo-root `/fixtures/refplant/` (SPEC-014 + Week-1 compose mounts) vs under `packages/simulators/`. Deferred with structure.
3. **Template coupling for validator rule #3** — the validator must check signal roles against the centrifugal_pump template (SPEC-015) *without importing `packages/templates`*. Proposal: snapshot the template's `signal_roles` as fixture data the validator reads. Confirm approach.
4. **ISO 14224 code discrepancy** — SPEC-014 seal-leak example uses `LEK`; SPEC-008 uses `ELP`; SPEC-015 failure mode `mechanical_seal_failure` uses `LEK`. Need one canonical mapping in the fixtures.
5. **QUDT validation source** — do we hardcode the small allowlist of units the pump template uses, or pull a QUDT symbol set? MVP-pragmatic: allowlist now.
6. **Scenario richness** — SPEC-008 lists `seal_flush_pressure`/`seal_flush_flow` and spectral signatures (1×RPM peaks) that the simple baseline+trajectory model can't fully express. Decide how much spectral/derived realism is in-scope for MVP vs faked as scalar trends.
```
