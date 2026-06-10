# Pitfalls and how we resolve them

This document lists the production-failure modes we identified before building. Each is mapped to the ADR or spec where it is resolved. If you propose a change that weakens a resolution here, escalate to a new ADR.

## 0. Asset aliasing — the same physical asset has many identifiers

**Failure mode**: Each connector invents its own asset UUID, KG drifts from connectors, asset rename/replacement has no home. Agent reasons about "different pumps" that are actually the same one.

**Resolution**: [ADR-0011 MAR](adrs/0011-master-asset-registry.md). Canonical Asset IDs (UUIDv7) per physical asset. All source-system identifiers (Maximo functional location, SAP equipment, PI AF element, UNS path, DCS ID) live as time-bounded aliases. MAR is populated before TRS during onboarding. The KG roots its nodes on `asset_id`. [See explainer](mar/how-mar-works.md).

## 1. Tag aliasing — the same physical sensor has many names

**Failure mode**: Agent treats aliases as distinct signals, confuses rebuilt-asset histories, cross-contaminates between sites.

**Resolution**: [ADR-0001 TRS](adrs/0001-tag-resolution-service.md). Canonical Signal IDs (UUIDv7) per physical sensor. No tool accepts raw tag strings except TRS resolution tools. No raw tags reach LLM prompts — only canonical `SignalDescriptor` objects. Alias mappings are time-bounded (`valid_from` / `valid_to`). [See explainer](trs/how-trs-works.md).

## 2. Units of measure — inconsistent, gauge vs absolute

**Failure mode**: Pressure threshold "20 bar" means very different things if one feed is barg and another bara. Free-text unit strings get mis-parsed.

**Resolution**: [ADR-0002 Units](adrs/0002-units-of-measure.md). QUDT URIs per signal. All values canonical SI internally. `pressure_reference` is a first-class field. Unit conversions refuse ambiguity rather than guess.

## 3. Time skew, timezones, and interpolation

**Failure mode**: Cross-source joins mis-align by seconds to minutes. PI interpolation invents values that were never measured. Naive datetimes silently use wrong timezone.

**Resolution**: [ADR-0006 Time](adrs/0006-time-handling.md). UTC ISO 8601 with tzinfo enforced. Every evidence bundle carries a `time_basis` block. Historian tools force explicit `mode` (stored/interpolated/aggregated). Sequence-of-events analysis uses DCS SOE recorders, not historian.

## 4. Workflow durability — long-running probes survive infra restarts

**Failure mode**: Probes lose state on deploys, crashes, or HITL waits beyond process lifetime. Retries are inconsistent. Workflow logic changes break in-flight probes.

**Resolution**: [ADR-0003 Temporal](adrs/0003-workflow-engine-temporal.md). Temporal for durable execution; HITL as `await_signal`; per-activity retries; workflow versioning.

## 5. Hallucination from raw evidence in prompts

**Failure mode**: Agent confidently invents claims when fed raw tags, raw timestamps, raw vendor coding schemes.

**Resolution**: Pydantic contracts ([ADR-0007](adrs/0007-contracts-as-pydantic.md)) + canonical descriptors ([ADR-0001](adrs/0001-tag-resolution-service.md), [ADR-0002](adrs/0002-units-of-measure.md)). Raw artifacts confined to provenance ([ADR-0010](adrs/0010-provenance-and-audit.md)); never in LLM context.

## 6. Provenance gaps — claims that can't be traced

**Failure mode**: A cause map node cites a signal value that no one can re-derive from source data. Regulatory disqualification.

**Resolution**: [ADR-0010 Provenance](adrs/0010-provenance-and-audit.md). Every tool return embeds Provenance. Append-only audit log. Bundle invariants enforced.

## 7. Template version drift between probes

**Failure mode**: A template changes mid-probe; re-opened probes use a different definition than the original.

**Resolution**: [SPEC-010 Overlay Learning](templates/SPEC-010-overlay-learning.md). Semver per template. Probes pin template version at start. Overlays versioned with supersedes chains.

## 8. Connector failure during a probe

**Failure mode**: PI is down. Agent retries forever, hangs, or makes things up.

**Resolution**: Per-tool retry policy in Temporal ([SPEC-004](temporal/SPEC-004-probe-workflow.md)). Explicit `source_unavailable` error code that the agent reasons about. Degraded-mode behavior documented per template (proceed with partial evidence vs halt).

## 9. Cost blowups — runaway LLM and connector calls

**Failure mode**: A probe fan-out hits Claude rate limits, blows through PI API quota, or runs an LLM loop indefinitely.

**Resolution**: Per-probe budget ([SPEC-002](connectors/SPEC-002-mcp-tool-contracts.md)). Every tool checks budget; `budget_exceeded` halts the probe cleanly. Budget configurable per tenant per equipment class.

## 10. Multi-tenancy retrofit pain

**Failure mode**: MVP ships single-tenant; bolt-on multi-tenancy later requires touching everything.

**Resolution**: `tenant_id` is a required field on every domain object from day one. Postgres rows are partitioned or row-policied by tenant. TRS, audit log, evidence bundles all carry tenant.

## 11. PII and sensitive data in LLM context

**Failure mode**: Operator names, contractor names, blame-implying narratives leak into prompts and downstream caches.

**Resolution**: Document classification at ingest. Redaction rules applied before context build. Audit log keeps raw; UI redacts on read by viewer role.

## 12. No way to measure if the agent got better

**Failure mode**: Template change improves one scenario, regresses another. No one notices until pilot.

**Resolution**: [EPIC-009 Evaluation Harness](eval/EPIC-009-evaluation-harness.md). Frozen scenarios, scored automatically, regressions block PRs.

## 13. Rejected cause maps lost to the void

**Failure mode**: Reviewer rejects an agent proposal; learning signal is wasted.

**Resolution**: [SPEC-005 HITL Gates](hitl/SPEC-005-hitl-gates.md) and [SPEC-010](templates/SPEC-010-overlay-learning.md). Rejection captures structured diff + rationale; feeds `overlay.propose_update`.

## 14. Connector authentication chaos

**Failure mode**: Kerberos for PI, OAuth for Maximo SaaS, basic auth for SAP — credentials sprawl across config.

**Resolution**: Credential broker pattern. Connectors fetch tenant-scoped credentials from a central broker; secrets never in source or env.

## 15. Simulator-production parity drift

**Failure mode**: Agent works on simulators, fails on first real connection.

**Resolution**: [ADR-0008](adrs/0008-simulators-first.md) + EPIC-011 parity tests. Contracts are the source of truth; production parity gated before pilot.

## 16. Simulators-as-MCP mistake (load-bearing reframe)

**Failure mode**: We start by writing simulators that *expose MCP directly*. When we plug into a real customer source, all the MCP translation, provenance stamping, unit and time normalization, retry logic, and credential handling has to be re-invented in a hurry — because none of it lived in product code.

**Resolution**: [ADR-0012](adrs/0012-connectors-own-the-contract.md). **Connectors** own the MCP contract and ship to customers; **simulators** speak source-side protocols (PI Web API, OSLC, OPC UA, MQTT, SharePoint REST) and exist only in dev/CI. The agent↔connector contract is the only contract that matters. Swapping simulator ↔ real source is a connector-config change.

## 17. Probe trigger shape undefined

**Failure mode**: Every entry point (operator UI, alarm engine, cron, threshold worker) invents its own trigger envelope. Idempotency lost, multi-tenant authz inconsistent, replay is impossible.

**Resolution**: [SPEC-012](temporal/SPEC-012-probe-trigger-schema.md). One canonical `ProbeTrigger` Pydantic model + REST API + dedup window.

## 18. Tenant onboarding ad-hoc

**Failure mode**: Customer rolls in, gets half-onboarded (connectors yes, MAR no, templates no), triggers a probe, the agent silently produces garbage because TRS has 40% unresolved tags.

**Resolution**: [SPEC-013](foundations/SPEC-013-tenant-onboarding.md). Six-stage Temporal workflow with explicit gates; production cutover blocked until all gates pass.

## 19. Simulator fixture chaos

**Failure mode**: Each simulator invents its own YAML format; cross-simulator coherence (Maximo work order matches PI vibration spike) is impossible.

**Resolution**: [SPEC-014](simulators/SPEC-014-simulator-fixture-schema.md). One fixture tree (`fixtures/refplant/`) shared by all simulators with a CI validator.

## 20. Equipment template variance across classes

**Failure mode**: We add a second equipment class (motors) and discover the template schema we wrote for pumps doesn't generalize — every class needs custom YAML, every agent prompt is bespoke.

**Resolution**: [SPEC-015](templates/SPEC-015-equipment-template-schema.md). Single template schema with explicit `signal_roles`, `failure_modes`, `evidence_recipe`, `tier_budgets`, `overlay_*` surfaces. Adding a class is a YAML file, not a code change.

## Open questions (no resolution yet)

These are real and need ADRs before pilot:

- **OQ-1**: Cross-tenant overlay learning. Can the agent learn from probes across tenants without leaking proprietary data? Anonymization strategy TBD.
- **OQ-2**: Cause map ground-truth labelling at scale. How do we get enough labelled probes to validate overlay learning robustly?
- **OQ-3**: Air-gapped on-prem deployments. Some operators won't allow outbound calls to Claude. Local model fallback or air-gapped Bedrock?
- **OQ-4**: Failure-mode priors for new equipment classes — bootstrapping when OREDA coverage is thin.
