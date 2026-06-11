"""KgHierarchyWriter tests (Sprint 2b Task 11): InMemory idempotency + live Neo4j skip-if-down.

The onboarding pipeline upserts crawled Site/Area/Unit nodes through this port; the headline
guarantee is idempotency — a re-run with no source change adds zero nodes/edges. The InMemory
writer proves that via its ``write_count`` counter; the live test (skipped if Neo4j is down)
proves the same against real Cypher by counting nodes before/after a second upsert.
"""
from __future__ import annotations

import pytest
from conftest import requires_kg

from rca_kg.write import InMemoryHierarchyWriter, Neo4jHierarchyWriter

_NODES = [
    {"id": "site:test-plant", "label": "Site", "name": "Test Plant",
     "plant_id": "test-plant", "parent_id": None},
    {"id": "area:test-plant:area-100", "label": "Area", "name": "AREA-100",
     "plant_id": "test-plant", "parent_id": "site:test-plant"},
    {"id": "unit:test-plant:unit-101", "label": "Unit", "name": "UNIT-101",
     "plant_id": "test-plant", "parent_id": "area:test-plant:area-100"},
]


async def test_inmemory_upsert_is_idempotent() -> None:
    writer = InMemoryHierarchyWriter()
    assert await writer.upsert_hierarchy_nodes(_NODES) == 3
    assert len(writer.nodes) == 3
    assert writer.edges == {
        ("site:test-plant", "area:test-plant:area-100"),
        ("area:test-plant:area-100", "unit:test-plant:unit-101"),
    }
    after_first = writer.write_count  # 3 nodes + 2 edges = 5 actual writes

    # Second, identical upsert: still returns 3 (nodes presented) but writes NOTHING new.
    assert await writer.upsert_hierarchy_nodes(_NODES) == 3
    assert writer.write_count == after_first
    assert len(writer.nodes) == 3
    assert len(writer.edges) == 2


async def test_inmemory_rejects_non_hierarchy_label() -> None:
    writer = InMemoryHierarchyWriter()
    with pytest.raises(ValueError, match="not writable"):
        await writer.upsert_hierarchy_nodes(
            [{"id": "asset:x", "label": "EquipmentClass", "name": "x", "plant_id": "p"}])


@requires_kg
async def test_neo4j_upsert_is_idempotent() -> None:
    from rca_kg.config import kg_database, make_async_driver

    driver = make_async_driver()
    writer = Neo4jHierarchyWriter(driver=driver, database=kg_database())
    try:
        async with driver.session(database=kg_database()) as s:
            await s.run("MATCH (n) WHERE n.plant_id = 'test-plant' DETACH DELETE n")

        async def _count() -> int:
            async with driver.session(database=kg_database()) as s:
                res = await s.run("MATCH (n) WHERE n.plant_id = 'test-plant' RETURN count(n) AS c")
                rec = await res.single()
                return rec["c"]

        assert await writer.upsert_hierarchy_nodes(_NODES) == 3
        first = await _count()
        assert first == 3
        assert await writer.upsert_hierarchy_nodes(_NODES) == 3
        assert await _count() == first  # re-run adds zero nodes
        async with driver.session(database=kg_database()) as s:
            await s.run("MATCH (n) WHERE n.plant_id = 'test-plant' DETACH DELETE n")
    finally:
        await writer.aclose()
