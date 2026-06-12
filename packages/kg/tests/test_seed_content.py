"""Hermetic content checks on the KG seed cypher files (Sprint 2a Task 4).

Parses `packages/kg/seed/*.cypher` as text — no Neo4j needed. The sprint plan budgets
">=120" ontology nodes; the seed holds 122 (3 EquipmentClass + 19 FailureMode +
41 FailureMechanism + 12 MaintenanceActivity + 5 Subunit + 42 Component), and we
also assert the exact per-label counts, which is stricter.
"""
from __future__ import annotations

import re
from pathlib import Path

from rca_kg.slugs import slug

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"
ISO_TEXT = (SEED_DIR / "iso14224_bb1.cypher").read_text(encoding="utf-8")
HIERARCHY_TEXT = (SEED_DIR / "refplant_hierarchy.cypher").read_text(encoding="utf-8")

BB1_FAILURE_MODE_CODES = [
    "BRD", "ERO", "HIO", "LOO", "VIB", "LBP", "LCP", "STD", "OHE", "ELP",
    "ELU", "FOF", "INL", "NOI", "OTH", "PDE", "PLU", "SER", "UNK",
]

EXPECTED_LABEL_COUNTS = {
    "EquipmentClass": 3,
    "FailureMode": 19,
    "FailureMechanism": 42,   # +1: failure-mechanism:other generic fallback (Sprint 5 G26)
    "MaintenanceActivity": 12,
    "Subunit": 5,
    "Component": 42,
}

HIERARCHY_IDS = {
    "site:refinery-gc",
    "area:refinery-gc:area-100",
    "area:refinery-gc:area-200",
    "unit:refinery-gc:unit-101",
    "unit:refinery-gc:unit-102",
    "unit:refinery-gc:unit-201",
}


def _merged_node_ids(text: str, label: str | None = None) -> set[str]:
    pattern = rf'MERGE \(\w+:{label or r"\w+"} {{id: "([^"]+)"}}\)'
    return set(re.findall(pattern, text))


def test_seed_files_only_merge_nodes_never_create() -> None:
    for text in (ISO_TEXT, HIERARCHY_TEXT):
        assert re.search(r"\bCREATE\b", text, re.IGNORECASE) is None  # MERGE-only, idempotent
        assert "MERGE (" in text


def test_iso_seed_node_counts_per_label_and_total() -> None:
    all_ids: set[str] = set()
    for label, expected in EXPECTED_LABEL_COUNTS.items():
        ids = _merged_node_ids(ISO_TEXT, label)
        assert len(ids) == expected, f"{label}: expected {expected}, found {len(ids)}"
        all_ids |= ids
    assert len(all_ids) == sum(EXPECTED_LABEL_COUNTS.values()) == 123  # +1: G26 mechanism:other
    distinct_id_values = set(re.findall(r'id: "([^"]+)"', ISO_TEXT))
    assert len(distinct_id_values) >= 120  # sprint plan budget for ontology nodes


def test_iso_seed_has_all_19_bb1_failure_mode_codes() -> None:
    for code in BB1_FAILURE_MODE_CODES:
        assert re.search(rf'code = "{code}"', ISO_TEXT), f"missing failure-mode code {code}"
    assert len(_merged_node_ids(ISO_TEXT, "FailureMode")) == len(BB1_FAILURE_MODE_CODES)


def test_iso_seed_key_relationships_present() -> None:
    for rel in ("HAS_SUBCLASS", "HAS_SUBUNIT", "HAS_COMPONENT", "CAN_EXHIBIT",
                "CAUSED_BY", "OCCURS_IN", "REMEDIED_BY"):
        assert f"[:{rel}]" in ISO_TEXT, f"missing relationship type {rel}"


def test_hierarchy_seed_exact_ids_and_contains_edges() -> None:
    ids = set(re.findall(r'id: "([^"]+)"', HIERARCHY_TEXT))
    assert ids == HIERARCHY_IDS
    # UNWIND batching: 3 MERGE statements cover the 5 edges (site->2 areas, areas->3 units).
    assert HIERARCHY_TEXT.count("-[:CONTAINS]->") >= 3
    for child in sorted(HIERARCHY_IDS - {"site:refinery-gc"}):
        assert re.search(rf'UNWIND \[[^\]]*"{child}"', HIERARCHY_TEXT), f"no CONTAINS edge to {child}"


def test_hierarchy_unit_ids_use_shared_slug() -> None:
    for name in ("UNIT-101", "UNIT-102", "UNIT-201"):
        assert f'id: "unit:refinery-gc:{slug(name)}"' in HIERARCHY_TEXT
