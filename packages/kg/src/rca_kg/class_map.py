"""KG-owned ISO-14224 dotted-class -> KG node-id export (D1).

Ontology truth lives in the KG seed. MAR consumes this map at asset registration so the
agent only ever hands the KG a native ``equipment-class:*`` id. The map is parsed from the
seed cypher (no live Neo4j dependency, so MAR registration stays decoupled from the graph).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_SEED = Path(__file__).resolve().parent.parent.parent / "seed" / "iso14224_bb1.cypher"
_ID = re.compile(r'MERGE\s*\(n:EquipmentClass\s*\{id:\s*"(?P<id>[^"]+)"\}\)(?P<body>[^;]*);',
                 re.IGNORECASE | re.DOTALL)
_DOTTED = re.compile(r'n\.dotted\s*=\s*"(?P<dotted>[^"]+)"', re.IGNORECASE)


class UnknownEquipmentClass(ValueError):
    """A dotted ISO class with no matching EquipmentClass node in the KG seed."""


@lru_cache(maxsize=1)
def iso_to_kg_map() -> dict[str, str]:
    text = _SEED.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in _ID.finditer(text):
        dotted = _DOTTED.search(m.group("body"))
        if dotted:
            out[dotted.group("dotted")] = m.group("id")
    if not out:
        raise RuntimeError(f"no dotted EquipmentClass aliases found in {_SEED}")
    return out


def resolve_equipment_class(dotted: str) -> str:
    try:
        return iso_to_kg_map()[dotted]
    except KeyError as exc:
        raise UnknownEquipmentClass(
            f"no KG EquipmentClass for ISO class {dotted!r}; "
            f"known: {sorted(iso_to_kg_map())}") from exc


__all__ = ["iso_to_kg_map", "resolve_equipment_class", "UnknownEquipmentClass"]
