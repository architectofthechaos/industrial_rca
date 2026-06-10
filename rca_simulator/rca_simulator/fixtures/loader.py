"""S2.1 — fixture loader.

``load(path)`` parses a reference-plant fixture tree into a fully-validated
:class:`RefPlant`. It raises (pydantic ``ValidationError`` or ``FileNotFoundError``)
rather than ever returning partial data, so a broken fixture fails loudly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .schema import (
    Asset,
    Plant,
    RefPlant,
    Scenario,
    Signal,
    TimeAxis,
    WorkOrderSeed,
)


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping, got {type(data).__name__}")
    return data


def _yaml_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.yaml"))


def load(path: str | Path) -> RefPlant:
    """Load and validate the fixture tree rooted at ``path``."""
    root = Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f"fixture directory not found: {root}")

    version_file = root / "VERSION"
    if not version_file.is_file():
        raise FileNotFoundError(f"missing VERSION file: {version_file}")
    fixture_version = version_file.read_text().strip()

    plant = Plant.model_validate(_read_yaml(root / "plant.yaml"))
    time_axis = TimeAxis.model_validate(_read_yaml(root / "time_axis.yaml"))

    assets: dict[str, Asset] = {}
    for f in _yaml_files(root / "assets"):
        asset = Asset.model_validate(_read_yaml(f))
        assets[asset.tag] = asset

    signals: dict[str, Signal] = {}
    for f in _yaml_files(root / "signals"):
        sig = Signal.model_validate(_read_yaml(f))
        signals[f"{sig.asset_ref}.{sig.role}"] = sig

    scenarios: dict[str, Scenario] = {}
    for f in _yaml_files(root / "scenarios"):
        sc = Scenario.model_validate(_read_yaml(f))
        scenarios[sc.scenario_id] = sc

    work_orders = [
        WorkOrderSeed.model_validate(_read_yaml(f))
        for f in _yaml_files(root / "work_orders")
    ]

    return RefPlant(
        fixture_version=fixture_version,
        plant=plant,
        assets=assets,
        signals=signals,
        scenarios=scenarios,
        time_axis=time_axis,
        work_orders=work_orders,
    )
