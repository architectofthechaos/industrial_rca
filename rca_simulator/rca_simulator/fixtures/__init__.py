"""S2.1 — Shared fixture layer (BLOCKER for all simulators).

The single source of truth every simulator reads. Compiles the reference-plant
YAML + scenarios into validated objects and deterministic per-second series.

Modules
-------
schema.py             Pydantic v2 models for plant/asset/signal/scenario/time_axis
                      (per SPEC-014).
loader.py             load("fixtures/refplant/") -> fully-validated object graph;
                      raises on invalid/partial fixtures.
scenario_expander.py  Compile a scenario into a deterministic (seeded) per-second
                      series per affected signal: baseline + diurnal sine +
                      seeded noise + trajectory + injected events. Also extracts
                      discrete events keyed by sink (documents/alarms/maximo/...).
_validate.py          The 8 SPEC-014 referential-integrity rules (run in CI;
                      simulators refuse to start on an invalid fixture).

Ref: SPEC-014, SPEC-008, SPEC-015. See also memory: simulator-template-coupling.
"""
