# SPEC-008: Scenario Catalog

- **Status**: Draft
- **Owner**: gvishnu

## Purpose

The scenario catalog is the seed data for simulators *and* the evaluation harness. Each scenario is a known failure with known evidence and known correct outcome.

## MVP scenarios (centrifugal pump)

### 1. `seal_leak_progression`
- Asset: P-101A (charge pump)
- Failure mode: ISO 14224 `ELP` (external leakage, process)
- Mechanism: mechanical seal wear
- Timeline: T0–T-30d normal; T-15d seal flush pressure trending down; T-3d seepage visible; T0 high-priority WO opened.
- Expected outcome: top candidate `ELP` with confidence > 0.8; root cause "seal face wear due to abrasive service"; corrective action "replace seal cartridge, review flush plan."

### 2. `cavitation_event`
- Asset: P-101B (BFW pump)
- Failure mode: ISO 14224 `VIB` (vibration) with underlying mechanism cavitation
- Timeline: T-6h suction pressure drops below NPSHr; T-4h vibration RMS rises; T-30m discharge pressure oscillating; T0 trip on vibration high-high.
- Expected outcome: top candidate `VIB` with mechanism cavitation; root cause "upstream strainer plugged" (matching simulated WO history).

### 3. `bearing_failure`
- Asset: P-102A (injection pump)
- Failure mode: ISO 14224 `VIB` with mechanism bearing wear
- Timeline: T-30d baseline; T-10d 1×RPM peak grows in spectrum; T-2d temperature rises; T0 trip.
- Expected outcome: top `VIB`, bearing wear identified from spectral signature; corrective "replace DE bearing, check alignment."

### 4. `motor_trip_overload`
- Asset: P-103A (transfer pump)
- Failure mode: ISO 14224 `STP` (spurious stop) with electrical root cause
- Timeline: T-15m motor current rising during reduced flow; T0 overload trip.
- Expected outcome: top `STP`; root cause "process upset causing motor overload"; corrective action "review process operating envelope."

## Scenario YAML schema

```yaml
scenario_id: seal_leak_progression
version: 1
asset_id: <UUID for P-101A>
failure_mode_iso14224: ELP
mechanism: mechanical_seal_wear
timeline:
  - t_offset: -30d
    type: baseline_operating
  - t_offset: -15d
    type: signal_trend
    signal_role: seal_flush_pressure
    trend: linear_decrease
    end_value_pct: 70
  - t_offset: -3d
    type: visual_observation
    document: operator_log_2026-05-21.pdf
  - t_offset: 0
    type: work_order_opened
    priority: high
    failure_code: ELP
expected_outcome:
  top_candidate: ELP
  min_confidence: 0.8
  root_cause: seal_face_wear_abrasive_service
  corrective_actions:
    - replace_seal_cartridge
    - review_flush_plan
```

## Eval harness usage

The evaluation harness runs every scenario as a probe and checks:
- Top candidate matches expected
- Confidence above minimum
- Root cause text contains expected key phrases (semantic similarity)
- Corrective actions overlap with expected set

Regressions surface in CI on PR.

## Expansion plan

Beyond MVP, add scenarios for other equipment classes (recip compressor, valve, exchanger) as those templates ship.
