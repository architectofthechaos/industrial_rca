"""S2.5 — OPC UA address-space mapping (pure; no server dependency).

Walks the reference-plant hierarchy and produces a deterministic plan of nodes:
one variable per signal under Site → Area → Unit → Asset folders. The asyncua
server (``server.py``) materializes this plan; keeping it pure makes the mapping
unit-testable without standing up a server.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..fixtures.schema import RefPlant


@dataclass(frozen=True)
class NodePlan:
    browse_path: tuple[str, ...]   # (site, area, unit, asset, role)
    signal_key: str                # "<tag>.<role>" into rp.signals
    identifier: str                # OPC UA string NodeId identifier (= signal_key)


def build_node_plan(rp: RefPlant) -> list[NodePlan]:
    """Deterministic node plan following plant order, signals sorted by role."""
    plans: list[NodePlan] = []
    site = rp.plant.site
    for area in site.areas:
        for unit in area.units:
            for eq in unit.equipment:
                asset = eq.asset_ref
                roles = sorted(
                    sig.role for sig in rp.signals.values()
                    if sig.asset_ref == asset
                )
                for role in roles:
                    signal_key = f"{asset}.{role}"
                    plans.append(NodePlan(
                        browse_path=(site.site_id, area.area_id, unit.unit_id, asset, role),
                        signal_key=signal_key,
                        identifier=signal_key,
                    ))
    return plans


__all__ = ["NodePlan", "build_node_plan"]
