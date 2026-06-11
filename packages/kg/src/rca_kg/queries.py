"""KG read queries behind a gateway protocol (Sprint 2a Task 5).

`KgGateway` is the seam the MCP server talks through: `Neo4jGateway` runs read-only
Cypher over the async driver; `InMemoryGateway` mirrors the same semantics over plain
dicts for hermetic tests. Labels are validated against `ALLOWED_LABELS` and hop/depth
bounds are validated as ints BEFORE any string interpolation into Cypher (Cypher
forbids parameters in label positions and variable-length hop bounds); everything
else travels as query parameters. Validation failures raise ValueError, which the
server maps to a `validation_failed` ToolError.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Protocol

from neo4j import AsyncDriver, AsyncManagedTransaction

from rca_kg import config

ALLOWED_LABELS = frozenset({
    "EquipmentClass", "FailureMode", "FailureMechanism", "MaintenanceActivity",
    "Subunit", "Component", "Site", "Area", "Unit",
})
HIERARCHY_LABELS = ("Site", "Area", "Unit")
MAX_DEPTH_LIMIT = 16
MAX_HOPS_LIMIT = 16


def validated_label(label: str) -> str:
    if label not in ALLOWED_LABELS:
        allowed = ", ".join(sorted(ALLOWED_LABELS))
        raise ValueError(f"label {label!r} is not queryable; allowed labels: {allowed}")
    return label


def validated_depth(max_depth: int) -> int:
    depth = int(max_depth)
    if not 1 <= depth <= MAX_DEPTH_LIMIT:
        raise ValueError(f"max_depth must be between 1 and {MAX_DEPTH_LIMIT}, got {max_depth}")
    return depth


def validated_hops(max_hops: int) -> int:
    hops = int(max_hops)
    if not 1 <= hops <= MAX_HOPS_LIMIT:
        raise ValueError(f"max_hops must be between 1 and {MAX_HOPS_LIMIT}, got {max_hops}")
    return hops


class KgGateway(Protocol):
    """Read-only access to the knowledge graph (five queries the kg.* tools need)."""

    async def get_node(self, label: str, node_id: str) -> dict[str, Any] | None:
        """Properties of the node, or None if absent."""
        ...

    async def outgoing_rel_counts(self, label: str, node_id: str) -> dict[str, int]:
        """Outgoing relationship type -> count for the node."""
        ...

    async def failure_modes_for_class(self, equipment_class_id: str) -> list[dict[str, Any]]:
        """CAN_EXHIBIT failure modes, each with a `mechanisms` list (CAUSED_BY props)."""
        ...

    async def hierarchy(
        self, root_id: str | None, plant_id: str | None, max_depth: int
    ) -> list[dict[str, Any]]:
        """Flat rows {id, label, name, parent_id} for Site/Area/Unit under the root(s)."""
        ...

    async def shortest_path(
        self, from_id: str, to_id: str, max_hops: int
    ) -> list[dict[str, Any]] | None:
        """Undirected shortest path as [{node, label, rel_to_next}], or None if no path."""
        ...


class Neo4jGateway:
    """KgGateway over the async Neo4j driver (read-only Cypher; see module docstring)."""

    def __init__(self, driver: AsyncDriver | None = None, database: str | None = None) -> None:
        self._driver = driver if driver is not None else config.make_async_driver()
        self._database = database if database is not None else config.kg_database()

    async def aclose(self) -> None:
        await self._driver.close()

    async def _read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            result = await tx.run(query, params)  # type: ignore[arg-type]
            return await result.data()

        async with self._driver.session(database=self._database) as session:
            return await session.execute_read(work)

    async def get_node(self, label: str, node_id: str) -> dict[str, Any] | None:
        lbl = validated_label(label)
        rows = await self._read(
            f"MATCH (n:{lbl} {{id: $node_id}}) RETURN properties(n) AS props", node_id=node_id
        )
        return rows[0]["props"] if rows else None

    async def outgoing_rel_counts(self, label: str, node_id: str) -> dict[str, int]:
        lbl = validated_label(label)
        rows = await self._read(
            f"MATCH (n:{lbl} {{id: $node_id}})-[r]->() RETURN type(r) AS rel, count(r) AS c",
            node_id=node_id,
        )
        return {row["rel"]: row["c"] for row in rows}

    async def failure_modes_for_class(self, equipment_class_id: str) -> list[dict[str, Any]]:
        rows = await self._read(
            "MATCH (c:EquipmentClass {id: $class_id})-[:CAN_EXHIBIT]->(fm:FailureMode)\n"
            "OPTIONAL MATCH (fm)-[:CAUSED_BY]->(m:FailureMechanism)\n"
            "WITH fm, collect(properties(m)) AS mechanisms\n"
            "RETURN properties(fm) AS props, mechanisms ORDER BY fm.code",
            class_id=equipment_class_id,
        )
        return [{**row["props"], "mechanisms": row["mechanisms"]} for row in rows]

    async def hierarchy(
        self, root_id: str | None, plant_id: str | None, max_depth: int
    ) -> list[dict[str, Any]]:
        depth = validated_depth(max_depth)
        if root_id is not None:
            match_root = ("MATCH (root) WHERE (root:Site OR root:Area OR root:Unit) "
                          "AND root.id = $root_id")
            params: dict[str, Any] = {"root_id": root_id}
        elif plant_id is not None:
            match_root = "MATCH (root:Site {plant_id: $plant_id})"
            params = {"plant_id": plant_id}
        else:
            match_root = "MATCH (root:Site)"
            params = {}
        return await self._read(
            f"{match_root}\n"
            f"MATCH p = (root)-[:CONTAINS*0..{depth}]->(n)\n"
            "WHERE all(x IN nodes(p) WHERE x:Site OR x:Area OR x:Unit)\n"
            "WITH n, [x IN nodes(p) | x.id] AS path_ids\n"
            "RETURN DISTINCT n.id AS id, labels(n)[0] AS label, n.name AS name,\n"
            "       CASE WHEN size(path_ids) > 1 THEN path_ids[-2] ELSE null END AS parent_id",
            **params,
        )

    async def shortest_path(
        self, from_id: str, to_id: str, max_hops: int
    ) -> list[dict[str, Any]] | None:
        hops = validated_hops(max_hops)
        if from_id == to_id:  # shortestPath() rejects identical endpoints
            rows = await self._read(
                "MATCH (n {id: $node_id}) RETURN labels(n)[0] AS label, properties(n) AS props",
                node_id=from_id,
            )
            if not rows:
                return None
            return [{"node": rows[0]["props"], "label": rows[0]["label"], "rel_to_next": None}]
        rows = await self._read(
            "MATCH (a {id: $from_id}), (b {id: $to_id})\n"
            f"MATCH p = shortestPath((a)-[*..{hops}]-(b))\n"
            "RETURN [x IN nodes(p) | {label: labels(x)[0], props: properties(x)}] AS ns,\n"
            "       [r IN relationships(p) | type(r)] AS rels",
            from_id=from_id, to_id=to_id,
        )
        if not rows:
            return None
        ns, rels = rows[0]["ns"], rows[0]["rels"]
        return [
            {"node": n["props"], "label": n["label"],
             "rel_to_next": rels[i] if i < len(rels) else None}
            for i, n in enumerate(ns)
        ]


class InMemoryGateway:
    """Hermetic KgGateway: nodes = {(label, id): props}, edges = [(src_id, rel, dst_id)]."""

    def __init__(
        self,
        nodes: dict[tuple[str, str], dict[str, Any]],
        edges: list[tuple[str, str, str]],
    ) -> None:
        self._nodes = dict(nodes)
        self._edges = list(edges)
        self._label_by_id = {node_id: label for (label, node_id) in self._nodes}
        self._props_by_id = {node_id: props for (_, node_id), props in self._nodes.items()}

    async def get_node(self, label: str, node_id: str) -> dict[str, Any] | None:
        props = self._nodes.get((validated_label(label), node_id))
        return dict(props) if props is not None else None

    async def outgoing_rel_counts(self, label: str, node_id: str) -> dict[str, int]:
        if validated_label(label) != self._label_by_id.get(node_id):
            return {}
        counts: dict[str, int] = defaultdict(int)
        for src, rel, _dst in self._edges:
            if src == node_id:
                counts[rel] += 1
        return dict(counts)

    async def failure_modes_for_class(self, equipment_class_id: str) -> list[dict[str, Any]]:
        entries = []
        for src, rel, dst in self._edges:
            if src != equipment_class_id or rel != "CAN_EXHIBIT":
                continue
            if self._label_by_id.get(dst) != "FailureMode":
                continue
            mechanisms = [
                dict(self._props_by_id[m_dst])
                for m_src, m_rel, m_dst in self._edges
                if m_src == dst and m_rel == "CAUSED_BY"
                and self._label_by_id.get(m_dst) == "FailureMechanism"
            ]
            entries.append({**self._props_by_id[dst], "mechanisms": mechanisms})
        return sorted(entries, key=lambda e: e.get("code", ""))

    async def hierarchy(
        self, root_id: str | None, plant_id: str | None, max_depth: int
    ) -> list[dict[str, Any]]:
        depth = validated_depth(max_depth)
        if root_id is not None:
            roots = [root_id] if self._label_by_id.get(root_id) in HIERARCHY_LABELS else []
        elif plant_id is not None:
            roots = sorted(
                node_id for (label, node_id), props in self._nodes.items()
                if label == "Site" and props.get("plant_id") == plant_id
            )
        else:
            roots = sorted(node_id for (label, node_id) in self._nodes if label == "Site")
        rows: list[dict[str, Any]] = []
        for rid in roots:
            visited: set[str] = set()
            queue: deque[tuple[str, str | None, int]] = deque([(rid, None, 0)])
            while queue:
                node_id, parent_id, dist = queue.popleft()
                if node_id in visited:
                    continue
                visited.add(node_id)
                props = self._props_by_id[node_id]
                rows.append({"id": node_id, "label": self._label_by_id[node_id],
                             "name": props.get("name"), "parent_id": parent_id})
                if dist == depth:
                    continue
                for src, rel, dst in self._edges:
                    if (src == node_id and rel == "CONTAINS"
                            and self._label_by_id.get(dst) in HIERARCHY_LABELS):
                        queue.append((dst, node_id, dist + 1))
        return rows

    async def shortest_path(
        self, from_id: str, to_id: str, max_hops: int
    ) -> list[dict[str, Any]] | None:
        hops = validated_hops(max_hops)
        if from_id not in self._label_by_id or to_id not in self._label_by_id:
            return None

        def segment(node_id: str, rel_to_next: str | None) -> dict[str, Any]:
            return {"node": dict(self._props_by_id[node_id]),
                    "label": self._label_by_id[node_id], "rel_to_next": rel_to_next}

        if from_id == to_id:
            return [segment(from_id, None)]
        adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for src, rel, dst in self._edges:  # undirected BFS, like shortestPath((a)-[*..N]-(b))
            adjacency[src].append((dst, rel))
            adjacency[dst].append((src, rel))
        prev: dict[str, tuple[str, str]] = {}
        frontier, visited, dist = [from_id], {from_id}, 0
        while frontier and to_id not in prev and dist < hops:
            dist += 1
            next_frontier = []
            for node_id in frontier:
                for neighbor, rel in adjacency[node_id]:
                    if neighbor in visited:
                        continue
                    visited.add(neighbor)
                    prev[neighbor] = (node_id, rel)
                    next_frontier.append(neighbor)
            frontier = next_frontier
        if to_id not in prev:
            return None
        path_ids, rels = [to_id], []
        while path_ids[-1] != from_id:
            parent, rel = prev[path_ids[-1]]
            rels.append(rel)
            path_ids.append(parent)
        path_ids.reverse()
        rels.reverse()
        return [
            segment(node_id, rels[i] if i < len(rels) else None)
            for i, node_id in enumerate(path_ids)
        ]


__all__ = [
    "ALLOWED_LABELS", "KgGateway", "Neo4jGateway", "InMemoryGateway",
    "validated_label", "validated_depth", "validated_hops",
]
