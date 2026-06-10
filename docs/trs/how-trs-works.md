# How the Tag Resolution Service (TRS) works

**Status: Deferred — out of Phase 1 scope. See phase1_gap_analysis.md §8.**

A walk-through of the part of the system that confuses people most: how we keep an AI agent from confusing 5 names for the same sensor with 5 different sensors.

> **Spec reference**: [SPEC-003](SPEC-003-tag-resolution-service.md). This document explains the *why*; the spec defines the *what*.

## The problem in one paragraph

In an industrial plant, the same physical pressure transmitter might be called `BAY3.P101A.PT.DISCH.PV` in PI, `Site1/Area3/Unit1/P-101A/PressureTransmitter01/Pressure` in UNS, `MP-44521` in Maximo, `40PIT0103.PV` in the DCS, and "P-101A discharge pressure" in an engineer's PDF. If we feed those 5 strings to an AI agent, it sees 5 sensors. It will reason about them as if they're independent. It will hallucinate.

## The setup — pretend you're a new customer

Acme Refinery just bought our RCA product. They have:
- A PI Historian with 50,000 tags
- A Maximo CMMS with 8,000 assets
- A UNS broker publishing Sparkplug B messages
- A bunch of engineer PDFs in SharePoint

Day 1 — we connect. Now what?

## TRS is populated by a "discovery phase" — once per source, **before** any probe

Think of it like indexing a library before you let people search. We don't run probes until TRS knows the plant.

```
Connect source → Discovery sweep → TRS populated → Now probes can run
```

This happens **per connector, per tenant**, usually during onboarding week. After that, discovery runs incrementally — new tags appear, we ingest them.

> Aside: discovery for assets (MAR) runs *before* discovery for signals (TRS). See [how-mar-works.md](how-mar-works.md). The reason: signals belong to assets, so we need the assets first.

## How discovery works — three paths, ranked by trust

We try the highest-trust path first. Whatever we learn goes into TRS.

### Path 1 — UNS BIRTH messages (gold standard, when available)

UNS publishes "BIRTH" messages that look like this:

```json
{
  "metric": "Site1/Area3/Unit1/P-101A/PressureTransmitter01/Pressure",
  "type": "Float",
  "unit": "barg",
  "alias": 42
}
```

This message tells us **everything we need**:
- Asset: `P-101A` (parsed from path; we look it up in MAR)
- Role: `discharge_pressure` (mapped from `PressureTransmitter01/Pressure` via convention)
- Unit: `barg` → we convert to QUDT URI for pascals + `pressure_reference=gauge`
- Source system: `uns`
- Raw tag: the full path

We create a row in `signals` and a row in `signal_aliases` with `mapping_source='uns_authoritative'`, `confidence=1.0`.

**Done. This sensor is canonically resolved.**

### Path 2 — PI AF (PI Asset Framework) browse

PI AF is essentially a structured database of "this PI tag = this physical thing on this asset." We walk it:

```
PI AF Element: P-101A (pump)
  └── Attribute: DischargePressure
        ├── DataReference: PI Point "BAY3.P101A.PT.DISCH.PV"
        └── UnitOfMeasure: "psi"
```

Same outcome — we create (or extend) a signal + alias with `confidence=0.95`. Slightly lower than UNS because AF metadata is sometimes stale.

### Path 3 — regex heuristic (last resort)

Some plants have neither UNS nor clean AF. They just have raw PI tags following a naming convention. We configure a regex per tenant:

```regex
^BAY(?P<bay>\d+)\.P(?P<pump>\d+)(?P<train>[AB])\.(?P<sensor>PT|TT|FT|VT)\.(?P<location>DISCH|SUCT|BRG|MOT)\.PV$
```

Run it against `BAY3.P101A.PT.DISCH.PV`:
- bay=3, pump=101, train=A → asset = `P-101A`
- sensor=PT (pressure transmitter), location=DISCH → role = `discharge_pressure`

We create a signal + alias with `confidence=0.7` — lower, because it's a guess based on convention.

## How do we know two tags are the **same** physical sensor?

This is the magic moment. During discovery we encounter:

**From UNS:** `Site1/Area3/Unit1/P-101A/PressureTransmitter01/Pressure`
**From PI AF:** PI tag `BAY3.P101A.PT.DISCH.PV` on AF element `P-101A`, attribute `DischargePressure`
**From Maximo:** Measurement point `MP-44521` on functional location `EQ-100425` (which MAR tells us is `P-101A`)

All three describe **the same physical pressure transmitter**.

### Matching rule — match on `(asset_id, role)`

```
For each incoming alias from discovery:
  1. Identify the asset → get asset_id from MAR (e.g., P-101A → UUID 7f3e...)
  2. Identify the role  → 'discharge_pressure'
  3. Look up signals WHERE asset_id=7f3e... AND role='discharge_pressure'
  4. Found one? → Attach this alias to it (same signal_id)
     Not found? → Create a new signal, then attach the alias
```

So the **canonical identity is `(asset_id, role)`**. The first source to discover this sensor creates the `signal_id`. Every subsequent source that finds the same `(asset_id, role)` attaches its raw tag as a new alias to that same `signal_id`.

After discovery, our tables look like this:

**signals**

| signal_id | asset_id | role | qudt_unit | pressure_ref |
|---|---|---|---|---|
| `sig-abc-123` | `P-101A` (UUID) | discharge_pressure | Pa | gauge |

**signal_aliases**

| signal_id | source_system | raw_tag | confidence |
|---|---|---|---|
| sig-abc-123 | uns | `Site1/Area3/.../Pressure` | 1.0 |
| sig-abc-123 | pi | `BAY3.P101A.PT.DISCH.PV` | 0.95 |
| sig-abc-123 | maximo | `MP-44521` | 0.9 |

**One physical sensor. One signal_id. Three aliases. The agent only ever sees `sig-abc-123` and the SignalDescriptor that wraps it.**

## What we explicitly do NOT do

**Value correlation.** We do *not* say "these two tags have the same time series therefore they're the same sensor." This path is full of false positives — two pumps in parallel service have nearly identical traces. We rely on structured identifiers and humans as the tiebreaker, not value math.

**Best-guess fuzzy matching at probe time.** If a tag wasn't discovered during onboarding and a probe encounters it, we do not have the agent improvise. We pause the probe with a `tag_confirmation_needed` HITL gate. The probe never guesses.

## What happens when discovery is incomplete

Onboarding is rarely perfect on day one. Three things can happen during a probe:

**Case 1 — fully resolved.** All tags the probe needs are in `signal_aliases`. The probe never blocks on TRS.

**Case 2 — low confidence (e.g., regex match at 0.7).** The probe pauses, the human confirms or corrects. After confirmation, the alias is upgraded to `human_confirmed` (confidence 1.0), and the probe resumes.

**Case 3 — totally unknown.** Tag string is not in `signal_aliases` at all. We insert it into `signal_alias_unresolved`, increment the occurrence counter, and pause the probe for HITL. The unresolved queue also surfaces in the admin UI so operators can clean it up between probes.

In every case, **the agent never invents a mapping**. If TRS can't resolve, a human resolves.

## Re-builds and renames

When a plant rebuilds Unit 3 in 2024 and re-uses tag `BAY3.P101A.PT.DISCH.PV` for a new physical transmitter with different range and calibration:

1. The old alias gets `valid_to = 2024-03-15T08:00:00Z` (the cutover time).
2. A new signal is created (it's a different physical sensor).
3. A new alias is created with `valid_from = 2024-03-15T08:00:00Z` pointing to the new signal.

When a probe in 2023 asks for that tag, TRS resolves at the probe's query time and returns the old signal. When a probe in 2025 asks, it gets the new signal. **History is not Frankenstein-ed.**

## Mental model — library catalog

- **Discovery phase** = cataloging the books. Done once when you open the library. Updated as new books arrive.
- **Probes** = readers asking for books. They use the catalog, they don't re-catalog.
- **Tag aliases** = the same book having different names in different card-catalog systems (Dewey, ISBN, library sticker).
- **Canonical signal_id** = the actual physical book on the shelf.
- **Unresolved queue** = a librarian's "huh, never seen this" pile.

## The honest summary

We use three signals, ranked, to decide that two tags are the same physical sensor:

1. **Authoritative metadata** (UNS path or PI AF element + attribute encodes asset + role).
2. **Convention match** (regex extracts the same asset + role).
3. **Human confirmation** (the HITL queue resolved an unknown).

We never use value correlation. We never let the agent guess. Everything is auditable through aliases, provenance, and the audit log.

## Where to go next

- Reference schema and resolution algorithm: [SPEC-003](SPEC-003-tag-resolution-service.md)
- The asset side of this same pattern: [how-mar-works.md](how-mar-works.md)
- The decision and trade-offs: [ADR-0001](../adrs/0001-tag-resolution-service.md)
