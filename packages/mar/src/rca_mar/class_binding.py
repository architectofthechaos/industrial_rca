"""MAR-side consumption of the KG-owned ISO->KG class map (D1).

MAR resolves the dotted class to a KG-native id at registration and persists it. An unmapped
class stores NULL (the hard-fail is the KG upsert's job at probe time, not MAR's at registration).
"""
from __future__ import annotations

from rca_kg.class_map import UnknownEquipmentClass, resolve_equipment_class


def kg_class_for(dotted: str) -> str | None:
    try:
        return resolve_equipment_class(dotted)
    except UnknownEquipmentClass:
        return None


__all__ = ["kg_class_for"]
