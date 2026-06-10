# SPEC-012: Probe Trigger Schema

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0003](../adrs/0003-workflow-engine-temporal.md), [0006](../adrs/0006-time-handling.md), [0010](../adrs/0010-provenance-and-audit.md), [0011](../adrs/0011-master-asset-registry.md)
- **Closes gap**: G3 (probe trigger schema undefined)

## Purpose

Define the canonical shape of a **probe trigger** — the input that causes the system to start a new RCA workflow. Triggers are the public API of the agent: every Temporal workflow run starts from one. They must be small, validated, idempotent, and carry enough context for the agent to scope the probe without re-deriving anything sensitive.

## Trigger sources (MVP)

| Source | Channel | Latency target | Example |
|---|---|---|---|
| **Operator** | REST POST from a console UI | seconds | "P-101A is making a noise, run RCA" |
| **Alarm** | Kafka topic `alarms.fired` | < 10s | Vibration > 8 mm/s on P-101A for 5 min |
| **Schedule** | Temporal cron schedule | n/a | Weekly review of top-10 bad actors |
| **Threshold (overlay)** | Stream processor → Kafka | < 30s | Discharge pressure -2σ from learned baseline |
| **Upstream probe** | Internal event from another probe | seconds | Tier-3 traverses neighborhood → spawns child probes |

All sources converge on the same `ProbeTrigger` envelope below.

## Pydantic contract

Lives in `packages/contracts/probe_trigger.py`.

```python
from typing import Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field, model_validator
from uuid import UUID

TriggerSource = Literal[
    "operator",
    "alarm",
    "schedule",
    "threshold",
    "upstream_probe",
]

class TriggerEvidenceHint(BaseModel):
    """Optional pointers the trigger source already has — agent must still verify."""
    signal_ids: list[UUID] = Field(default_factory=list)
    alarm_ids: list[str] = Field(default_factory=list)
    work_order_ids: list[str] = Field(default_factory=list)
    document_uris: list[str] = Field(default_factory=list)
    free_text: Optional[str] = None  # operator narrative, alarm message

class ProbeTrigger(BaseModel):
    # ---- Identity ----
    trigger_id: UUID                # UUIDv7, monotonic
    tenant_id: UUID
    idempotency_key: str            # caller-provided; dedupes within 24h window

    # ---- What ----
    source: TriggerSource
    asset_id: UUID                  # canonical MAR AssetID — required, never raw tag
    failure_signature: Optional[str] = None   # short tag like "vibration_high", "seal_leak"

    # ---- When ----
    detected_at: datetime           # UTC ISO 8601 with tzinfo; when source first noticed
    trigger_window_start: datetime  # earliest evidence time we know we care about
    trigger_window_end: datetime    # latest; usually == detected_at

    # ---- Who / Why ----
    actor: str                      # user_id, "system:alarm-engine", "cron:weekly-bad-actors"
    reason: str                     # short human-readable summary

    # ---- Context ----
    severity_hint: Literal["low", "medium", "high", "critical"] = "medium"
    evidence_hints: TriggerEvidenceHint = Field(default_factory=TriggerEvidenceHint)
    parent_probe_id: Optional[UUID] = None     # only set when source=upstream_probe
    budget_override_usd: Optional[float] = None  # if absent use tenant default

    # ---- Provenance ----
    received_at: datetime           # when the API gateway accepted it
    source_request_id: Optional[str] = None    # caller's request id for tracing

    @model_validator(mode="after")
    def _check_windows(self) -> "ProbeTrigger":
        if self.trigger_window_start > self.trigger_window_end:
            raise ValueError("trigger_window_start must be <= trigger_window_end")
        if self.trigger_window_end > self.detected_at:
            raise ValueError("trigger_window_end must be <= detected_at")
        if self.source == "upstream_probe" and self.parent_probe_id is None:
            raise ValueError("upstream_probe trigger requires parent_probe_id")
        return self
```

## Idempotency

- `idempotency_key` is `(source, asset_id, failure_signature, floor(detected_at, 5min))` for system-generated triggers.
- Operator triggers use a UI-provided UUID; double-clicks are caught client-side.
- The probe-service deduplicates triggers seen within a 24h window. Duplicates return the existing `probe_id`.

## Validation pipeline (probe-service)

```
HTTP POST /triggers  ──▶  schema validate (Pydantic)
                     ──▶  tenant authz check
                     ──▶  asset_id exists in MAR for this tenant
                     ──▶  windows sane (see model_validator)
                     ──▶  idempotency dedup
                     ──▶  enqueue Temporal workflow with ProbeTrigger as input
                     ──▶  return 202 + probe_id
```

Reject with `ToolError(code="validation_failed")` on any failure. Never silently fix a bad trigger.

## Time window semantics

Triggers carry the **trigger window**, not the **evidence window**. The agent's Scope-tier step computes the `EvidenceWindow` by extending the trigger window using:
1. The equipment template's `default_lookback` (e.g., 30d for seal leak, 24h for cavitation).
2. Any explicit hints in `evidence_hints` (e.g., a referenced work-order from 90d ago).
3. Time-axis sanity caps (no more than 365d for MVP).

See [SPEC-001](SPEC-001-evidence-bundle.md) for `EvidenceWindow`.

## Storage

Triggers are persisted to `probe_triggers` table immediately on receipt, before the Temporal workflow starts. This gives us an audit trail even when workflows fail to start.

```sql
CREATE TABLE probe_triggers (
    trigger_id        UUID PRIMARY KEY,
    tenant_id         UUID NOT NULL REFERENCES tenants(id),
    idempotency_key   TEXT NOT NULL,
    source            TEXT NOT NULL,
    asset_id          UUID NOT NULL,
    failure_signature TEXT,
    detected_at       TIMESTAMPTZ NOT NULL,
    window_start      TIMESTAMPTZ NOT NULL,
    window_end        TIMESTAMPTZ NOT NULL,
    actor             TEXT NOT NULL,
    reason            TEXT NOT NULL,
    severity_hint     TEXT NOT NULL,
    payload           JSONB NOT NULL,       -- full ProbeTrigger
    probe_id          UUID,                 -- set after workflow starts
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX ix_probe_triggers_tenant_asset_time
    ON probe_triggers (tenant_id, asset_id, detected_at DESC);
```

## MCP tools

| Tool | Purpose |
|---|---|
| `probe.create_trigger` | Create a new trigger (internal — used by alarm/threshold workers). |
| `probe.get_trigger` | Fetch a `ProbeTrigger` by `trigger_id`. |
| `probe.list_triggers_for_asset` | Recent triggers for an asset (dedup view). |

## REST API (external)

Operator UIs and alarm engines hit:

```
POST /v1/triggers
Content-Type: application/json
X-Tenant-Id: <uuid>
Authorization: Bearer <token>

{ ...ProbeTrigger fields, minus trigger_id/received_at... }

→ 202 Accepted
{
  "trigger_id": "...",
  "probe_id": "...",
  "deduplicated": false
}
```

## Test plan

1. **Schema fuzz** — round-trip serialize/deserialize 10k random valid triggers.
2. **Window validators** — reject inverted windows, future detected_at, future windows.
3. **Idempotency** — same key within 24h returns same probe_id, after 24h creates new.
4. **Authz** — trigger for asset in another tenant returns 403, no row written.
5. **Source-specific** — `upstream_probe` without `parent_probe_id` rejected.

## Out of scope (post-MVP)

- Streaming triggers (websocket / SSE)
- Trigger composition (bundle N alarms into one trigger)
- Trigger replay / time-travel testing harness (separate spec)
