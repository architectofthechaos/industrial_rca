# ADR-0001: Tag Resolution Service with canonical Signal IDs

**Status: Deferred — out of Phase 1 scope. See phase1_gap_analysis.md §8.**

- **Status**: Accepted
- **Date**: 2026-06-03
- **Deciders**: gvishnu

## Context

In industrial plants, the same physical sensor is referenced by different names across systems:

- `BAY3.P101A.PT.DISCH.PV` in PI (legacy naming convention)
- `Site1/Area3/Unit1/P-101A/PressureTransmitter01/Pressure` in UNS
- `EQ-100425` in Maximo (functional location ID)
- `40PIT0103.PV` in DCS (Honeywell tag)
- `Pump P-101A Discharge Pressure` in an engineer's PDF report

If we feed these raw strings to an AI agent it will:

1. **Treat aliases as distinct signals.** The agent sees 5 pressure readings from "different" sensors when there is one physical transmitter.
2. **Misidentify rebuilt assets.** When Unit 3 is rebuilt in 2022, `BAY3.P101A.PT.DISCH.PV` is reassigned to a new physical transmitter with a different range. Historical queries Frankenstein two sensors.
3. **Cross-contaminate across sites.** `FT-101` means feedwater flow at one site and fuel gas flow at another. A multi-site corpus poisons the agent.

This is the single largest hallucination risk in our system. It must be solved at the contract layer, not by hoping the agent figures it out.

## Decision

We will build a **Tag Resolution Service (TRS)** that owns one canonical identifier per physical sensor — the **Signal ID**, a UUIDv7.

Hard rules:

1. **No MCP tool accepts a raw tag string as input** (except TRS resolution tools themselves). Every evidence tool takes one or more `SignalID` values.
2. **No raw tag string is ever placed in an LLM prompt.** Tools pass canonical `SignalDescriptor` objects to the agent: `{signal_id, role, asset, uom, range, ...}`. Raw tags appear only in provenance, never in reasoning context.
3. **Alias resolution is explicit and audited.** TRS has tools `trs.resolve_tag(string, asset_hint?, time?)` and `trs.search_signals(asset, role)`. Each resolution returns a confidence score and a mapping source (UNS authoritative, PI AF authoritative, regex heuristic, human-confirmed).
4. **Temporal validity.** Every alias has `valid_from` and `valid_to`. A query for historical data at time T uses the alias mapping valid at T, not the current mapping.
5. **Unresolved tags are an explicit state.** If TRS cannot resolve a tag with confidence ≥ threshold, the probe transitions to a `tag_confirmation_needed` HITL state. The agent does not guess.
6. **Per-tenant isolation.** Signal IDs are tenant-scoped. The TRS table has `tenant_id` as a partition key.

## Alternatives considered

**A. No TRS — pass raw tags to the agent and rely on prompt engineering.** Rejected. This is the default failure mode of every industrial AI POC. Hallucinations are inevitable and discoverable only in production.

**B. Lax TRS — tools accept raw tags but normalize internally.** Rejected. Two code paths emerge (with-canonical, without-canonical), and tool authors forget which they are in. The "without" path becomes a hallucination surface.

**C. Use UNS path as the canonical ID.** Rejected. Not all customers have a UNS. UNS paths change when plants reorganize. We need an opaque immutable identifier.

**D. Use PI AF element paths.** Rejected. Same problem — couples canonical ID to one vendor system. Also, PI AF is read-mostly; our TRS needs to be writable as new signals are discovered.

## Consequences

**Positive:**

- The agent never sees alias chaos. Hallucination surface drops dramatically.
- Audit trails are clean — every evidence row traces to a specific Signal ID.
- Simulators emit Signal IDs natively, so the simulator-to-production swap is transparent.
- Multi-site corpora can be merged without cross-contamination.
- Templates reference roles (`discharge_pressure`, `bearing_temperature`) which TRS resolves per-asset; templates are not coupled to specific tags.

**Negative:**

- Every connector ingestion path must include a tag discovery phase that populates TRS before the connector is "ready."
- TRS is a critical-path service — if it is down, no probe can run. Needs HA from MVP.
- Initial seeding requires either UNS, PI AF metadata, or a human-curated tag list. Greenfield sites without any tag discipline are higher onboarding effort.

**Neutral:**

- Adds a Postgres table with ~10k–10M rows per plant. Negligible cost.
- Adds 2–10 ms per signal resolution. Cache-able.

## References

- [SPEC-003 Tag Resolution Service](../trs/SPEC-003-tag-resolution-service.md)
- [ADR-0002 Units of Measure](0002-units-of-measure.md) — Signal descriptors carry canonical units
- [ADR-0010 Provenance](0010-provenance-and-audit.md) — raw tags appear only in provenance
