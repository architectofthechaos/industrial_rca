# SPEC-014: Simulator Fixture Schema

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0008](../adrs/0008-simulators-first.md), [0012](../adrs/0012-connectors-own-the-contract.md)
- **Related Specs**: [SPEC-007](SPEC-007-simulator-behavior.md), [SPEC-008](SPEC-008-scenario-catalog.md), [SPEC-015](SPEC-015-equipment-template-schema.md)
- **Closes gap**: G5 (simulator fixture YAML schema undefined)

## Purpose

Define the YAML schemas that describe the **reference plant** and the **scenarios** each simulator reads from. Fixtures are the single source of truth shared across all simulators — when the Maximo simulator returns a work order for P-101A, the PI simulator's time series for P-101A's pressure must agree.

## Directory layout

```
fixtures/refplant/
├── plant.yaml                 # site/area/unit/equipment hierarchy
├── assets/
│   ├── P-101A.yaml
│   ├── P-101B.yaml
│   ├── P-102A.yaml
│   └── P-103A.yaml
├── signals/
│   ├── P-101A.discharge_pressure.yaml
│   ├── P-101A.suction_pressure.yaml
│   ├── P-101A.motor_amps.yaml
│   ├── P-101A.vibration_radial.yaml
│   ├── P-101A.bearing_temp.yaml
│   └── ...
├── work_orders/
│   ├── seed_2025_q4.yaml      # baseline historical work orders
│   └── seed_2026_q1.yaml
├── documents/
│   ├── datasheets/
│   │   └── P-101A.datasheet.yaml   # metadata; PDF bytes alongside
│   ├── pids/
│   └── rca_reports/
├── scenarios/
│   ├── seal_leak_progression.yaml
│   ├── cavitation_event.yaml
│   ├── bearing_failure.yaml
│   └── motor_trip_overload.yaml
└── time_axis.yaml
```

## `plant.yaml`

```yaml
version: 1
site:
  site_id: SITE-DEMO
  name: Demo Refinery
  timezone: America/Chicago
  areas:
    - area_id: AREA-100
      name: Crude Unit
      units:
        - unit_id: UNIT-101
          name: Crude Distillation
          equipment:
            - asset_ref: P-101A    # → assets/P-101A.yaml
            - asset_ref: P-101B
        - unit_id: UNIT-102
          name: Hydrotreater Feed
          equipment:
            - asset_ref: P-102A
    - area_id: AREA-200
      name: Tank Farm
      units:
        - unit_id: UNIT-201
          name: Transfer
          equipment:
            - asset_ref: P-103A
```

## `assets/<asset_tag>.yaml`

```yaml
version: 1
asset_id_seed: 0190d3c9-...    # deterministic UUIDv7 seed so dev IDs are stable
external_ids:
  pi_af_path: \\PI-DEMO\Refinery\Crude\P-101A
  maximo_location: CRDU-P101A
  sap_equipment: 10001234
  uns_segment: crude.distillation.p101a

tag: P-101A
service: charge pump
iso14224_class: pump.centrifugal
nameplate:
  manufacturer: Sulzer
  model: AHLSTAR-A22-50
  serial: SN-2018-00471
  rated_flow_m3h: 320
  rated_head_m: 145
  rated_speed_rpm: 3550
  rated_power_kw: 185
parent_unit: UNIT-101
criticality: high
installed_at: 2018-06-12
template_class: centrifugal_pump
template_version: v0.3.1
```

## `signals/<asset_tag>.<role>.yaml`

```yaml
version: 1
asset_ref: P-101A
role: discharge_pressure        # canonical name from template
display_name: P-101A Discharge Pressure
source_systems:
  - source: pi
    raw_tag: PUMP_101A.DISCH_P
    af_attribute: \\PI-DEMO\Refinery\Crude\P-101A|DischargePressure
    units_raw: psig
  - source: uns
    raw_tag: spBv1.0/SITE-DEMO/DDATA/crude/distillation/p101a/DischargePressure
    units_raw: psig
canonical_units: kPa            # QUDT → kPa for pressure
qudt_quantity_kind: Pressure
sampling:
  expected_hz: 1.0
  stored_compression_deviation: 0.5   # psig
range:
  operating_min: 800           # kPa
  operating_max: 2000
  alarm_lo: 600
  alarm_hi: 2400
baseline:
  mean: 1450
  stddev: 35
  diurnal_amplitude: 25         # kPa, sinusoidal
```

## `scenarios/<scenario>.yaml`

This is the load-bearing fixture — drives every simulator to produce consistent data.

```yaml
version: 1
scenario_id: seal_leak_progression
description: Slow mechanical seal degradation over 30 days on P-101A
affected_asset: P-101A
failure_mode_iso14224: LEK     # leakage
duration_days: 30
t0: 2026-03-01T00:00:00Z       # scenario start in UTC; simulators offset their clocks from t0

# How signals deviate from baseline over time
signal_trajectories:
  - role: discharge_pressure
    trajectory: linear_decay
    start_offset: 0
    end_offset: -180             # kPa below baseline by end
  - role: motor_amps
    trajectory: linear_growth
    start_offset: 0
    end_offset: 8               # A above baseline (seal flush losses)
  - role: vibration_radial
    trajectory: step_then_growth
    steps:
      - at_day: 18
        offset: 1.2              # mm/s step
      - at_day: 25
        offset: 4.5

# Discrete events injected into source systems
events:
  - at_day: 5
    type: operator_log
    sink: documents
    payload:
      doc_id: NOTE-2026-03-06-001
      author: J. Operator
      text: "P-101A slight whine, watching."
  - at_day: 12
    type: alarm
    sink: alarms
    payload:
      alarm_id: ALM-2026-03-13-9912
      signal: P-101A.vibration_radial
      level: warning
      threshold: 4.0
      duration_min: 35
  - at_day: 18
    type: work_order
    sink: maximo
    payload:
      wo_number: WO-50012345
      type: corrective
      priority: 3
      problem_code: VIBR
      narrative: "Vibration trending up — inspect seal"
  - at_day: 28
    type: work_order
    sink: maximo
    payload:
      wo_number: WO-50012402
      type: corrective
      priority: 1
      problem_code: LEAK
      failure_code: LEK
      narrative: "Mechanical seal leak confirmed, plan shutdown"

# Expected RCA outcome for evaluation harness (see SPEC-009)
expected_rca:
  primary_failure_mode: mechanical_seal_failure
  root_causes:
    - dry_running_seal_face
    - insufficient_flush_flow
  must_cite_evidence:
    - signal_role: vibration_radial
    - work_order_problem_code: LEAK
    - document_keyword: "mechanical seal"
```

## `time_axis.yaml`

```yaml
version: 1
reference_time: 2026-03-01T00:00:00Z      # T0 for all scenarios
clock_skews:                              # injected per-source for realism
  pi: 0.0                                 # PI is reference
  maximo: 1.5                             # Maximo +1.5s
  sap_pm: -2.3
  opc_ua: 0.2
  uns: 0.1
  sharepoint: 0.0
```

## Validation

A `fixtures/refplant/_validate.py` script (run in CI) checks:

1. Every `asset_ref` in `plant.yaml` exists under `assets/`.
2. Every `signals/` file references an existing asset.
3. Every `signal.role` is in the asset's template `signal_roles` (see [SPEC-015](SPEC-015-equipment-template-schema.md)).
4. Every `canonical_units` is a valid QUDT unit.
5. Every scenario `affected_asset` exists.
6. Every scenario signal `role` exists for the affected asset.
7. No two scenarios concurrently affect the same asset (simulators are single-track per asset).
8. `t0 + duration_days` is within the scenario time bounds in `time_axis.yaml`.

Validation failure fails CI; simulators refuse to start on an invalid fixture.

## Versioning

- Each YAML has `version: 1` at the top.
- Adding new optional fields = minor bump in fixture set version (`fixtures/refplant/VERSION`).
- Removing or changing semantics of existing fields = major bump.
- Simulators pin to a fixture-set major version.

## Extension points

- **New equipment classes**: drop new `assets/*.yaml` and matching signals; tag with `template_class`.
- **New scenarios**: add a `scenarios/<id>.yaml` and reference an existing or new asset.
- **Tenant-specific fixtures**: a separate fixture tree per tenant, layered on top of `refplant/`.

## Test plan

1. **Validator unit tests** — golden valid fixture passes, 12 broken variants fail with specific errors.
2. **Round-trip simulator boot** — every simulator boots cleanly on `refplant/`.
3. **Cross-simulator coherence** — for `seal_leak_progression`, PI series values, Maximo work orders, alarm events all align on `t0 + offset`.
4. **Scenario isolation** — running scenario A on P-101A leaves P-101B's data untouched.

## Out of scope

- Generating fixtures from real customer data (separate post-MVP tool).
- Compressed binary fixture format (YAML is fine for MVP scale).
- Multi-plant simulations (single reference plant for MVP).
