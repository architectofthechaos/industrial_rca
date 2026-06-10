# SPEC-002: MCP Tool Contracts

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0005](../adrs/0005-mcp-as-tool-protocol.md), [0001](../adrs/0001-tag-resolution-service.md), [0006](../adrs/0006-time-handling.md), [0012](../adrs/0012-connectors-own-the-contract.md)

## Purpose

Defines every MCP tool the agent can call, organized by tier. This spec is the contract — Pydantic models in `packages/contracts` are the implementation, and any change here requires updating both.

## Who owns these tools

Per [ADR-0012](../adrs/0012-connectors-own-the-contract.md), every MCP tool listed below is implemented by a **connector** (product code). Connectors translate MCP calls into source-specific protocols (PI Web API, OSLC, OData, OPC UA, MQTT, SharePoint REST). In dev/CI the source behind a connector is a [simulator](SPEC-007-simulator-behavior.md); in production it is the customer's real system. **The MCP contract is invariant across that swap.**

Connector → tool mapping:

| Connector | MCP tool prefix | Source protocol |
|---|---|---|
| `pi-connector` | `pi.*` | PI Web API REST |
| `maximo-connector` | `maximo.*` | Maximo OSLC REST |
| `sap-pm-connector` | `sap_pm.*` | SAP OData v2 |
| `opc-ua-connector` | `opc_ua.*` | OPC UA binary |
| `mqtt-uns-connector` | `uns.*` | MQTT + Sparkplug B |
| `documents-connector` | `documents.*` | SharePoint Graph / S3 |
| `trs-service` (internal) | `trs.*` | internal Postgres |
| `mar-service` (internal) | `assets.*`, `kg.*` | internal Postgres + Neo4j |
| `templates-service` (internal) | `templates.*`, `template.*` | internal repo |
| `probe-service` (internal) | `probe.*`, `causemap.*`, `evidence.*`, `corpus.*`, `overlay.*`, `cmms.*` | internal Postgres + Temporal |

## Tool naming convention

`<server>.<verb>_<noun>` — e.g., `pi.get_series`, `maximo.get_workorders`, `trs.resolve_tag`.

## Global rules (every tool)

1. **Inputs and outputs are Pydantic models.** No untyped dicts.
2. **Outputs always carry a `Provenance` block** (embedded or appended).
3. **No raw tag strings as inputs.** Use `SignalID` (UUID) from TRS, except for TRS resolution tools themselves.
4. **All timestamps are UTC ISO 8601 with tzinfo.** Pydantic validators enforce.
5. **Read-only by default.** Mutating tools (CMMS write-back) are explicitly marked `mutates: true` in metadata and require an HITL gate before invocation.
6. **Rate-limited and budget-aware.** Every call records cost (LLM tokens, API quotas) against the probe's budget. Tools that would exceed the budget return a `budget_exceeded` error.
7. **Idempotency keys on mutating calls.** `mutating_tool(idempotency_key=<probe_id+step>)`.

## Tier 1 — Scope

| Tool | Purpose |
|---|---|
| `trs.resolve_tag` | Resolve a raw tag string (with optional asset/time hints) to a SignalID + confidence + source. |
| `trs.search_signals` | Find Signal IDs by asset + role (e.g., all "discharge_pressure" signals on P-101A). |
| `trs.get_signal` | Fetch full SignalDescriptor for a SignalID. |
| `assets.resolve` | Map a source-system external identifier (Maximo functional location, PI AF element, UNS path segment, work-order-id, alarm-id) to a canonical `AssetID`. See [SPEC-011](SPEC-011-master-asset-registry.md). |
| `assets.get` | Fetch full `AssetDescriptor` for an asset_id, including parent chain. |
| `assets.search` | Find assets by class, tag pattern, parent, criticality, or service. |
| `assets.get_hierarchy` | *(removed Sprint 1 — hierarchy moves to the KG in Sprint 2)* Walk asset hierarchy up/down/both with depth limit. |
| `assets.classify_iso14224` | Determine ISO 14224 class for an asset. For already-classified assets reads the field; for unclassified runs a heuristic against nameplate + name + parent context. |
| `kg.get_neighborhood` | Build local taxonomy fragment around an asset (parent system, child components, peer equipment). |
| `templates.load` | Load the equipment-class template version pinned to this probe. |
| `probe.set_time_window` | Compute and persist the probe TimeWindow given trigger time + template defaults. |

## Tier 2 — Evidence

| Tool | Purpose |
|---|---|
| `pi.get_series` | Get historian series for signals. Requires `mode` (stored / interpolated / aggregated). |
| `pi.get_event_frames` | Get PI event frames intersecting the window. |
| `pi.get_summary` | Statistical summary (min/max/avg/p95/stddev) per signal. |
| `dcs.get_soe` | Sequence-of-events records from DCS, ms-precision, single-clock. |
| `alarms.get_history` | Alarm activations / clears / acks in the window. |
| `maximo.get_workorders` | Work orders for an asset, with status / dates / failure codes. |
| `maximo.get_failure_history` | ISO 14224-coded failure history for the asset. |
| `sap_pm.get_notifications` | SAP PM notifications and follow-up actions. |
| `documents.search` | Semantic + keyword search over SharePoint/S3 docs scoped to asset and class. |
| `documents.fetch` | Retrieve a specific document with extracted excerpt around relevant sections. |
| `vibration.get_spectra` | Spectral data from vibration monitoring (if available). |
| `lab.get_results` | Oil analysis, sample lab results. |

All evidence tools return data that conforms to [SPEC-001 EvidenceBundle](SPEC-001-evidence-bundle.md) components.

## Tier 3 — Reason

| Tool | Purpose |
|---|---|
| `template.get_failure_modes` | Return failure modes for the loaded template with priors and evidence recipes. |
| `evidence.score_failure_mode` | Given an evidence bundle and a failure mode, compute a likelihood score using the template's recipe. |
| `causemap.create_node` | Add a node to the cause map (failure mode, mechanism, cause, contributing factor). |
| `causemap.create_edge` | Link cause map nodes with relationship type. |
| `causemap.attach_evidence` | Bind specific Measurement / WorkOrder / Alarm IDs to a cause map node as supporting/refuting evidence. |
| `kg.traverse_neighborhood` | When initial evidence is inconclusive, expand the search to upstream/downstream/peer assets. |
| `template.get_method_template` | Get the methodology scaffold (5-whys, fishbone, FTA, PROACT) for cause map construction. |

## Tier 4 — Govern

| Tool | Purpose | Mutates |
|---|---|---|
| `probe.submit_for_review` | Mark probe ready for reliability engineer review; emits HITL signal. | No |
| `probe.record_review_decision` | Record reviewer's approval / edits / rejection. | Yes |
| `cmms.preview_writeback` | Construct (but do not send) the CMMS notification payload. | No |
| `cmms.commit_writeback` | Send the approved notification to CMMS. Requires prior HITL approval. | Yes |
| `corpus.index_probe` | Add closed probe to corpus index for future retrieval. | Yes |
| `overlay.propose_update` | Propose a learned-overlay update from this probe (priors, thresholds). | No |
| `overlay.commit_update` | Apply approved overlay updates. Auto-applies for stat-only (n≥30); structural changes require human approval. | Yes |

## Error model

```python
class ToolError(BaseModel):
    code: Literal[
        "not_found",
        "ambiguous_input",
        "unresolved_signal",
        "unit_conversion_ambiguous",
        "source_unavailable",
        "rate_limited",
        "budget_exceeded",
        "permission_denied",
        "validation_failed",
        "timeout",
        "internal_error",
    ]
    message: str
    retryable: bool
    details: dict | None = None
```

Tools return `ToolError` rather than raising; the agent reasons over errors as part of its loop.

## Versioning

Each tool has a `version` string in metadata (semver). Breaking changes bump major. Workflows pin tool versions per tier.

## Catalogs per tier — enforcement

Agent tier graphs receive only their tier's tool catalog via the MCP server URL list. The Scope-tier agent cannot call evidence tools by construction.

## Connector responsibilities (vs simulator)

A connector is **not a passthrough**. Connectors own:

1. **Authentication / credentials** — OAuth, Kerberos, API keys, certificates. Simulators accept tokens but do not validate; real sources do.
2. **Pagination and stitching** — source APIs return chunks; connectors return canonical bundles.
3. **Unit normalization** — raw source units → QUDT canonical (see [ADR-0002](../adrs/0002-units-of-measure.md)).
4. **Timestamp normalization** — source-local time → UTC ISO 8601 (see [ADR-0006](../adrs/0006-time-handling.md)).
5. **Provenance** — every response stamped with `source_system`, `endpoint`, `query_time`, `latency_ms`, `request_id` (see [ADR-0010](../adrs/0010-provenance-and-audit.md)).
6. **Retry / circuit breaker** — transient errors retried with jitter; persistent failures open the breaker.
7. **Budget accounting** — emit cost metrics (rows, bytes, API quota units) per call.
8. **Schema validation** — every outbound MCP response validated against the Pydantic model in `packages/contracts`.

Simulators provide the source-side bytes; connectors provide everything above.
