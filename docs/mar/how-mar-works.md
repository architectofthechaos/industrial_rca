# How the Master Asset Registry (MAR) works

The Master Asset Registry is TRS for assets. Same three-table pattern, one level up. It exists because **before you can resolve a tag, you need to know what asset the tag belongs to**, and "what assets exist in this plant" is itself a nontrivial problem.

> **Spec reference**: [SPEC-011](SPEC-011-master-asset-registry.md). **Decision rationale**: [ADR-0011](../adrs/0011-master-asset-registry.md).
>
> **Sprint 1 update:** hierarchy no longer lives in MAR — `parent_asset_id` and `assets.get_hierarchy` were removed; the knowledge graph owns hierarchy from Sprint 2 on. Assets now also carry a `canonical_id` (`asset:{plant}:{unit}:{name}`). Hierarchy mentions below are historical.

## Why we need MAR at all

The same physical pump P-101A appears across systems with different identifiers:
- **Maximo** functional location `EQ-100425`
- **SAP PM** equipment number `10044521`
- **PI AF** element path `\\PIServer\Acme\Site1\Area3\P-101A`
- **UNS** namespace segment `Site1/Area3/Unit1/P-101A`
- **DCS** equipment ID `40-P-101A`
- **Engineer spreadsheet** row "P-101A, Charge Pump, Train A"

If we don't canonicalize, every connector invents its own asset UUID and the agent sees "six different pumps that have suspiciously similar tags."

This is structurally the same problem as tag aliasing. We solve it the same way.

## The pattern — identical to TRS

Three tables:

1. **`assets`** — the master list. One row per physical asset. UUID, hierarchy, ISO 14224 class, criticality, nameplate.
2. **`asset_aliases`** — the translation dictionary. One row per (source system, external identifier) per asset. Time-bounded for renames.
3. **`asset_aliases_unresolved`** — the queue of unknowns. Surfaces things we couldn't auto-resolve.

If you understood TRS, you already understand MAR. The only difference is the *thing being canonicalized* — physical equipment instead of physical sensors.

## Why MAR comes before TRS

`signals.asset_id` is a foreign key to `assets.asset_id`. You cannot create a signal without first having its asset.

Onboarding sequence per tenant:

```
1. Pick the authoritative source (usually Maximo)
2. MAR import — populates assets + primary aliases
3. MAR cross-walks (PI AF, UNS, SAP PM) — adds secondary aliases, queues unknowns
4. Human resolves the unresolved-asset queue
5. ────── MAR is ready ──────
6. TRS ingestion runs (UNS BIRTH, PI AF, regex onboarding)
7. Human resolves any unresolved-tag queue
8. ────── TRS is ready, probes can run ──────
```

## How MAR decides "these external IDs are the same physical asset"

Resolution algorithm, in order:

1. **Exact alias match** — `(tenant_id, source_system, external_id)` is already in `asset_aliases`. Done.
2. **Cross-walk** — the external ID isn't known for *this* source, but the *tag* matches an already-known asset from another source. Example: PI AF says element name is `P-101A`; MAR already has `P-101A` from Maximo with that tag. Confidence 0.85.
3. **Regex heuristic** — tenant-configured regex extracts a tag from the external ID; we look up by tag in `assets`. Confidence 0.7.
4. **Unresolved** — record in `asset_aliases_unresolved` and surface to HITL.

The agent never guesses. The unresolved queue is the explicit "human, help" surface.

## What lives in MAR (and what doesn't)

**Lives in MAR — identity and structural metadata:**
- Asset ID (UUID, canonical)
- Hierarchy via `parent_asset_id` (Site → Area → Unit → Equipment → Component)
- ISO 14224 class + level
- Criticality (A/B/C/D — affects probe priority and budget)
- Service (charge, BFW, injection — engineering context)
- Manufacturer / model / serial / commissioning dates

**Does NOT live in MAR — operational and lifecycle data:**
- Maintenance plans, work order templates, spare parts → Maximo / SAP
- Live operating state (running, stopped, mode) → historian / SCADA
- Engineering documents (datasheets, P&IDs) → SharePoint / document store, referenced from MAR by `DocumentRef`
- Cost data → out of scope entirely

The discipline is "minimal MAR." When in doubt, the source system stays the source. MAR is identity + classification + hierarchy. That's it.

## A worked example — adding pump P-101A

**Day 1, onboarding.** We import Maximo:

```
Maximo functional location: EQ-100425
  parent: U-103-CHARGE
  description: "Charge Pump P-101A Train A"
  equipment_class: PUMP-CENTRIFUGAL
  criticality: A
  manufacturer: Sulzer
  model: ZE-200
```

MAR creates one asset and one alias:

**assets**
| asset_id | tag | iso14224_class | criticality | parent_asset_id |
|---|---|---|---|---|
| `ast-001` | `P-101A` | centrifugal_pump | A | `ast-unit-103` |

**asset_aliases**
| asset_id | source_system | external_id | confidence | is_primary |
|---|---|---|---|---|
| ast-001 | maximo | `EQ-100425` | 1.0 | true |

**Day 2, PI AF cross-walk.** PI AF browser walks the AF tree:

```
\\PIServer\Acme\Site1\Area3\P-101A
  Type: Centrifugal Pump
  Attributes: DischargePressure, SuctionPressure, ...
```

MAR's resolver sees `P-101A` (the AF element name) matches `tag='P-101A'` for an existing asset (ast-001). It adds an alias:

| asset_id | source_system | external_id | confidence | is_primary |
|---|---|---|---|---|
| ast-001 | pi_af | `\\PIServer\...\P-101A` | 0.85 | false |

**Day 3, UNS cross-walk.** Sparkplug BIRTH messages arrive with namespace `Site1/Area3/Unit1/P-101A/...`. MAR parses the asset segment, matches by tag, adds the UNS alias.

**Day 4, an unknown.** SAP PM import shows equipment `10044521` with description "Pump 101A, Crude Charge Service." The cross-walk finds two candidate matches (P-101A and P-101 — close tag names). Confidence is too low. Record goes to `asset_aliases_unresolved`. A reliability engineer reviews and confirms it's P-101A. `assets.confirm_alias` creates the alias with `mapping_source='human_confirmed'`, `confidence=1.0`.

At this point, ast-001 has aliases in Maximo, PI AF, UNS, and SAP PM. The agent treats them as one asset. TRS can now safely create signals with `asset_id = ast-001` and link them to PI tags via TRS's own alias table.

## Renames, decommissions, replacements

Same pattern as TRS:

- **Rename** (`P-101A` becomes `P-201A` after re-numbering): mark old aliases `valid_to=cutover_time`, create new aliases with `valid_from=cutover_time`.
- **Decommission**: set `decommissioned_at` on the asset. Probes can't trigger on decommissioned assets, but historical probes still resolve correctly.
- **Replacement** (entire pump swapped, new serial number, same tag): debatable — is this the same asset or a new one? Default policy: same asset, update nameplate fields, log the replacement in an audit row. Customer-configurable.

## Why this isn't just "use Maximo as canonical"

Three reasons:
1. **Not all customers use Maximo.** Some are SAP PM, some are HxGN EAM, some are spreadsheets.
2. **Maximo asset numbers change.** Reorganizations renumber functional locations. If our canonical ID is Maximo's, every reorganization breaks our history.
3. **The KG needs a stable anchor.** The just-in-time KG built per probe roots its nodes on `asset_id`. If `asset_id` is tied to a vendor system, the KG can't survive vendor migrations.

Canonical = our UUID. Vendor systems = aliases that map to it.

## Mental model — passport vs visas

- The asset's `asset_id` (our UUID) is its **passport number**. Immutable, opaque, ours.
- Each `asset_alias` row is a **visa** issued by a particular country (source system) that says "we recognize this person under this name."
- The unresolved queue is **border control's review pile.**
- Renames and replacements are passport renewals — old passport gets a `valid_to`, new passport issues with `valid_from`.

## Where to go next

- The full schema and tools: [SPEC-011](SPEC-011-master-asset-registry.md)
- The decision and trade-offs: [ADR-0011](../adrs/0011-master-asset-registry.md)
- The signal side of this same pattern: [how-trs-works.md](how-trs-works.md)
- Implementation epic: [EPIC-012](EPIC-012-master-asset-registry.md)
