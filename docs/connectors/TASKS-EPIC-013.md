# EPIC-013 — Executable Task Breakdown (Connectors)

One task per story. Each task is a self-contained unit of work for Claude Code.
Reference docs: [EPIC-013](EPIC-013-connectors.md), [SPEC-002](SPEC-002-mcp-tool-contracts.md),
[ADR-0012](../adrs/0012-connectors-own-the-contract.md), [ADR-0005](../adrs/0005-mcp-as-tool-protocol.md),
[ADR-0010](../adrs/0010-provenance-and-audit.md), [ADR-0002](../adrs/0002-units-of-measure.md),
[ADR-0006](../adrs/0006-time-handling.md).

Stack: Python 3.12, **product** uv workspace at the repo root (`members = ["packages/*"]`).
Connectors are **shipped product code** and live under `packages/connectors/<name>/` (src layout,
`rca_connector_<name>`). They import `rca_connector_sdk` + `rca_contracts` and **must not import
`rca_simulator`** (ADR-0012). Pydantic v2 strict/frozen/extra-forbid. TDD (red → green → verify);
hermetic tests drive simulators in-process via `httpx.ASGITransport` / in-memory FastMCP `Client`,
with an optional live smoke against `task up:<sim>`.

**Status legend:** ✅ done · 🟡 in progress · ⬜ not started

Dependency order: **S13.1 blocks S13.2–S13.7.** S13.8 (contract tests) and S13.9 (credential broker)
layer on top. Each connector also needs its matching EPIC-002 simulator (already built) reachable.

---

## Cross-cutting design decisions still open

These surfaced building S13.1 and must be settled at the start of the tasks that hit them:

1. **signal_id → source identifier (TRS alias seam)** — ✅ **RESOLVED (S13.2):** the `SignalResolver`
   port now returns a `SourceBinding(handle, raw_unit)` per `(signal_id, source)` — the source-side
   handle (PI WebID / OPC UA NodeId / Maximo location / SAP EQUNR) *and* the unit the source emits.
   In-memory default for dev; real TRS owns this later. **Used by S13.2; applies to S13.4, S13.5, S13.7.**
2. **Mutating-tool shape** — ✅ **RESOLVED (S13.3):** no new construct needed. The generalized
   orchestrator already does fetch→translate→provenance→envelope; a write tool's `fetch` does the POST
   and `translate` returns the result. Added a `mutating=True` marker on `@evidence_tool` (for
   safety/tier-gating). Idempotency is anchored on `wonum` (sim/server upserts); real Maximo would add
   an `idempotency_key` header.
3. **Streaming connector shape** — ✅ **RESOLVED (S13.5/S13.7):** background-ingest + request/response
   read tools. The SDK gained streaming primitives (`subscription.py`: `RingBuffer`, `SubscriptionState`,
   `run_with_reconnect`) + an `EventSink` port for alias candidates. A streaming connector runs a
   long-lived subscription in the background (asyncua for OPC UA; paho for MQTT — both reconnect) that
   fills `SubscriptionState`; its MCP tools are request/response reads over that cache. OPC UA's
   read-tool is on-demand via `@evidence_tool`; MQTT's two read-tools are hand-wired on FastMCP (they
   read shared cache state the orchestrator can't inject) but keep provenance + the `ToolResponse[T]`
   envelope. **Used by S13.5, S13.7.**
4. **Real TRS / MAR / credential-broker** — currently stood in by SDK `Protocol` ports with in-memory
   defaults. Connectors keep using the ports until EPIC-003/012 + the broker land. **Affects S13.9.**

---

## TASK-S13.1 — connector_sdk common platform + echo connector ✅ DONE

**Description**
Stand up the product uv workspace and build the shared platform every connector imports, proven by a
toy echo connector against a toy echo source. Hybrid shape: composable helpers (units/time/retry/
errors/provenance) + a thin `@evidence_tool` orchestrator that runs the full request/response
pipeline (resolve → credentials → fetch[retry] → translate → normalize units/time → validate →
require+attach Provenance → cost → map errors to `ToolError`) and is **hard-fail by construction** —
a success result is impossible without provenance + a valid payload. Every return is a generic
`ToolResponse[T]` (data+provenance XOR error). External services (TRS/MAR/vault/cost) are `Protocol`
**ports** with in-memory/static defaults so connectors build before those services exist.

**Files (created)**
- `pyproject.toml` (root product workspace, `members = ["packages/*"]`; shared ruff/mypy/pytest), `.python-version`
- `packages/contracts/` — `rca_contracts` **echo-path subset**: `_ids`, `enums`, `time_basis`,
  `signal`, `measurement`, `provenance`, `tool_error`, `tool_response` (`ToolResponse[T]`)
- `packages/connector_sdk/src/rca_connector_sdk/` — `ports`, `context`, `provenance`, `units`,
  `timeutil`, `retry`, `errors`, `orchestrator`, `mcp` (FastMCP skeleton)
- `packages/connectors/echo/` — `echo_source.py`, `connector.py`, `server.py` + the DoD test

**Expected behaviour / DoD — met**
Echo connector passes a ~50-line example test through the real FastMCP in-memory `Client`: success
returns `ToolResponse[MeasurementSeries]` with provenance + SI-normalized values + UTC timestamps; a
source 5xx returns `ToolError(source_unavailable)` with no data. 33 product tests + mypy + ruff green;
`rca_simulator` (132 tests) unaffected in its own venv.

**Deviations from plan (intentional):** built only the **echo-path subset** of contracts (full
`packages/contracts` is an EPIC-001 task, deferred); time module named `timeutil.py`; FastMCP 3.x.

---

## TASK-S13.2 — PI connector (`pi-connector`) 🟡 (all 3 tools done; real-sim parity → S13.8)

**Description**
First real connector and the request/response reference. MCP tools `pi.get_series`,
`pi.get_summary`, `pi.get_event_frames`, translating to the PI Web API REST subset the EPIC-002 PI
simulator exposes. Resolve `signal_id` → PI WebID via the resolver `SourceBinding` (decision #1),
honor `mode` semantics, and normalize raw PI engineering units → canonical SI. Built on `@evidence_tool`.

**Done (✅):**
- `pi.get_series` (`stored`→`recorded`, `interpolated`→`interpolated`, `is_interpolated` surfaced).
- `pi.get_summary` (aggregated `MeasurementSeries`; canonical `aggregation_method`/`aggregation_interval`).
- `pi.get_event_frames` (returns `ToolResponse[list[Alarm]]`).
- SDK refinements landed here: **gauge-pressure handling** (psig→Pa keeping `pressure_reference=gauge`;
  refuse only gauge→absolute); **`SourceBinding`** resolver (per-signal source handle + raw unit);
  and the **orchestrator generalization** — `@evidence_tool` `translate()` now returns the canonical
  response model (any `T`), with series built via the new `build_measurement_series` helper. This
  unblocks all non-series connectors (Maximo/SAP/Documents). New contract: `Alarm`.

**Parity (✅):** `test_pi_parity.py` runs the connector against the **real** EPIC-002 PI sim over HTTP
(`task parity:pi` starts/stops it); product venv never imports the sim. **Remaining (deferred
enhancement):** AF attribute traversal + pagination.

**Files (created)**
- `packages/connectors/pi/pyproject.toml`
- `packages/connectors/pi/src/rca_connector_pi/{__init__,connector,server}.py`
- `packages/connectors/pi/tests/test_pi_connector.py`
- (SDK) `packages/connector_sdk/src/rca_connector_sdk/series.py`; (contracts) `alarm.py`

**Expected behaviour / DoD**
Full DoD (runs identically against EPIC-002 PI sim + OSIsoft demo image) lands when parity is wired in
S13.8. **Met so far:** all three tools return correct `ToolResponse[...]` through the MCP boundary;
psig→Pa(gauge) verified; aggregated + event-frame shapes verified; source 5xx → `ToolError` with no
data; provenance carries the PI query + raw tag. Hermetic in-test PI fake; 37 product tests + mypy + ruff green.

---

## TASK-S13.3 — Maximo connector (`maximo-connector`) ✅

**Description**
MCP tools `maximo.get_workorders`, `maximo.get_failure_history`, `maximo.preview_writeback`,
`maximo.commit_writeback`, translating Maximo OSLC REST → canonical `WorkOrder`. Asset-scoped;
parses local-time-without-TZ timestamps → UTC (configured `source_timezone=America/Chicago`); legacy +
ISO-14224 failure codes pass through; idempotent commit (decision #2).

**Done (✅):** all 4 tools. Reused the generalized orchestrator for the write path; added the
`mutating=True` marker. `preview_writeback` performs no source call; `commit_writeback` POSTs to `mxwo`
and is idempotent by `wonum` (replays don't duplicate). Hermetic test + **real-sim parity**
(`task parity:maximo`) — both verify idempotent write-back — green.

**Files (created)**
- `packages/connectors/maximo/pyproject.toml`
- `packages/connectors/maximo/src/rca_connector_maximo/{__init__,connector,server}.py`
- `packages/connectors/maximo/tests/{test_maximo_connector,test_maximo_parity}.py`

**Expected behaviour / DoD — met**
Round-trip write-back against the EPIC-002 Maximo sim; commit replays return the prior result and never
duplicate. Read tools return canonical `WorkOrder` records (UTC, provenance, legacy code surfaced).
**Note:** Maxauth/cookie handling deferred (sim needs none); add when wiring a real Maximo + S13.9.

---

## TASK-S13.4 — SAP PM connector (`sap-pm-connector`) ✅ (read path + parity)

**Description**
MCP tool `sap_pm.get_notifications`, translating SAP OData v2 notifications → canonical `WorkOrder`.
Parses the OData v2 envelope (`d.results`), resolves `asset_id` → EQUNR via the resolver `SourceBinding`,
and normalizes SAP field names + the FECOD code scheme → ISO 14224 (`0010`→`LEK`, …).

**Done (✅):** `sap_pm.get_notifications` (read-only — reads need no CSRF). New `WorkOrder` contract.
SDK refinement landed here: the orchestrator is now **asset-scoped capable** — it resolves the source
binding from `signal_id` *or* `asset_id` and only resolves a `SignalDescriptor` when a signal is
present (`ctx.signal` is now optional). Hermetic test + **real-sim parity** (`task parity:sap`) green.

**Files (created)**
- `packages/connectors/sap_pm/pyproject.toml`
- `packages/connectors/sap_pm/src/rca_connector_sap_pm/{__init__,connector,server}.py`
- `packages/connectors/sap_pm/tests/{test_sap_pm_connector,test_sap_pm_parity}.py`
- (contracts) `work_order.py`

**Expected behaviour / DoD**
**Met:** notifications normalize to `WorkOrder` (source_system `sap_pm`, UTC `opened_at`, FECOD→ISO),
provenance carries the EQUNR; verified hermetically and against the real SAP sim. **Pending:** the
cross-source "contracts match Maximo for overlap assets" comparison — lands when the Maximo connector
(S13.3) exists. **Out of scope here:** CSRF write-back (only needed if/when SAP write tools are added).

---

## TASK-S13.5 — OPC UA connector (`opc-ua-connector`) ✅

**Description**
MCP tool `opc_ua.get_current_values` (request/response) + a long-lived background `OpcUaSubscription`
(streaming shape, decision #3). Uses an `asyncua` client against the EPIC-002 OPC UA server; maps
NodeId ↔ canonical `SignalID` via the resolver `SourceBinding` (decision #1).

**Done (✅):** `opc_ua.get_current_values` (on-demand asyncua read → `ToolResponse[Measurement]`,
psig→Pa gauge, retryable `SourceUnavailable` on read failure). Background `OpcUaSubscription` built on
the SDK streaming primitives (`run_with_reconnect` + asyncua data-change → `SubscriptionState` cache),
emits raw-tag alias candidates via `EventSink`. Added `ToolConfig.extra` for connector-specific config
(namespace_uri). Mapping extracted to module-level `to_measurement()` (unit-testable). Hermetic test
(mapping) + **real-sim parity** (`task parity:opcua`: on-demand read + live subscription cache) green.
Adversarial review (wrc567dh5) triaged: subscription `try/finally` cleanup, reconnect-loop logging,
event-sink emits raw tag only (no value).

**Files (created)**
- `packages/connectors/opc_ua/pyproject.toml`
- `packages/connectors/opc_ua/src/rca_connector_opc_ua/{__init__,connector,subscription,server}.py`
- `packages/connectors/opc_ua/tests/{test_opcua_connector,test_opcua_parity}.py`

**Expected behaviour / DoD — met**
Current-value reads match the simulator (SI-normalized, provenance, UTC); the background subscription
fills the cache live and reconnects via `run_with_reconnect`. **Note:** full docker-restart-mid-test
left to nightly/manual; reconnect logic covered by SDK unit tests + the live-subscription parity.

---

## TASK-S13.6 — Documents connector (`documents-connector`) ✅ (HTTP backend; S3 follow-up)

**Description**
MCP tools `documents.search`, `documents.fetch` behind a single contract. Query/document-scoped (no
signal/asset). Translate hits to canonical `DocumentRef` with provenance; preserve OCR-noisy bytes on fetch.

**Done (✅):** both tools against the SharePoint/HTTP backend (matches the docs sim). SDK refinement
landed here: the orchestrator's **source-binding resolution is now optional** (`ctx.source` can be None)
for query-scoped tools. Unified `doc_type` (source docType → id-prefix → other) across search+fetch;
defensive guards (skip malformed search hits, `MalformedResponse` on fetch missing meta/id, skip null
hits); `excerpt` = first 1000 chars or None; `raw_tags=[]` for search. New `DocumentRef` (+ `DocType`)
contract. Hermetic test + **real-sim parity** (`task parity:documents`) green. Adversarial review
(waa1175wu) triaged — 9 fixes folded in.

**Files (created)**
- `packages/connectors/documents/pyproject.toml`
- `packages/connectors/documents/src/rca_connector_documents/{__init__,connector,server}.py`
- `packages/connectors/documents/tests/{test_documents_connector,test_documents_parity}.py`
- (contracts) `document.py`

**Expected behaviour / DoD — met (HTTP backend)**
Same MCP query against the EPIC-002 documents sim returns canonical `DocumentRef` top-N; `fetch` returns
the excerpt/bytes. **Remaining follow-up:** the S3/MinIO backend variant behind the same contract.

---

## TASK-S13.7 — UNS / MQTT connector (`mqtt-connector`) ✅

**Description**
MCP tools `uns.browse_namespace`, `uns.get_recent_messages`. A long-lived paho MQTT client subscribed
to the EPIC-002 broker's Sparkplug B namespace (**streaming shape**, decision #3). Decode Sparkplug B,
parse BIRTH metadata, and **emit alias-candidate events** (via `EventSink`, the TRS seam). Reconnect
after a broker bounce.

**Done (✅):** Connector-local Sparkplug B codec (`sparkplug.py`, Tahu wire format — product code can't
import `rca_simulator`, so the connector owns its protobuf). `UnsService` (paho v2 background subscriber)
with a **pure `handle_message(topic, bytes)`** that fills `SubscriptionState`: (N|D)BIRTH learns
name↔alias + emits raw-tag alias candidates; alias-only DDATA resolves to names → `current_values` +
`recent` ring buffer. paho auto-reconnect + retained BIRTH cover broker-bounce recovery. The two read
tools are **hand-wired on FastMCP** (they read shared cache state the orchestrator can't inject) but
keep hard-fail provenance + the `ToolResponse[T]` envelope. Connector-local response models
(`NamespaceTree`/`RecentMessages`). Hermetic tests (5) + **real-broker parity** (`task parity:mqtt`)
green. Adversarial review (wp05p1vlo) running.

**Files (created)**
- `packages/connectors/mqtt/pyproject.toml`
- `packages/connectors/mqtt/src/rca_connector_mqtt/{__init__,sparkplug,uns_service,models,server}.py`
- `packages/connectors/mqtt/tests/{test_mqtt_connector,test_mqtt_parity}.py`

**Expected behaviour / DoD — met**
The connector decodes the live Sparkplug B stream into a canonical namespace tree + recent messages;
alias candidates surface via `EventSink`; paho reconnects after a broker bounce. **Note:** single
group/node assumed (matches the reference-plant edge).

---

## TASK-S13.8 — Connector contract / parity tests 🟡 (PI parity done)

**Sim-access decision — ✅ RESOLVED (live HTTP over localhost):** parity tests drive the **real**
EPIC-002 simulators **over HTTP**, never importing/installing them into the product venv (honors the
"simulator is separate" boundary, ADR-0012). Each connector gets a `test_<name>_parity.py` that skips
when its sim isn't reachable (so plain `uv run pytest` stays green) plus a `task parity:<name>` target
(in the root `Taskfile.yaml`) that starts the sim (its own docker/venv), runs the test, and tears down.

**Done (✅):**
- PI — `test_pi_parity.py` + `task parity:pi` (UTC, provenance, psig→Pa; stored/interpolated differ).
- SAP PM — `test_sap_pm_parity.py` + `task parity:sap` (OData v2 → canonical `WorkOrder`, FECOD→ISO).
- Maximo — `test_maximo_parity.py` + `task parity:maximo` (OSLC reads + idempotent write-back).
- Documents — `test_documents_parity.py` + `task parity:documents` (search/fetch → `DocumentRef`).
- OPC UA — `test_opcua_parity.py` + `task parity:opcua` (asyncua read + live subscription cache).
- MQTT/UNS — `test_mqtt_parity.py` + `task parity:mqtt` (live Sparkplug B → namespace tree + recent).

**Remaining:** a unified `task parity:all` + the broader matrix (validate all responses vs contracts,
`ToolError` shapes, latency budgets), realism-harness fault injection, and the nightly
`(connector × real_source)` run where licensed.

**Files**
- `packages/connectors/<name>/tests/test_<name>_parity.py`; root `Taskfile.yaml` (`parity:<name>`)

**Expected behaviour / DoD**
Green CI on every PR (parity skips when sims are down; `task parity:*` runs them green); nightly
real-source matrix against vendor demo images where licensed.

---

## TASK-S13.9 — Credential broker integration ⬜

**Description**
Replace the SDK's `StaticCredentialBroker` default with a real broker client: connectors read
`endpoint_url` + `credential_ref` from a `connector_config` table and fetch secrets from a vault per
call (no in-memory caching > 5 min), never logging secrets. Wired by the onboarding workflow
([SPEC-013](../foundations/SPEC-013-tenant-onboarding.md) Stage 1).

**Files modified**
- `packages/connector_sdk/src/rca_connector_sdk/credentials.py` (real `CredentialBroker` impl)
- `infra/postgres/` migration for `connector_config`
- `packages/connector_sdk/tests/test_credentials.py`

**Expected behaviour / DoD**
Rotating a credential in the vault is picked up on the next call without restarting the connector.

---

## Suggested build order (single engineer)

1. ✅ **S13.1** SDK + echo (done).
2. ✅ **S13.2 PI** — all 3 tools + real-sim parity done (decision #1 resolved; gauge units + orchestrator generalized). Deferred enhancement: AF traversal/pagination.
3. ✅ **S13.4 SAP PM** (read path + parity) · ✅ **S13.3 Maximo** (read + idempotent write-back + parity; mutating-tool shape resolved).
4. **S13.6 Documents** — two backends behind one contract.
5. **S13.5 OPC UA** + **S13.7 MQTT** — together, once the streaming shape (decision #3) is designed.
6. **S13.9 Credential broker** + finalize **S13.8** matrix as services (TRS/MAR/vault) land.

## Out of scope (post-MVP, per EPIC-013)
Customer-specific connector forks; vibration-spectra connector; DCS SOE connector.
