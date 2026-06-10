# ADR-0002: QUDT ontology and canonical SI units

- **Status**: Accepted
- **Date**: 2026-06-03
- **Deciders**: gvishnu

## Context

Units in industrial source systems are inconsistent, incomplete, and frequently wrong:

- PI tags carry an `EngineeringUnits` string that is free-text: `"psi"`, `"PSI"`, `"psig"`, `"pounds per square inch"`, `""` (blank), or sometimes the units of a different tag.
- Maximo has its own unit codes (`PSI`, `BAR`, `MPA`) often without a reference type.
- SAP PM uses ISO 80000 codes inconsistently.
- DCS exports often strip units entirely, assuming the engineer "knows."
- Engineer PDFs use whatever was convenient at the time.

The critical failure case is **pressure reference confusion**: a threshold of "discharge pressure > 20 bar" means very different things if one feed is `barg` (gauge) and another is `bara` (absolute). For a vacuum service this can be the difference between "normal" and "process upset."

## Decision

1. **QUDT as the canonical ontology.** Every signal has a `qudt_unit` URI (e.g., `http://qudt.org/vocab/unit/PA` for pascals). Reasons over UCUM: better industrial coverage, used by ISO 15926 / CFIHOS, has explicit reference-type for gauge/absolute pressure.
2. **Canonical SI internally.** All numeric values stored, transmitted, and reasoned over in SI base or derived units:
   - Pressure: pascals (`Pa`), with explicit `pressure_reference` enum (`absolute` | `gauge` | `differential`)
   - Temperature: kelvin (`K`)
   - Flow (mass): kg/s
   - Flow (volumetric): m³/s
   - Length: meters
   - Time: seconds (or ISO 8601 for absolute instants)
   - Speed: m/s
   - Power: watts
3. **Original unit captured in provenance.** Every measurement row records `original_value`, `original_unit`, `canonical_value`, `canonical_unit`, `conversion_source`.
4. **Conversion library refuses ambiguous conversions.** `psi → Pa` is fine. `psig → Pa` requires an absolute atmospheric reference; the converter either uses a registered site atmospheric pressure or **refuses** and surfaces a `unit_conversion_ambiguous` error to the probe.
5. **Pressure reference type is a first-class field on every pressure signal**, not embedded in a unit string. Tag discovery must determine it; if undetermined, the signal is flagged for human review before use.
6. **Presentation layer converts back for humans.** Cause map rendering and CMMS write-back use customer-preferred units (per tenant). The agent never sees non-SI.

## Alternatives considered

**A. UCUM only.** Rejected. UCUM is precise for healthcare and physics but weaker on industrial conventions like `barg` and `Nm³` (normal cubic meters at standard conditions).

**B. Pint (Python library) as the source of truth.** Rejected as ontology. Pint is excellent as a runtime conversion engine but does not provide stable URIs for cross-system semantic interop. We can use Pint *under* QUDT.

**C. Store in original units, convert at query time.** Rejected. Doubles the conversion attack surface — every consumer must convert correctly. Centralizing on canonical-at-ingest fails fast at the boundary.

**D. Per-customer unit preferences as canonical.** Rejected. Different customers have different preferences; canonical must be one thing.

## Consequences

**Positive:**

- The agent reasons in one consistent unit system. No "wait, was that psi or bar?" errors.
- Thresholds in templates are unambiguous (pressure values always Pa, pressure_reference always explicit).
- Multi-site benchmarking is meaningful — comparing OREDA data to customer data does not require per-comparison conversion.
- QUDT URIs give us a path to CFIHOS / ISO 15926 alignment later.

**Negative:**

- Every connector must implement unit parsing and conversion. The PI parser in particular needs a maintained mapping of common free-text variants (`"psi"` → QUDT URI).
- Engineer-facing UIs must always convert for display; engineers will not accept seeing pascals.
- Ambiguous-unit failures are user-visible during onboarding and require human curation before probes can run on those signals.

**Neutral:**

- Adds ~50 LOC of unit metadata to each `SignalDescriptor`.

## References

- QUDT: https://qudt.org
- Pint (runtime conversion): https://pint.readthedocs.io
- [SPEC-001 Evidence Bundle](../foundations/SPEC-001-evidence-bundle.md) — measurement row schema
- [ADR-0001 TRS](0001-tag-resolution-service.md) — Signal descriptors carry units
