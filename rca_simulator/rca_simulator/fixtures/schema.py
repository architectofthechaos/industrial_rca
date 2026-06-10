"""S2.1 — Pydantic v2 models for the reference-plant fixture YAML (SPEC-014).

These describe the shared fixture tree every simulator reads. ``extra='forbid'``
is deliberate: unknown keys in a fixture file are almost always typos and should
fail loudly. Timestamps must be timezone-aware (UTC) per ADR-0006.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- plant.yaml ----------

class EquipmentRef(_Base):
    asset_ref: str


class Unit(_Base):
    unit_id: str
    name: str
    equipment: list[EquipmentRef] = Field(default_factory=list)


class Area(_Base):
    area_id: str
    name: str
    units: list[Unit] = Field(default_factory=list)


class Site(_Base):
    site_id: str
    name: str
    timezone: str
    areas: list[Area] = Field(default_factory=list)


class Plant(_Base):
    version: int
    site: Site


# ---------- assets/<tag>.yaml ----------

class Nameplate(_Base):
    manufacturer: str
    model: str
    serial: str
    rated_flow_m3h: float
    rated_head_m: float
    rated_speed_rpm: float
    rated_power_kw: float


class Asset(_Base):
    version: int
    asset_id_seed: str
    external_ids: dict[str, Any] = Field(default_factory=dict)
    tag: str
    service: str
    iso14224_class: str
    nameplate: Nameplate
    parent_unit: str
    criticality: str
    installed_at: date
    template_class: str
    template_version: str


# ---------- signals/<tag>.<role>.yaml ----------

class SignalSourceSystem(_Base):
    source: str
    raw_tag: str
    af_attribute: str | None = None
    units_raw: str


class Sampling(_Base):
    expected_hz: float
    stored_compression_deviation: float | None = None


class SignalRange(_Base):
    operating_min: float
    operating_max: float
    alarm_lo: float
    alarm_hi: float


class Baseline(_Base):
    mean: float
    stddev: float
    diurnal_amplitude: float = 0.0


class Signal(_Base):
    version: int
    asset_ref: str
    role: str
    display_name: str
    source_systems: list[SignalSourceSystem] = Field(default_factory=list)
    canonical_units: str
    qudt_quantity_kind: str
    sampling: Sampling
    range: SignalRange
    baseline: Baseline


# ---------- scenarios/<id>.yaml ----------

TrajectoryKind = Literal[
    "linear_decay", "linear_growth", "step_then_growth", "constant"
]


class TrajectoryStep(_Base):
    at_day: float
    offset: float


class SignalTrajectory(_Base):
    role: str
    trajectory: TrajectoryKind
    start_offset: float = 0.0
    end_offset: float = 0.0
    steps: list[TrajectoryStep] = Field(default_factory=list)


class ScenarioEvent(_Base):
    at_day: float
    type: str
    sink: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ExpectedRca(_Base):
    primary_failure_mode: str
    root_causes: list[str] = Field(default_factory=list)
    must_cite_evidence: list[dict[str, Any]] = Field(default_factory=list)


class Scenario(_Base):
    version: int
    scenario_id: str
    description: str
    affected_asset: str
    failure_mode_iso14224: str
    duration_days: float
    t0: AwareDatetime
    signal_trajectories: list[SignalTrajectory] = Field(default_factory=list)
    events: list[ScenarioEvent] = Field(default_factory=list)
    expected_rca: ExpectedRca | None = None


# ---------- time_axis.yaml ----------

class TimeAxis(_Base):
    version: int
    reference_time: AwareDatetime
    window_start: AwareDatetime | None = None      # scenario time-bound lower (rule #8)
    window_end: AwareDatetime | None = None        # scenario time-bound upper (rule #8)
    clock_skews: dict[str, float] = Field(default_factory=dict)


# ---------- work_orders/<seed>.yaml ----------

class WorkOrderSeed(_Base):
    version: int
    work_orders: list[dict[str, Any]] = Field(default_factory=list)


# ---------- assembled object graph (returned by the loader) ----------

class RefPlant(_Base):
    """The fully-validated fixture object graph for one plant."""

    fixture_version: str
    plant: Plant
    assets: dict[str, Asset]
    signals: dict[str, Signal]            # key: "<tag>.<role>"
    scenarios: dict[str, Scenario]
    time_axis: TimeAxis
    work_orders: list[WorkOrderSeed] = Field(default_factory=list)


__all__ = [
    "EquipmentRef", "Unit", "Area", "Site", "Plant",
    "Nameplate", "Asset",
    "SignalSourceSystem", "Sampling", "SignalRange", "Baseline", "Signal",
    "TrajectoryKind", "TrajectoryStep", "SignalTrajectory", "ScenarioEvent",
    "ExpectedRca", "Scenario",
    "TimeAxis", "WorkOrderSeed", "RefPlant",
]
