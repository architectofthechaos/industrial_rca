# ADR-0010: Provenance and audit on every tool return

- **Status**: Accepted
- **Date**: 2026-06-03
- **Deciders**: gvishnu

## Context

RCA outputs end up in incident investigations, regulatory filings, and occasionally court. Every claim in the final cause map must trace back to specific source data with specific timestamps and specific tool invocations. If we cannot produce the provenance, the deliverable is unusable.

## Decision

Every MCP tool return is a Pydantic model that includes a `Provenance` block:

```python
class Provenance(BaseModel):
    tool_name: str
    tool_version: str
    source: str                # e.g., "pi_historian_main"
    source_query: str          # the actual query/URL/SQL/etc, sanitized
    queried_at: datetime       # UTC
    response_id: UUID          # unique per invocation, used as foreign key in audit log
    record_count: int
    truncated: bool
    raw_tags: list[str] = []   # original tag strings — never enters LLM context
    notes: str | None = None
```

Plus an `AuditLog` table that records every tool invocation with full inputs, outputs, and timing — keyed by `response_id`.

Hard rules:

1. **No tool may return data without provenance.** Validation enforced at MCP server layer.
2. **Provenance is preserved through transformations.** If the agent aggregates 3 evidence bundles into a cause map node, the node's `evidence_ref` list contains the `response_id`s of all 3 source bundles.
3. **Audit log is append-only.** Probe deliverables can be re-derived from the audit log.
4. **Raw tags are in provenance, never in agent context.** The agent reasons over canonical SignalDescriptors; raw tags exist only for forensic traceability.
5. **Retention**: 7 years (default), per-tenant configurable.

## Alternatives considered

**A. Provenance as a separate event stream, not embedded in returns.** Rejected — too easy to lose synchronization. Embedded means there is no "naked" return.

**B. Best-effort provenance.** Rejected — once a single un-provenance-able claim enters a cause map, the whole map becomes untrustworthy.

## Consequences

**Positive:**

- Auditability is structural, not an afterthought.
- Cause map nodes can be drilled down to source measurements.
- Regulatory compliance is achievable.
- Bug investigation has full replay.

**Negative:**

- Storage cost (audit log grows). Mitigated by retention policy and partitioning.
- Every tool implementation has provenance boilerplate (factored into a base class).

## References

- [SPEC-001 Evidence Bundle](../foundations/SPEC-001-evidence-bundle.md)
- [SPEC-009 Audit Log](../foundations/SPEC-009-audit-log.md)
