# SPEC-001: Evidence Bundle

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0001](../adrs/0001-tag-resolution-service.md), [0002](../adrs/0002-units-of-measure.md), [0006](../adrs/0006-time-handling.md), [0010](../adrs/0010-provenance-and-audit.md), [0011](../adrs/0011-master-asset-registry.md)

## Purpose

The `EvidenceBundle` is the fundamental data structure passed between MCP tools, agent reasoning, and persistence. It represents a typed, provenance-bearing collection of evidence about an asset over a time window.

## Schema

```python
from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime

# Core identifiers
SignalID = Annotated[UUID, Field(description="Canonical sensor UUID from TRS")]
AssetID  = Annotated[UUID, Field(description="Canonical asset UUID")]
TenantID = Annotated[UUID, Field(description="Tenant scope")]

class PressureReference(str, Enum):
    absolute = "absolute"
    gauge = "gauge"
    differential = "differential"
    not_applicable = "not_applicable"

class AssetDescriptor(BaseModel):
    """Canonical asset record from the Master Asset Registry. Closes gap G2.
    Mirrors SPEC-011 storage; this is the in-memory contract."""
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    asset_id: AssetID
    tenant_id: TenantID
    tag: str                                  # plant-local tag, e.g., "P-101A"
    name: str
    iso14224_class: str                       # e.g., "pump.centrifugal"
    template_class: str                       # equipment template class id
    template_version: str                     # pinned template version
    parent_asset_id: AssetID | None = None
    site_id: str
    area_id: str | None = None
    unit_id: str | None = None
    criticality: Literal["low", "medium", "high", "critical"] = "medium"
    service: str | None = None                # e.g., "charge pump", "BFW"
    nameplate: dict[str, str | float | int] = Field(default_factory=dict)
    external_ids: dict[str, str] = Field(default_factory=dict)
    # ^^^ keys like "pi_af_path", "maximo_location", "sap_equipment", "uns_segment"
    installed_at: AwareDatetime | None = None
    decommissioned_at: AwareDatetime | None = None

class SignalDescriptor(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    signal_id: SignalID
    tenant_id: TenantID
    asset_id: AssetID
    role: str                                # e.g., "discharge_pressure"
    qudt_unit: str                           # QUDT URI for canonical unit
    pressure_reference: PressureReference = PressureReference.not_applicable
    range_min: float | None = None
    range_max: float | None = None
    description: str | None = None

class TimeBasis(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    source_clock: str
    observed_offset_seconds: float
    offset_measurement_time: AwareDatetime
    source_timezone: str
    confidence: Literal["ntp_synced", "configured", "estimated", "unknown"]

class HistorianMode(str, Enum):
    stored = "stored"
    interpolated = "interpolated"
    aggregated = "aggregated"

class Measurement(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    signal_id: SignalID
    timestamp: AwareDatetime                 # UTC required
    value: float
    quality: Literal["good", "uncertain", "bad", "missing"] = "good"
    is_interpolated: bool = False

class MeasurementSeries(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    signal: SignalDescriptor
    time_basis: TimeBasis
    mode: HistorianMode
    interpolation_method: Literal["linear", "previous", "step"] | None = None
    aggregation_method: Literal["avg", "min", "max", "stddev", "count"] | None = None
    aggregation_interval: timedelta | None = None
    values: list[Measurement]

class Alarm(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    asset_id: AssetID
    signal_id: SignalID | None = None
    timestamp: AwareDatetime
    priority: int
    state: Literal["activated", "acknowledged", "cleared", "shelved"]
    message: str
    source_system: str

class SequenceOfEventsRecord(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    asset_id: AssetID
    signal_id: SignalID | None = None
    timestamp: AwareDatetime                  # SOE recorder, ms precision
    event_type: str
    detail: dict[str, str | float | int | bool]

class WorkOrder(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    work_order_id: str
    asset_id: AssetID
    opened_at: AwareDatetime
    closed_at: AwareDatetime | None
    priority: str
    status: str
    failure_code: str | None = None           # ISO 14224 code if present
    description: str
    actions_taken: str | None = None
    source_system: Literal["maximo", "sap_pm"]

class DocumentRef(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    document_id: str
    asset_id: AssetID | None = None
    title: str
    doc_type: Literal["datasheet", "p_and_id", "rca_report", "soop", "manual", "other"]
    uri: str
    last_modified: AwareDatetime
    excerpt: str | None = None                # relevant snippet for the probe

class Provenance(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    tool_name: str
    tool_version: str
    source: str
    source_query: str
    queried_at: AwareDatetime
    response_id: UUID
    record_count: int
    truncated: bool
    raw_tags: list[str] = Field(default_factory=list)    # forensic only, never in LLM context
    notes: str | None = None

class EvidenceBundle(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    bundle_id: UUID
    probe_id: UUID
    tenant_id: TenantID
    window_start: AwareDatetime
    window_end: AwareDatetime
    series: list[MeasurementSeries] = Field(default_factory=list)
    alarms: list[Alarm] = Field(default_factory=list)
    soe: list[SequenceOfEventsRecord] = Field(default_factory=list)
    work_orders: list[WorkOrder] = Field(default_factory=list)
    documents: list[DocumentRef] = Field(default_factory=list)
    provenance: list[Provenance]                          # one entry per tool call that contributed
```

## Invariants

1. **Every signal referenced must exist in TRS.** Bundle validation calls `trs.get_signal(signal_id)` for each unique signal_id; missing IDs fail the bundle.
1a. **Every asset referenced must exist in MAR.** Bundle validation calls `assets.get(asset_id)` for each unique asset_id; missing IDs fail the bundle. The agent always works with `AssetDescriptor` objects, never raw asset tag strings.
2. **All timestamps are UTC.** Pydantic `AwareDatetime` enforces tzinfo presence; validators reject non-UTC offsets at the bundle boundary.
3. **Value units match `signal.qudt_unit`.** Measurements are always in canonical SI per the signal's QUDT URI; no per-measurement unit field.
4. **`provenance` is never empty.** A bundle without provenance is invalid.
5. **`raw_tags` is forensic-only.** Agent prompt construction code MUST strip raw_tags before serializing into context. Lint rule + runtime check at prompt-build time.

## Size budgeting

A typical centrifugal pump probe has ~30 signals × 30 days × 1-minute aggregation = ~1.3M points. Raw bundle is large; we store full bundles in object storage (S3/MinIO) and pass `bundle_id` references in Temporal payloads. Tools that operate on bundles read from object storage; LLM context receives summaries, not raw series.

## Persistence

- **Bundles**: object storage (S3/MinIO) under `s3://rca-evidence/<tenant>/<probe>/<bundle_id>.json.zst`.
- **Provenance and metadata**: Postgres `evidence_bundles` table for queryability.
- **Audit log**: Postgres `audit_log` (append-only), keyed by `response_id`.

## Open questions

- Schema versioning strategy when measurements add new fields (e.g., per-point uncertainty)? Proposal: additive only within a major version; major bump triggers migration.
- How long do we retain raw bundles vs derived summaries? Default 7 years for bundles tied to closed probes; configurable per tenant.
