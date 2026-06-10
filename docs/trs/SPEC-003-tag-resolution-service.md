# SPEC-003: Tag Resolution Service (TRS)

**Status: Deferred — out of Phase 1 scope. See phase1_gap_analysis.md §8.**

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0001](../adrs/0001-tag-resolution-service.md)

## Purpose

Owns the canonical mapping between raw tag strings (and other identifiers) and `SignalID` UUIDs. Single source of truth for signal identity.

**Depends on**: [SPEC-011 Master Asset Registry](SPEC-011-master-asset-registry.md). `signals.asset_id` is a foreign key to `assets.asset_id`. MAR must be populated before TRS ingestion runs.

## Data model

### `signals` table
```sql
CREATE TABLE signals (
    signal_id           UUID PRIMARY KEY,            -- UUIDv7 for time-ordered
    tenant_id           UUID NOT NULL,
    asset_id            UUID NOT NULL REFERENCES assets(asset_id),  -- FK to Master Asset Registry (SPEC-011)
    role                TEXT NOT NULL,               -- e.g., 'discharge_pressure'
    qudt_unit           TEXT NOT NULL,               -- QUDT URI
    pressure_reference  TEXT,                        -- 'absolute' | 'gauge' | 'differential' | NULL
    range_min           DOUBLE PRECISION,
    range_max           DOUBLE PRECISION,
    description         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deprecated_at       TIMESTAMPTZ
);
CREATE INDEX ON signals (tenant_id, asset_id, role);
```

### `signal_aliases` table
```sql
CREATE TABLE signal_aliases (
    alias_id            UUID PRIMARY KEY,
    signal_id           UUID NOT NULL REFERENCES signals(signal_id),
    tenant_id           UUID NOT NULL,
    source_system       TEXT NOT NULL,               -- 'pi', 'uns', 'maximo', 'dcs', 'engineer_note'
    raw_tag             TEXT NOT NULL,               -- e.g., 'BAY3.P101A.PT.DISCH.PV'
    valid_from          TIMESTAMPTZ NOT NULL,
    valid_to            TIMESTAMPTZ,                 -- NULL = currently valid
    mapping_source      TEXT NOT NULL,               -- 'uns_authoritative' | 'pi_af_authoritative' | 'regex_heuristic' | 'human_confirmed'
    confidence          DOUBLE PRECISION NOT NULL,   -- 0..1
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_by        TEXT,                        -- user id if human_confirmed
    notes               TEXT
);
CREATE INDEX ON signal_aliases (tenant_id, source_system, raw_tag);
CREATE INDEX ON signal_aliases (signal_id);
```

### `signal_alias_unresolved` table
```sql
CREATE TABLE signal_alias_unresolved (
    raw_tag             TEXT NOT NULL,
    source_system       TEXT NOT NULL,
    tenant_id           UUID NOT NULL,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    occurrence_count    BIGINT NOT NULL DEFAULT 1,
    last_attempt_at     TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, source_system, raw_tag)
);
```

Unresolved tags pile up here until a human or downstream discovery process maps them.

## Tools (MCP)

### `trs.resolve_tag`

Input:
```python
class ResolveTagInput(BaseModel):
    raw_tag: str
    source_system: str
    tenant_id: UUID
    asset_hint: AssetID | None = None
    time: AwareDatetime | None = None         # for historical lookups
    min_confidence: float = 0.85
```

Output:
```python
class ResolveTagOutput(BaseModel):
    status: Literal["resolved", "ambiguous", "unresolved"]
    signal: SignalDescriptor | None
    confidence: float
    mapping_source: str
    alternatives: list[SignalDescriptor] = []   # populated when status == 'ambiguous'
    provenance: Provenance
```

Resolution algorithm (in order, first success wins):
1. **Exact match** in `signal_aliases` for `(tenant_id, source_system, raw_tag)` valid at `time`. If unique, return. If multiple, → ambiguous.
2. **Asset-hinted match** — same as above but filtered by `asset_id == asset_hint`.
3. **Regex heuristic** — apply tenant-configured regex patterns to extract asset + role from raw_tag, then `search_signals`. Confidence capped at 0.7.
4. **No match** — insert into `signal_alias_unresolved`, return `unresolved`.

### `trs.search_signals`

Input:
```python
class SearchSignalsInput(BaseModel):
    tenant_id: UUID
    asset_id: AssetID | None = None
    role: str | None = None
    role_pattern: str | None = None            # SQL LIKE-style
    limit: int = 50
```

Output: `list[SignalDescriptor] + Provenance`.

### `trs.get_signal`

Input: `signal_id: SignalID`, `tenant_id: UUID`
Output: `SignalDescriptor | None + Provenance`

### `trs.register_signal` (admin)

Creates a new signal and one or more initial aliases. Authenticated, audited.

### `trs.confirm_alias` (admin / HITL)

Promotes an unresolved tag to a confirmed alias. Triggered by the `tag_confirmation_needed` HITL gate.

## Ingestion paths (populating TRS)

1. **UNS discovery** — read Sparkplug B BIRTH messages or UNS namespace browse; UNS path is authoritative if present.
2. **PI AF browse** — iterate PI AF elements and attributes; map AF path → signal, AF attribute config string → raw_tag.
3. **Maximo asset import** — pull functional locations and attached measurement points.
4. **Regex onboarding** — for each tenant, configure naming convention regex(es) to bootstrap.
5. **Manual curation** — admin UI for unresolved tag queue.

## HITL `tag_confirmation_needed` flow

When a probe encounters an unresolved or low-confidence tag, it pauses with a structured payload:
```python
class TagConfirmationRequest(BaseModel):
    probe_id: UUID
    unresolved_tags: list[UnresolvedTagDetail]
    suggested_mappings: list[ResolveTagOutput]   # best guesses with confidence < threshold
    deadline: AwareDatetime | None
```

Resolver confirms in the UI; the confirmation `trs.confirm_alias` call promotes the alias, and the probe resumes via a Temporal signal.

## Performance targets

- p50 resolution latency: < 5 ms (Postgres with index)
- p99: < 50 ms
- Cache: in-process LRU per tenant for hot tags (60s TTL).

## Test plan

- Unit: resolution algorithm with synthetic alias sets, including ambiguity and historical validity.
- Contract: every `ResolveTagOutput` validates against schema; round-trip with simulators.
- Integration: full probe flow with a mix of resolved, ambiguous, and unresolved tags.
