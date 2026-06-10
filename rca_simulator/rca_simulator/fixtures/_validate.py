"""S2.1 — fixture referential-integrity validator (SPEC-014).

Enforces the cross-file coherence rules that the per-file Pydantic schema cannot:
asset refs resolve, signal roles exist on the equipment template, canonical units
are valid QUDT symbols (and match the template), scenarios reference real
assets/roles, no two scenarios concurrently affect one asset, and scenario
windows stay inside the time-axis bounds.

The equipment-template signal roles and the QUDT allowlist are read as DATA files
(``data/``) — never imported from ``packages/templates`` (ADR-0012).

Error codes
-----------
ASSET_REF_UNRESOLVED            plant.yaml references an asset with no asset file
SIGNAL_ASSET_MISSING            a signal references an unknown asset
SIGNAL_ROLE_NOT_IN_TEMPLATE     a signal role is not in the equipment template
UNIT_NOT_QUDT                   canonical_units is not a known QUDT symbol
SIGNAL_UNITS_MISMATCH_TEMPLATE  canonical_units disagrees with the template role
SCENARIO_ASSET_MISSING          a scenario's affected_asset is unknown
SCENARIO_ROLE_MISSING_FOR_ASSET a scenario role has no signal on the affected asset
EVENT_SIGNAL_UNKNOWN            a scenario event references an unknown signal
SCENARIO_OVERLAP                two scenarios concurrently affect one asset
SCENARIO_OUT_OF_BOUNDS          a scenario window falls outside the time axis
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from .schema import RefPlant

_DATA = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


class FixtureValidationError(Exception):
    def __init__(self, violations: list[Violation]) -> None:
        self.violations = violations
        joined = "; ".join(f"[{v.code}] {v.message}" for v in violations)
        super().__init__(f"{len(violations)} fixture violation(s): {joined}")


def load_template_roles(path: Path | None = None) -> dict[str, str]:
    """role -> canonical_units, from the template-snapshot data file."""
    src = path or _DATA / "centrifugal_pump_signal_roles.yaml"
    data = yaml.safe_load(src.read_text())
    return {r["role"]: r["canonical_units"] for r in data["signal_roles"]}


def load_qudt_units(path: Path | None = None) -> set[str]:
    src = path or _DATA / "qudt_units.yaml"
    data = yaml.safe_load(src.read_text())
    return set(data["qudt_units"])


def validate(
    rp: RefPlant,
    template_roles: dict[str, str] | None = None,
    qudt_units: set[str] | None = None,
) -> list[Violation]:
    """Return all referential-integrity violations (empty list = clean)."""
    roles = template_roles if template_roles is not None else load_template_roles()
    qudt = qudt_units if qudt_units is not None else load_qudt_units()
    out: list[Violation] = []

    assets = set(rp.assets)
    signal_keys = set(rp.signals)

    # Rule 1 — plant asset refs resolve
    for area in rp.plant.site.areas:
        for unit in area.units:
            for eq in unit.equipment:
                if eq.asset_ref not in assets:
                    out.append(Violation(
                        "ASSET_REF_UNRESOLVED",
                        f"plant references unknown asset {eq.asset_ref!r}"))

    # Rules 2-4 + units/template match — per signal
    for key, sig in rp.signals.items():
        if sig.asset_ref not in assets:
            out.append(Violation(
                "SIGNAL_ASSET_MISSING",
                f"signal {key!r} references unknown asset {sig.asset_ref!r}"))
        if sig.role not in roles:
            out.append(Violation(
                "SIGNAL_ROLE_NOT_IN_TEMPLATE",
                f"signal {key!r} role {sig.role!r} not in equipment template"))
        if sig.canonical_units not in qudt:
            out.append(Violation(
                "UNIT_NOT_QUDT",
                f"signal {key!r} canonical_units {sig.canonical_units!r} not a QUDT symbol"))
        elif sig.role in roles and roles[sig.role] != sig.canonical_units:
            out.append(Violation(
                "SIGNAL_UNITS_MISMATCH_TEMPLATE",
                f"signal {key!r} units {sig.canonical_units!r} != template "
                f"{roles[sig.role]!r} for role {sig.role!r}"))

    # Rules 5-6 + events — per scenario
    for sid, sc in rp.scenarios.items():
        if sc.affected_asset not in assets:
            out.append(Violation(
                "SCENARIO_ASSET_MISSING",
                f"scenario {sid!r} affected_asset {sc.affected_asset!r} unknown"))
        for traj in sc.signal_trajectories:
            if f"{sc.affected_asset}.{traj.role}" not in signal_keys:
                out.append(Violation(
                    "SCENARIO_ROLE_MISSING_FOR_ASSET",
                    f"scenario {sid!r} role {traj.role!r} has no signal on "
                    f"{sc.affected_asset!r}"))
        for ev in sc.events:
            ref = ev.payload.get("signal")
            if ref is not None and ref not in signal_keys:
                out.append(Violation(
                    "EVENT_SIGNAL_UNKNOWN",
                    f"scenario {sid!r} event references unknown signal {ref!r}"))

    out.extend(_check_overlaps(rp))
    out.extend(_check_bounds(rp))
    return out


def _check_overlaps(rp: RefPlant) -> list[Violation]:
    # Rule 7 — no two scenarios concurrently affect the same asset
    out: list[Violation] = []
    by_asset: dict[str, list[tuple[str, datetime, datetime]]] = {}
    for sid, sc in rp.scenarios.items():
        end = sc.t0 + timedelta(days=sc.duration_days)
        by_asset.setdefault(sc.affected_asset, []).append((sid, sc.t0, end))
    for asset, windows in by_asset.items():
        windows.sort(key=lambda w: w[1])
        for (sid_a, _start_a, end_a), (sid_b, start_b, _end_b) in zip(windows, windows[1:]):
            if start_b < end_a:  # overlap
                out.append(Violation(
                    "SCENARIO_OVERLAP",
                    f"scenarios {sid_a!r} and {sid_b!r} both affect {asset!r} "
                    f"with overlapping windows"))
    return out


def _check_bounds(rp: RefPlant) -> list[Violation]:
    # Rule 8 — scenario window within time-axis bounds
    out: list[Violation] = []
    ta = rp.time_axis
    if ta.window_start is None or ta.window_end is None:
        return out
    for sid, sc in rp.scenarios.items():
        end = sc.t0 + timedelta(days=sc.duration_days)
        if sc.t0 < ta.window_start or end > ta.window_end:
            out.append(Violation(
                "SCENARIO_OUT_OF_BOUNDS",
                f"scenario {sid!r} window [{sc.t0.isoformat()}, {end.isoformat()}] "
                f"outside time axis"))
    return out


def validate_or_raise(
    rp: RefPlant,
    template_roles: dict[str, str] | None = None,
    qudt_units: set[str] | None = None,
) -> None:
    violations = validate(rp, template_roles, qudt_units)
    if violations:
        raise FixtureValidationError(violations)


__all__ = [
    "Violation", "FixtureValidationError",
    "validate", "validate_or_raise",
    "load_template_roles", "load_qudt_units",
]
