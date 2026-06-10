# ADR-0011: Master Asset Registry

- **Status**: Accepted
- **Date**: 2026-06-04
- **Deciders**: gvishnu

## Context

In [ADR-0001](0001-tag-resolution-service.md) we made `asset_id` a required field on every Signal, but never said where `asset_id` comes from. Every connector implicitly needs to map its own asset identifier — Maximo functional location, SAP equipment number, PI AF element, UNS namespace segment — to a canonical `asset_id`. Without an explicit owner of this mapping, three things happen:

1. **Each connector invents its own canonical ID.** Maximo's UUIDs disagree with PI AF's UUIDs for the same pump. The agent sees "two pumps."
2. **The KG drifts from the connectors.** The just-in-time KG built per probe has nodes that don't match what evidence tools return.
3. **Asset renames and lifecycle changes have no home.** When P-101A is decommissioned and replaced, there's no clean way to record this.

This is structurally the same problem as tag aliasing, one level up. It deserves the same structural solution.

## Decision

We will build a **Master Asset Registry (MAR)** that owns one canonical identifier per physical asset — the **Asset ID**, a UUIDv7. It mirrors TRS in pattern and code shape.

Hard rules:

1. **No MCP tool returns `asset_id` values that are not registered in MAR.** Connectors map their external identifiers to canonical Asset IDs via MAR's resolution tools.
2. **The asset hierarchy lives in MAR.** Site → Area → Unit → Equipment → Component is modeled in the `assets` table via `parent_asset_id`. Other services query MAR for hierarchy; they do not build their own.
3. **ISO 14224 class and criticality live in MAR.** Templates are selected by class; probe budgets are sized by criticality. Both read from MAR as source of truth.
4. **Asset aliases are time-bounded.** When an asset is renamed, decommissioned, or replaced, alias rows carry `valid_from` / `valid_to` so historical queries resolve correctly.
5. **One master source per tenant during onboarding.** Maximo is the default authoritative source for most customers; some have engineering tag-register spreadsheets; greenfield UNS-only is a third path. Pick one per tenant, document it, treat others as secondary aliases.
6. **MAR is minimal.** It stores identity, hierarchy, class, criticality, and basic nameplate. Maintenance plans, spare parts, inspection schedules stay in the source system and are queried on demand. We are not building a CMMS.

## Alternatives considered

**A. No MAR — let each connector invent asset_id.** Rejected. This is the silent drift problem. Discoverable only in production when the agent reports "two pumps."

**B. Use Maximo functional location directly as the canonical ID.** Rejected. Couples canonical identity to one vendor system. Not all customers use Maximo. SAP PM users would need a separate path.

**C. Use ISA-95 / KKS / customer naming convention as the canonical ID.** Rejected. These are human-readable strings that change when plants reorganize. We need an opaque immutable identifier.

**D. Bolt asset master onto TRS (single table).** Rejected. Mixes concerns. TRS resolves signals; MAR resolves assets. Separating them keeps each focused and matches the way connectors work.

## Consequences

**Positive:**

- The agent reasons about assets consistently across all evidence.
- The KG's root nodes match connector outputs by construction.
- Asset rename and lifecycle changes are explicit and auditable.
- Onboarding has a named, gated workflow ("import the asset master").
- Templates and budgets have a single source for class/criticality.

**Negative:**

- One more service to operate (Postgres tables, MCP server, ingestion paths).
- Onboarding is gated on having a usable asset master. Greenfield sites without one require human-curated bootstrap.
- Risk of scope creep into full master data management. Mitigated by explicit minimalism rule above.

**Neutral:**

- Adds a Postgres table with ~1k–100k rows per plant. Negligible cost.

## References

- [SPEC-011 Master Asset Registry](../mar/SPEC-011-master-asset-registry.md)
- [SPEC-003 Tag Resolution Service](../trs/SPEC-003-tag-resolution-service.md) — `signals.asset_id` is a FK to MAR
- [ADR-0001 TRS](0001-tag-resolution-service.md) — parallel pattern
- [EPIC-012 Master Asset Registry](../mar/EPIC-012-master-asset-registry.md)
