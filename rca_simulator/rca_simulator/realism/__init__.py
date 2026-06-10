"""S2.8 — Realism injection harness (imported by every simulator).

Source-side messiness so connectors exercise retry / circuit-breaker paths.
Deterministic when seeded; off (all-zero) by default in clean tests.

Modules
-------
config.py  Env-var parsing + sane defaults: SIM_CLOCK_SKEW_SECONDS, SIM_DROP_RATE,
           SIM_BAD_QUALITY_RATE, SIM_5XX_RATE, SIM_LATENCY_MEAN_MS, SIM_LATENCY_P99_MS.
inject.py  Hooks/decorators usable identically by HTTP, OPC UA, and MQTT paths:
           maybe_drop(), apply_latency(), maybe_error(), maybe_bad_quality(),
           skew_timestamp().

Ref: SPEC-007 (realism flags).
"""
