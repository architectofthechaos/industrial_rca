"""KG hierarchy-upsert write port (Sprint 2b Task 11 — onboarding projection).

The onboarding pipeline projects crawled Site/Area/Unit nodes into the KG via the
``KgHierarchyWriter`` seam (read access keeps living behind ``queries.KgGateway``).
``Neo4jHierarchyWriter`` MERGEs each node by ``id`` and MERGEs a ``CONTAINS`` edge from
its parent — both idempotent, so a re-run with no source change writes nothing new and
the returned count reflects only the nodes presented (not "rows created"). The in-memory
writer mirrors the same semantics over dicts for hermetic tests, and tracks ``write_count``
(only-incremented-on-actual-change) so idempotency can be asserted without a live database.

Node shape (one dict per node, parents before children is NOT required — edges MERGE
independently): ``{id, label, name, plant_id, parent_id | None}``. ``label`` must be one of
Site/Area/Unit (validated against ``queries.HIERARCHY_LABELS``); Asset nodes are Sprint 3.
"""
from __future__ import annotations

from typing import Any, Protocol

from neo4j import AsyncDriver, AsyncManagedTransaction

from rca_kg import config
from rca_kg.queries import HIERARCHY_LABELS


def _validated_hierarchy_label(label: str) -> str:
    if label not in HIERARCHY_LABELS:
        allowed = ", ".join(HIERARCHY_LABELS)
        raise ValueError(f"hierarchy label {label!r} is not writable; allowed: {allowed}")
    return label


class KgHierarchyWriter(Protocol):
    """Idempotent upsert of Site/Area/Unit nodes + their CONTAINS edges."""

    async def upsert_hierarchy_nodes(self, nodes: list[dict[str, Any]]) -> int:
        """Upsert the nodes (MERGE by id) + parent CONTAINS edges; return the count upserted."""
        ...


class Neo4jHierarchyWriter:
    """KgHierarchyWriter over the async Neo4j driver (MERGE node + MERGE CONTAINS edge)."""

    def __init__(self, driver: AsyncDriver | None = None, database: str | None = None) -> None:
        self._driver = driver if driver is not None else config.make_async_driver()
        self._database = database if database is not None else config.kg_database()

    async def aclose(self) -> None:
        await self._driver.close()

    async def upsert_hierarchy_nodes(self, nodes: list[dict[str, Any]]) -> int:
        if not nodes:
            return 0
        # Validate labels BEFORE interpolation (Cypher forbids parameters in label positions),
        # exactly as queries.py validates read labels.
        for node in nodes:
            _validated_hierarchy_label(node["label"])

        async def work(tx: AsyncManagedTransaction) -> None:
            for node in nodes:
                lbl = _validated_hierarchy_label(node["label"])
                await tx.run(
                    f"MERGE (n:{lbl} {{id: $id}}) "
                    "SET n.name = $name, n.plant_id = $plant_id",
                    id=node["id"], name=node.get("name"), plant_id=node.get("plant_id"))
                parent_id = node.get("parent_id")
                if parent_id is not None:
                    await tx.run(
                        "MATCH (p {id: $parent_id}) MATCH (c {id: $child_id}) "
                        "MERGE (p)-[:CONTAINS]->(c)",
                        parent_id=parent_id, child_id=node["id"])

        async with self._driver.session(database=self._database) as session:
            await session.execute_write(work)
        return len(nodes)


class InMemoryHierarchyWriter:
    """Hermetic KgHierarchyWriter: nodes keyed by id, edges as a set; idempotent.

    ``write_count`` increments only when a node's stored props actually change or a new
    CONTAINS edge is created — so a no-change re-run leaves it untouched (the idempotency
    parity assertion the tests rely on). ``upsert_hierarchy_nodes`` still returns the count
    of nodes PRESENTED (matching the Neo4j writer's contract), regardless of whether they
    changed."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: set[tuple[str, str]] = set()
        self.write_count = 0

    async def upsert_hierarchy_nodes(self, nodes: list[dict[str, Any]]) -> int:
        for node in nodes:
            _validated_hierarchy_label(node["label"])
            node_id = node["id"]
            props = {"label": node["label"], "name": node.get("name"),
                     "plant_id": node.get("plant_id")}
            if self.nodes.get(node_id) != props:
                self.nodes[node_id] = props
                self.write_count += 1
            parent_id = node.get("parent_id")
            if parent_id is not None and (parent_id, node_id) not in self.edges:
                self.edges.add((parent_id, node_id))
                self.write_count += 1
        return len(nodes)


__all__ = ["KgHierarchyWriter", "Neo4jHierarchyWriter", "InMemoryHierarchyWriter"]
