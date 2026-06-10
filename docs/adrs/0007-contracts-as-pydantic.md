# ADR-0007: Pydantic v2 models as the single source of truth for contracts

- **Status**: Accepted
- **Date**: 2026-06-03
- **Deciders**: gvishnu

## Context

We have many interfaces — MCP tool inputs/outputs, evidence bundle structure, Signal descriptors, template schema, workflow signals — and many consumers — agent, simulators, connectors, MCP servers, evaluation harness, tests. If each consumer defines its own types, drift is guaranteed.

## Decision

All contracts live in `packages/contracts` as **Pydantic v2 models**. Every other package imports from there. JSON Schema, OpenAPI specs, and MCP tool schemas are all generated from Pydantic models — never hand-written.

- `packages/contracts/signal.py` — `SignalID`, `SignalDescriptor`, role enums
- `packages/contracts/evidence.py` — `EvidenceBundle`, `Measurement`, `Alarm`, `WorkOrder`, `Document`
- `packages/contracts/probe.py` — `Probe`, `ProbeState`, `TimeWindow`
- `packages/contracts/template.py` — `EquipmentTemplate`, `FailureMode`, `EvidenceRecipe`
- `packages/contracts/causemap.py` — `CauseMap`, `Node`, `Edge`
- `packages/contracts/provenance.py` — `Provenance`, `ToolCallRecord`
- `packages/contracts/time_basis.py` — `TimeBasis`

Rules:

1. **Strict mode**: `model_config = ConfigDict(strict=True, extra='forbid', frozen=True)` unless mutation is explicitly required.
2. **No naive datetimes**: custom validator enforces `tzinfo is not None`.
3. **Versioned**: each contract module exposes `__contract_version__`. Breaking changes bump the version and require migration plan.
4. **No business logic in models**, only validation. Logic lives in services.

## Alternatives considered

**A. Protobuf / gRPC contracts.** Stronger schema evolution rules, but worse Python ergonomics, especially for LLM tool integration. Rejected.

**B. JSON Schema hand-written.** Rejected — drift between schemas and runtime types is inevitable.

**C. attrs / dataclasses with custom validation.** Rejected — Pydantic v2 is fast (rust core), has the validation we need, and is the de facto standard in the LangChain/LangGraph ecosystem.

## Consequences

**Positive:**

- One source of truth; no drift.
- Runtime validation catches contract violations at the boundary.
- JSON Schema for OpenAPI and MCP is free.
- Strict mode catches typos and extra fields.

**Negative:**

- Pydantic v2 strict mode is unforgiving; ingestion code must do explicit coercion at the boundary.
- Versioning discipline required.

## References

- Pydantic v2: https://docs.pydantic.dev
- [SPEC-001 Evidence Bundle](../foundations/SPEC-001-evidence-bundle.md)
