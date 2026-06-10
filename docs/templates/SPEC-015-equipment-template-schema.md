# SPEC-015: Equipment Template Schema

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0001](../adrs/0001-tag-resolution-service.md), [0007](../adrs/0007-contracts-as-pydantic.md), [0011](../adrs/0011-master-asset-registry.md)
- **Closes gap**: G6 (equipment template YAML schema unspecified)

## Purpose

Define the YAML schema for **equipment templates** — the per-class knowledge artifacts that tell the agent what signals to look for, what failure modes to consider, what thresholds matter, and what evidence pattern proves each failure mode. Templates are the productized expertise. Centrifugal pump is our reference class.

A template is **versioned**, **immutable** at a version, and **tenant-overridable** via overlays (see [SPEC-010](SPEC-010-overlay-learning.md)).

## File layout

```
packages/templates/equipment_classes/
├── centrifugal_pump/
│   ├── v0.3.1.yaml             # the template at this version
│   ├── v0.3.0.yaml
│   ├── CHANGELOG.md
│   └── README.md
├── motor_induction/
│   └── v0.1.0.yaml
└── heat_exchanger_shell_and_tube/
    └── v0.1.0.yaml
```

## Schema (top-level)

```yaml
template_class: centrifugal_pump
template_version: v0.3.1
iso14224:
  taxonomy_level: 6              # equipment unit
  class_code: PU                 # ISO 14224 Table A.4
  description: "Pump - centrifugal"
supported_subtypes:
  - single_stage_overhung
  - between_bearings
  - vertical_inline

# ---- Identity and physical context the agent needs ----
nameplate_required_fields:
  - manufacturer
  - model
  - rated_flow
  - rated_head
  - rated_speed
  - rated_power

# ---- Signal roles: what the agent expects to find ----
signal_roles:
  - role: discharge_pressure
    qudt_quantity_kind: Pressure
    canonical_units: kPa
    required: true
    rationale: "Primary performance indicator; mandatory for any pump RCA."
  - role: suction_pressure
    qudt_quantity_kind: Pressure
    canonical_units: kPa
    required: true
  - role: flow
    qudt_quantity_kind: VolumeFlowRate
    canonical_units: M3-PER-HR
    required: false               # not all installations metered
  - role: motor_amps
    qudt_quantity_kind: ElectricCurrent
    canonical_units: A
    required: true
  - role: vibration_radial
    qudt_quantity_kind: Velocity
    canonical_units: MilliM-PER-SEC
    required: false
  - role: bearing_temp_de
    qudt_quantity_kind: Temperature
    canonical_units: DEG_C
    required: false
  - role: bearing_temp_nde
    qudt_quantity_kind: Temperature
    canonical_units: DEG_C
    required: false
  - role: seal_flush_flow
    qudt_quantity_kind: VolumeFlowRate
    canonical_units: L-PER-MIN
    required: false

# ---- Default operating-window context ----
default_lookback:
  routine_check: PT24H
  alarm_triggered: P7D
  seal_or_bearing_concern: P30D
  performance_drift: P90D

# ---- Failure modes (the prior belief space) ----
failure_modes:
  - id: mechanical_seal_failure
    iso14224_code: LEK             # leakage
    prior_probability: 0.28        # marginal across pump fleet
    description: "Loss of seal integrity, evidenced by leakage and/or flush flow loss."
    evidence_recipe:
      strong_positive:
        - signal: seal_flush_flow
          condition: "drop > 50%"
        - work_order:
            problem_code: LEAK
            within: P90D
        - document:
            keywords: ["seal leak", "mechanical seal", "flush"]
      supporting_positive:
        - signal: motor_amps
          condition: "rising trend, > +5%"
        - alarm:
            tag_role: vibration_radial
            level: warning
      refuting:
        - work_order:
            problem_code: BEAR    # bearing problem suggests different mode
            within: P30D

  - id: cavitation
    iso14224_code: VIB             # vibration (per ISO mapping convention)
    prior_probability: 0.18
    description: "Vapor bubble collapse from insufficient NPSH."
    evidence_recipe:
      strong_positive:
        - signal: suction_pressure
          condition: "drop > 20% with high vibration"
        - signal: vibration_radial
          condition: "spectral peak at vane-pass frequency"
      supporting_positive:
        - signal: flow
          condition: "erratic, > ±15% swing"
        - document:
            keywords: ["cavitation", "NPSH"]
      refuting:
        - signal: suction_pressure
          condition: "stable within normal band"

  - id: bearing_failure
    iso14224_code: VIB
    prior_probability: 0.22
    description: "Rolling element or sleeve bearing degradation."
    evidence_recipe:
      strong_positive:
        - signal: bearing_temp_de
          condition: "rise > 15°C above baseline"
        - signal: vibration_radial
          condition: "high-frequency content rising"
        - work_order:
            problem_code: BEAR
            within: P180D
      supporting_positive:
        - signal: motor_amps
          condition: "creeping upward"
      refuting:
        - signal: seal_flush_flow
          condition: "abnormal"  # points to seal not bearing

  - id: motor_electrical
    iso14224_code: ELE
    prior_probability: 0.12
    description: "Motor overload, ground fault, winding insulation."
    evidence_recipe:
      strong_positive:
        - alarm:
            tag_role: motor_amps
            level: trip
        - work_order:
            problem_code: ELEC
            within: P30D
      supporting_positive:
        - signal: motor_amps
          condition: "spike > 130% rated"

  - id: impeller_wear_or_damage
    iso14224_code: ERO              # erosion
    prior_probability: 0.10
    description: "Impeller wear, erosion, or fouling reducing head."
    evidence_recipe:
      strong_positive:
        - signal: discharge_pressure
          condition: "sustained drop > 10% with rated suction"
      supporting_positive:
        - signal: motor_amps
          condition: "below baseline"

  - id: misalignment_or_imbalance
    iso14224_code: VIB
    prior_probability: 0.10
    description: "Coupling misalignment or impeller imbalance."
    evidence_recipe:
      strong_positive:
        - signal: vibration_radial
          condition: "1x running speed dominant"

# Prior probabilities must sum to ≤ 1.0; the residual is "other / unknown".

# ---- Methodology scaffolds ----
method_templates:
  default: 5_whys
  available: [5_whys, fishbone, fta, proact]

# ---- Tier budgets ----
tier_budgets:
  scope_max_seconds: 30
  evidence_max_seconds: 180
  reason_max_seconds: 240
  govern_max_seconds: 30
  total_max_usd: 1.20             # token + tool cost ceiling per probe

# ---- HITL gates ----
hitl_gates:
  - after: scope
    required_when: ambiguous_asset OR multi_tenant_blast_radius
  - after: reason
    required_when: always
  - after: govern
    required_when: cmms_writeback

# ---- Overlay surface (what tenants can override; see SPEC-010) ----
overlay_allowed_fields:
  - failure_modes[].prior_probability
  - failure_modes[].evidence_recipe[].condition  # thresholds only
  - default_lookback
  - tier_budgets
overlay_forbidden_fields:
  - signal_roles
  - failure_modes[].id
  - failure_modes[].iso14224_code
  - hitl_gates
```

## Pydantic contract

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field, condecimal
from decimal import Decimal

QudtUnit = str

class SignalRole(BaseModel):
    role: str                     # e.g. "discharge_pressure"
    qudt_quantity_kind: str
    canonical_units: QudtUnit
    required: bool
    rationale: Optional[str] = None

class EvidenceCriterion(BaseModel):
    signal: Optional[str] = None
    work_order: Optional[dict] = None
    document: Optional[dict] = None
    alarm: Optional[dict] = None
    condition: Optional[str] = None
    within: Optional[str] = None   # ISO 8601 duration

class EvidenceRecipe(BaseModel):
    strong_positive: list[EvidenceCriterion] = Field(default_factory=list)
    supporting_positive: list[EvidenceCriterion] = Field(default_factory=list)
    refuting: list[EvidenceCriterion] = Field(default_factory=list)

class FailureMode(BaseModel):
    id: str
    iso14224_code: str
    prior_probability: condecimal(ge=Decimal("0"), le=Decimal("1"))
    description: str
    evidence_recipe: EvidenceRecipe

class EquipmentTemplate(BaseModel):
    template_class: str
    template_version: str
    iso14224: dict
    supported_subtypes: list[str]
    nameplate_required_fields: list[str]
    signal_roles: list[SignalRole]
    default_lookback: dict[str, str]
    failure_modes: list[FailureMode]
    method_templates: dict
    tier_budgets: dict
    hitl_gates: list[dict]
    overlay_allowed_fields: list[str]
    overlay_forbidden_fields: list[str]
```

## Validation rules

1. `template_version` matches semver-ish `vMAJOR.MINOR.PATCH`.
2. `failure_modes[].id` unique within template.
3. Sum of `prior_probability` ≤ 1.0.
4. Every `EvidenceCriterion.signal` references a `signal_roles[].role`.
5. Every `canonical_units` is a known QUDT unit symbol.
6. `default_lookback` values parse as ISO 8601 durations.
7. `overlay_allowed_fields` and `overlay_forbidden_fields` are disjoint.

Validation runs in CI and at template-service startup.

## Versioning policy

- **PATCH** — threshold tuning, prior tweaks, doc edits. No agent code changes.
- **MINOR** — new failure mode, new optional signal role, new method template. Backward compatible.
- **MAJOR** — removing/renaming a signal role, changing an `iso14224_code`, restructuring schema.

Tenants pin to a `(class, version)` pair per asset class. Upgrading requires re-running the Stage 5 smoke test from [SPEC-013](SPEC-013-tenant-onboarding.md).

## Tooling

| Tool | Purpose |
|---|---|
| `templates.load` | Load `(class, version)` and return `EquipmentTemplate`. |
| `templates.list_versions` | List available versions for a class. |
| `templates.diff` | Show diff between two versions of a template. |
| `templates.validate` | Validate a candidate YAML against the Pydantic schema. |

## Test plan

1. Schema golden file — `centrifugal_pump/v0.3.1.yaml` parses, validates, round-trips.
2. Validator unit tests — 15 mutated copies fail with specific error codes.
3. Overlay compatibility — apply allowed overrides; verify forbidden ones are rejected.
4. Evidence recipe smoke test — agent can resolve every `signal` reference to a `SignalID` on the reference plant.

## Out of scope

- Automated template synthesis from historical RCA data (post-MVP — see [SPEC-010](SPEC-010-overlay-learning.md) overlays for the closest in-MVP capability).
- Cross-class composite templates (e.g., pump+motor unit). Each subsystem has its own template for MVP.
- Localization of `description` / `rationale` text.
