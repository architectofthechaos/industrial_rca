# SPEC-011: Master Asset Registry (MAR)

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0011](../adrs/0011-master-asset-registry.md)

## Purpose

Owns the canonical mapping between source-system asset identifiers and `AssetID` UUIDs. Single source of truth for asset identity, hierarchy, ISO 14224 class, and criticality.

## Data model

### `assets` table — master list of physical equipment

```sql
CREATE TABLE assets (
    asset_id            UUID PRIMARY KEY,            -- UUIDv7 for time-ordered
    tenant_id           UUID NOT NULL,
    parent_asset_id     UUID REFERENCES assets(asset_id),   -- hierarchy
    iso14224_class      TEXT NOT NULL,               -- 'centrifugal_pump', 'gas_turbine', etc.
    iso14224_level      INTEGER NOT NULL,            -- 1..9 per ISO 14224 taxonomy
    tag                 TEXT NOT NULL,               -- customer-preferred name, e.g., 'P-101A'
    service             TEXT,                        -- 'charge', 'BFW', 'crude_injection', etc.
    criticality         TEXT NOT NULL,               -- 'A' | 'B' | 'C' | 'D'
    manufacturer        TEXT,
    model               TEXT,
    serial_number       TEXT,
    commissioned_at     TIMESTAMPTZ,
    decommissioned_at   TIMESTAMPTZ,
    location_description TEXT,
    description         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON assets (tenant_id, iso14224_class);
CREATE INDEX ON assets (tenant_id, parent_asset_id);
CREATE INDEX ON assets (tenant_id, tag);
```

### `asset_aliases` table — translation dictionary

```sql
CREATE TABLE asset_aliases (
    alias_id            UUID PRIMARY KEY,
    asset_id            UUID NOT NULL REFERENCES assets(asset_id),
    tenant_id           UUID NOT NULL,
    source_system       TEXT NOT NULL,               -- 'maximo', 'sap_pm', 'pi_af', 'uns', 'dcs', 'spreadsheet'
    external_id         TEXT NOT NULL,               -- the source-system identifier, e.g., 'EQ-100425'
    valid_from          TIMESTAMPTZ NOT NULL,
    valid_to            TIMESTAMPTZ,                 -- NULL = currently valid
    mapping_source      TEXT NOT NULL,               -- 'authoritative_import' | 'cross_walk' | 'regex_heuristic' | 'human_confirmed'
    confidence          DOUBLE PRECISION NOT NULL,   -- 0..1
    is_primary          BOOLEAN NOT NULL DEFAULT FALSE,  -- one primary alias per (asset, source_system)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_by        TEXT,
    notes               TEXT
);
CREATE INDEX ON asset_aliases (tenant_id, source_system, external_id);
CREATE INDEX ON asset_aliases (asset_id);
CREATE UNIQUE INDEX ON asset_aliases (tenant_id, source_system, external_id)
    WHERE valid_to IS NULL;
```

### `asset_aliases_unresolved` table — queue of unknowns

```sql
CREATE TABLE asset_aliases_unresolved (
    external_id         TEXT NOT NULL,
    source_system       TEXT NOT NULL,
    tenant_id           UUID NOT NULL,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    occurrence_count    BIGINT NOT NULL DEFAULT 1,
    last_attempt_at     TIMESTAMPTZ,
    candidate_payload   JSONB,                       -- enough context to help a human resolve
    PRIMARY KEY (tenant_id, source_system, external_id)
);
```

## Resolution algorithm

```python
def resolve_asset(external_id, source_system, tenant_id, time=None) -> AssetResolution:
    # Step 1: exact alias match valid at time
    row = aliases.find(tenant_id, source_system, external_id, valid_at=time)
    if row:
        return Resolved(asset_id=row.asset_id, confidence=row.confidence,
                        mapping_source=row.mapping_source)

    # Step 2: cross-walk through other source systems already resolved
    # (e.g., Maximo EQ-100425 -> tag P-101A -> PI AF element P-101A)
    candidates = aliases.find_by_known_crosswalk(tenant_id, external_id)
    if len(candidates) == 1:
        return Resolved(asset_id=candidates[0].asset_id, confidence=0.85,
                        mapping_source='cross_walk')
    if len(candidates) > 1:
        return Ambiguous(candidates=candidates)

    # Step 3: regex heuristic
    parsed = regex_extract_tag(external_id, tenant_id)
    if parsed:
        asset = assets.find(tenant_id, tag=parsed.tag)
        if asset:
            return Resolved(asset_id=asset.id, confidence=0.7,
                            mapping_source='regex_heuristic')

    # Step 4: record unresolved, return for HITL
    unresolved.upsert(tenant_id, source_system, external_id)
    return Unresolved()
```

## MCP tools

### `assets.resolve`

Input:
```python
class ResolveAssetInput(BaseModel):
    external_id: str
    source_system: str
    tenant_id: UUID
    time: AwareDatetime | None = None
    min_confidence: float = 0.85
```

Output:
```python
class ResolveAssetOutput(BaseModel):
    status: Literal["resolved", "ambiguous", "unresolved"]
    asset: AssetDescriptor | None
    confidence: float
    mapping_source: str
    alternatives: list[AssetDescriptor] = []
    provenance: Provenance
```

### `assets.get`

Input: `asset_id: UUID`, `tenant_id: UUID`
Output: `AssetDescriptor` including parent chain.

### `assets.search`

Input:
```python
class SearchAssetsInput(BaseModel):
    tenant_id: UUID
    iso14224_class: str | None = None
    tag_pattern: str | None = None
    parent_asset_id: UUID | None = None
    criticality: list[str] | None = None
    service: str | None = None
    limit: int = 50
```

Output: `list[AssetDescriptor] + Provenance`

### `assets.get_hierarchy` *(removed Sprint 1 — hierarchy moves to the KG in Sprint 2)*

Input: `asset_id: UUID`, `direction: 'up' | 'down' | 'both'`, `max_depth: int = 5`
Output: tree of `AssetDescriptor` nodes.

### `assets.classify_iso14224`

Input: `asset_id: UUID`
Output: `iso14224_class`, `iso14224_level`, justification.

This is a separate tool (rather than just reading the column) because for unclassified assets it runs a classification heuristic against nameplate + name + parent context.

### `assets.register` (admin)

Creates a new asset and one or more initial aliases. Authenticated, audited.

### `assets.confirm_alias` (admin / HITL)

Promotes an unresolved external_id to a confirmed alias. Triggered by `asset_confirmation_needed` HITL gate.

### `assets.merge` (admin)

When discovery creates two assets that turn out to be the same physical equipment, merge them: keep one canonical asset_id, redirect all aliases and dependent signals to it, mark the other deprecated. Audited and reversible within 7 days.

## Pydantic model

```python
class AssetDescriptor(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    asset_id: UUID
    tenant_id: UUID
    parent_asset_id: UUID | None
    iso14224_class: str
    iso14224_level: int
    tag: str
    service: str | None
    criticality: Literal["A", "B", "C", "D"]
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    commissioned_at: AwareDatetime | None
    decommissioned_at: AwareDatetime | None
    location_description: str | None
    description: str | None
```

## Ingestion paths

1. **Maximo import (authoritative for most customers)** — pulls functional location hierarchy and equipment master. Each Maximo functional location becomes an asset; Maximo equipment number becomes the primary alias.
2. **SAP PM import** — pulls equipment master and functional locations. Same shape as Maximo.
3. **Engineering tag register spreadsheet** — CSV/Excel import for customers without a clean CMMS source.
4. **PI AF cross-walk** — walks PI AF elements and matches to existing assets by tag; creates aliases.
5. **UNS namespace cross-walk** — parses UNS path segments and matches to existing assets by tag; creates aliases.
6. **Manual curation** — admin UI for the unresolved-alias queue and for new asset registration.

## HITL `asset_confirmation_needed` flow

When discovery encounters an external_id that cannot be resolved with sufficient confidence:
```python
class AssetConfirmationRequest(BaseModel):
    probe_id: UUID | None       # set if discovered during a probe; None if during onboarding sweep
    unresolved: list[UnresolvedAssetDetail]
    suggested_matches: list[ResolveAssetOutput]
    deadline: AwareDatetime | None
```

Resolver confirms; `assets.confirm_alias` is called; probe (if any) resumes via Temporal signal.

## Performance targets

- p50 resolution: < 5 ms (Postgres with index)
- p99: < 50 ms
- Hierarchy fetch (depth 5): < 20 ms
- Per-tenant LRU cache, 60s TTL.

## Onboarding sequence

Per tenant, in order:

1. Pick the authoritative source (usually Maximo).
2. Run authoritative import → populates `assets` with primary aliases.
3. Run secondary cross-walk ingestors (PI AF, UNS, SAP PM as applicable) → adds aliases to existing assets, queues unknowns.
4. Human resolves the unresolved queue.
5. **MAR is now ready.** TRS ingestion can start. Probes can run.

## Relationship to TRS

`signals.asset_id` is a foreign key to `assets.asset_id`. When TRS resolves a signal, it returns a `SignalDescriptor` with `asset_id`; the agent can then call `assets.get(asset_id)` to get the full asset descriptor.

## Relationship to the knowledge graph

The KG built per probe seeds its root nodes from MAR (`assets.get_hierarchy` — removed Sprint 1; the KG owns hierarchy from Sprint 2 on). KG node IDs match `asset_id`. This keeps KG and connectors in lockstep.

## Test plan

- Unit: resolution algorithm with synthetic alias sets covering ambiguity, cross-walk, temporal validity, regex.
- Contract: every `ResolveAssetOutput` validates; round-trip with simulators.
- Integration: full onboarding sequence (Maximo import + PI AF cross-walk + UNS cross-walk) against simulators, with unresolved queue assertions.
- Replay: asset rename scenario validates that historical evidence still resolves to the correct asset.

## Out of scope (explicit minimalism)

- Maintenance plans, work order templates, spare parts, inspection schedules — stay in source CMMS, queried on demand.
- Engineering documents (datasheets, P&IDs) — referenced via `DocumentRef`, not stored in MAR.
- Live operational state (running/stopped, mode) — read from historian/SCADA, not MAR.
- Cost / financial data — out of scope entirely.

If a feature requires extending MAR beyond identity + hierarchy + class + criticality + nameplate, that's an ADR.
