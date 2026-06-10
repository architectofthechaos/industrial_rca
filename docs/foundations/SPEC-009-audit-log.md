# SPEC-009: Audit Log

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0010](../adrs/0010-provenance-and-audit.md)

## Purpose

Append-only record of every tool invocation, HITL decision, and mutating action. Enables reconstruction of any probe outcome and supports regulatory traceability.

## Schema

```sql
CREATE TABLE audit_log (
    response_id        UUID PRIMARY KEY,
    tenant_id          UUID NOT NULL,
    probe_id           UUID,
    workflow_id        TEXT NOT NULL,         -- Temporal workflow id
    run_id             TEXT NOT NULL,         -- Temporal run id
    activity_id        TEXT,
    tier               TEXT,                  -- 'scope' | 'evidence' | 'reason' | 'govern' | NULL
    tool_name          TEXT NOT NULL,
    tool_version       TEXT NOT NULL,
    source_system      TEXT,
    started_at         TIMESTAMPTZ NOT NULL,
    completed_at       TIMESTAMPTZ NOT NULL,
    duration_ms        INTEGER NOT NULL,
    status             TEXT NOT NULL,         -- 'success' | 'error' | 'timeout' | 'budget_exceeded'
    error_code         TEXT,
    input_hash         TEXT NOT NULL,         -- sha256 of canonicalized input
    input_uri          TEXT,                  -- pointer to full input in object storage
    output_hash        TEXT,
    output_uri         TEXT,                  -- pointer to full output
    cost_usd           NUMERIC(12, 6) DEFAULT 0,
    tokens_in          INTEGER,
    tokens_out         INTEGER,
    raw_tags           TEXT[]                 -- raw tags involved (for forensics)
) PARTITION BY RANGE (started_at);
```

Partitioned monthly; older partitions can be moved to cold storage.

## What gets logged

- Every MCP tool invocation (input, output, status, timing, cost).
- Every HITL request issuance and decision.
- Every workflow signal received.
- Every overlay update (proposed and committed).
- Every CMMS write-back (preview and commit).

## Append-only enforcement

- Postgres role `rca_writer` has INSERT only.
- DELETE / UPDATE blocked by table policies.
- Retention enforced by partition drop (not row deletion), aligned to tenant retention policy.

## Query patterns

- **Reconstruct probe**: `SELECT * FROM audit_log WHERE probe_id = $1 ORDER BY started_at`.
- **Find all uses of a signal**: `SELECT * FROM audit_log WHERE $1 = ANY(raw_tags)` — useful when a tag is later discovered to be miscalibrated.
- **Cost report per probe**: `SELECT probe_id, SUM(cost_usd) FROM audit_log GROUP BY probe_id`.

## Retention

- Default: 7 years.
- Per-tenant configurable.
- Object storage (input/output URIs) retention matches.

## PII and redaction

- Tools that may emit PII (operator names in notes) flag the output for redaction-on-read.
- Audit log stores raw; UI redacts based on viewer role.
