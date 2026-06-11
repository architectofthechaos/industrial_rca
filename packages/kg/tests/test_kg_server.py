"""Tests for the read-only KG MCP server (Sprint 2a Task 5).

Hermetic tests run against `InMemoryGateway` with a miniature graph mirroring the
seed's shapes (BB1 + 19 failure modes, refplant hierarchy, one Asset node that must
NEVER appear in hierarchy output). Live tests construct `Neo4jGateway` against the
seeded dev Neo4j and skip via the conftest reachability marker.
"""
from __future__ import annotations

import json

import pytest
from conftest import requires_kg
from fastmcp import Client
from rca_contracts import ToolResponse

from rca_kg.queries import InMemoryGateway, Neo4jGateway
from rca_kg.server import (
    FailureModeEntry,
    HierarchyNode,
    OntologyNode,
    PathSegment,
    make_kg_mcp,
)

EXPECTED_TOOLS = {
    "kg.get_ontology_node",
    "kg.list_failure_modes_for_class",
    "kg.get_hierarchy",
    "kg.find_path",
}
FM_CODES = [
    "BRD", "ERO", "HIO", "LOO", "VIB", "LBP", "LCP", "STD", "OHE", "ELP",
    "ELU", "FOF", "INL", "NOI", "OTH", "PDE", "PLU", "SER", "UNK",
]


def _parse(result, model):
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[model].model_validate_json(json.dumps(payload))


def _fake_gateway() -> InMemoryGateway:
    nodes: dict[tuple[str, str], dict] = {}
    edges: list[tuple[str, str, str]] = []

    def add(label: str, node_id: str, **props) -> None:
        nodes[(label, node_id)] = {"id": node_id, **props}

    add("EquipmentClass", "equipment-class:bb1", code="BB1", name="Centrifugal pump",
        description="Centrifugal pump equipment type.")
    for code in FM_CODES:
        fm_id = f"failure-mode:{code.lower()}"
        add("FailureMode", fm_id, code=code, name=code.title(),
            description=f"{code} failure mode.", iso14224_ref="B.3")
        edges.append(("equipment-class:bb1", "CAN_EXHIBIT", fm_id))
    for mech in ("imbalance", "bearing-wear", "seal-failure"):
        add("FailureMechanism", f"failure-mechanism:{mech}", name=mech.replace("-", " ").title(),
            description=f"{mech} mechanism.", iso14224_ref="B.4")
    edges += [
        ("failure-mode:vib", "CAUSED_BY", "failure-mechanism:imbalance"),
        ("failure-mode:vib", "CAUSED_BY", "failure-mechanism:bearing-wear"),
        ("failure-mode:elp", "CAUSED_BY", "failure-mechanism:seal-failure"),
    ]
    add("MaintenanceActivity", "maintenance-activity:adjust", name="Adjust",
        description="Adjust activity.", iso14224_ref="B.6")
    edges.append(("failure-mode:vib", "REMEDIED_BY", "maintenance-activity:adjust"))
    add("Component", "component:mechanical-seal", name="Mechanical seal",
        description="Shaft sealing device.")
    edges.append(("failure-mechanism:seal-failure", "OCCURS_IN", "component:mechanical-seal"))

    add("Site", "site:refinery-gc", name="Refinery GC", plant_id="refinery-gc")
    add("Area", "area:refinery-gc:area-100", name="AREA-100", plant_id="refinery-gc")
    add("Area", "area:refinery-gc:area-200", name="AREA-200", plant_id="refinery-gc")
    add("Unit", "unit:refinery-gc:unit-101", name="UNIT-101", plant_id="refinery-gc")
    add("Unit", "unit:refinery-gc:unit-102", name="UNIT-102", plant_id="refinery-gc")
    add("Unit", "unit:refinery-gc:unit-201", name="UNIT-201", plant_id="refinery-gc")
    # An Asset hangs off unit-101 but must never surface from kg.get_hierarchy.
    add("Asset", "asset:refinery-gc:unit-101:p-101a", name="P-101A", plant_id="refinery-gc")
    edges += [
        ("site:refinery-gc", "CONTAINS", "area:refinery-gc:area-100"),
        ("site:refinery-gc", "CONTAINS", "area:refinery-gc:area-200"),
        ("area:refinery-gc:area-100", "CONTAINS", "unit:refinery-gc:unit-101"),
        ("area:refinery-gc:area-100", "CONTAINS", "unit:refinery-gc:unit-102"),
        ("area:refinery-gc:area-200", "CONTAINS", "unit:refinery-gc:unit-201"),
        ("unit:refinery-gc:unit-101", "CONTAINS", "asset:refinery-gc:unit-101:p-101a"),
    ]
    return InMemoryGateway(nodes, edges)


def _client() -> Client:
    return Client(make_kg_mcp(gateway=_fake_gateway()))


def _assert_kg_provenance(resp, tool_name: str) -> None:
    assert resp.provenance is not None
    assert resp.provenance.source == "kg"
    assert resp.provenance.tool_name == tool_name
    assert resp.provenance.queried_at is not None
    assert resp.provenance.record_count >= 1


def _walk(node: HierarchyNode):
    yield node
    for child in node.children:
        yield from _walk(child)


# --------------------------------------------------------------------------- hermetic


async def test_exposed_tools_are_exactly_the_four_kg_tools():
    async with _client() as c:
        tools = {t.name for t in await c.list_tools()}
        assert tools == EXPECTED_TOOLS


async def test_get_ontology_node_returns_vib_with_outgoing_counts():
    async with _client() as c:
        res = _parse(await c.call_tool(
            "kg.get_ontology_node",
            {"request": {"label": "FailureMode", "node_id": "failure-mode:vib"}}),
            OntologyNode)
        assert res.error is None
        assert res.data.label == "FailureMode"
        assert res.data.properties["code"] == "VIB"
        assert res.data.properties["iso14224_ref"] == "B.3"
        assert res.data.outgoing == {"CAUSED_BY": 2, "REMEDIED_BY": 1}
        _assert_kg_provenance(res, "kg.get_ontology_node")


async def test_get_ontology_node_rejects_label_outside_allowlist():
    async with _client() as c:
        res = _parse(await c.call_tool(
            "kg.get_ontology_node",
            {"request": {"label": "Asset", "node_id": "asset:refinery-gc:unit-101:p-101a"}}),
            OntologyNode)
        assert res.data is None and res.error is not None
        assert res.error.code == "validation_failed"


async def test_get_ontology_node_unknown_id_is_not_found():
    async with _client() as c:
        res = _parse(await c.call_tool(
            "kg.get_ontology_node",
            {"request": {"label": "FailureMode", "node_id": "failure-mode:nope"}}),
            OntologyNode)
        assert res.error is not None and res.error.code == "not_found"


async def test_list_failure_modes_for_bb1_has_19_entries_with_mechanisms():
    async with _client() as c:
        res = _parse(await c.call_tool(
            "kg.list_failure_modes_for_class",
            {"request": {"equipment_class_id": "equipment-class:bb1"}}),
            list[FailureModeEntry])
        assert res.error is None
        assert len(res.data) >= 18
        assert {e.code for e in res.data} == set(FM_CODES)
        by_code = {e.code: e for e in res.data}
        vib = by_code["VIB"]
        assert vib.id == "failure-mode:vib" and vib.iso14224_ref == "B.3"
        assert vib.name and vib.description
        assert len(vib.mechanisms) == 2  # non-empty for VIB
        assert {m["id"] for m in vib.mechanisms} == {
            "failure-mechanism:imbalance", "failure-mechanism:bearing-wear"}
        _assert_kg_provenance(res, "kg.list_failure_modes_for_class")
        assert res.provenance.record_count == len(res.data)


async def test_get_hierarchy_by_plant_is_site_tree_without_assets():
    async with _client() as c:
        res = _parse(await c.call_tool(
            "kg.get_hierarchy", {"request": {"plant_id": "refinery-gc"}}), HierarchyNode)
        assert res.error is None
        root = res.data
        assert root.id == "site:refinery-gc" and root.label == "Site"
        all_nodes = list(_walk(root))
        assert len(all_nodes) == 6  # 1 site + 2 areas + 3 units
        assert {n.label for n in all_nodes} == {"Site", "Area", "Unit"}  # NO Asset
        assert not any(n.id.startswith("asset:") for n in all_nodes)
        _assert_kg_provenance(res, "kg.get_hierarchy")
        assert res.provenance.record_count == 6


async def test_get_hierarchy_by_root_id_returns_subtree():
    async with _client() as c:
        res = _parse(await c.call_tool(
            "kg.get_hierarchy", {"request": {"root_id": "area:refinery-gc:area-100"}}),
            HierarchyNode)
        assert res.error is None
        assert res.data.id == "area:refinery-gc:area-100" and res.data.label == "Area"
        assert {child.id for child in res.data.children} == {
            "unit:refinery-gc:unit-101", "unit:refinery-gc:unit-102"}
        assert all(child.label == "Unit" for child in res.data.children)


async def test_get_hierarchy_max_depth_1_stops_at_children():
    async with _client() as c:
        res = _parse(await c.call_tool(
            "kg.get_hierarchy", {"request": {"plant_id": "refinery-gc", "max_depth": 1}}),
            HierarchyNode)
        assert res.error is None
        assert len(res.data.children) == 2  # children (areas) present
        assert all(child.children == [] for child in res.data.children)  # no grandchildren


async def test_get_hierarchy_unknown_root_is_not_found():
    async with _client() as c:
        res = _parse(await c.call_tool(
            "kg.get_hierarchy", {"request": {"root_id": "area:nope:area-999"}}), HierarchyNode)
        assert res.error is not None and res.error.code == "not_found"


async def test_get_hierarchy_rejects_out_of_bounds_max_depth():
    async with _client() as c:
        for depth in (0, 17):
            res = _parse(await c.call_tool(
                "kg.get_hierarchy", {"request": {"plant_id": "refinery-gc", "max_depth": depth}}),
                HierarchyNode)
            assert res.error is not None and res.error.code == "validation_failed"


async def test_find_path_rejects_out_of_bounds_max_hops():
    async with _client() as c:
        for hops in (0, 17):
            res = _parse(await c.call_tool(
                "kg.find_path",
                {"request": {"from_id": "failure-mode:vib",
                             "to_id": "component:mechanical-seal", "max_hops": hops}}),
                list[PathSegment])
            assert res.error is not None and res.error.code == "validation_failed"


async def test_list_failure_modes_unknown_class_is_empty_success():
    async with _client() as c:
        res = _parse(await c.call_tool(
            "kg.list_failure_modes_for_class",
            {"request": {"equipment_class_id": "equipment-class:does-not-exist"}}),
            list[FailureModeEntry])
        assert res.error is None
        assert res.data == []
        assert res.provenance is not None and res.provenance.record_count == 0


async def test_find_path_vib_to_mechanical_seal_is_ordered_segments():
    async with _client() as c:
        res = _parse(await c.call_tool(
            "kg.find_path",
            {"request": {"from_id": "failure-mode:vib", "to_id": "component:mechanical-seal"}}),
            list[PathSegment])
        assert res.error is None
        segments = res.data
        assert len(segments) >= 2
        assert segments[0].node["id"] == "failure-mode:vib"
        assert segments[-1].node["id"] == "component:mechanical-seal"
        assert segments[-1].relationship_to_next is None  # last segment terminates the path
        assert all(s.relationship_to_next is not None for s in segments[:-1])
        _assert_kg_provenance(res, "kg.find_path")
        assert res.provenance.record_count == len(segments)


async def test_find_path_honors_max_hops():
    # the only fake-graph route vib->mechanical-seal is 4 hops; 3 must miss, 4 must hit
    async with _client() as c:
        miss = _parse(await c.call_tool(
            "kg.find_path",
            {"request": {"from_id": "failure-mode:vib", "to_id": "component:mechanical-seal",
                         "max_hops": 3}}),
            list[PathSegment])
        assert miss.error is not None and miss.error.code == "not_found"
        hit = _parse(await c.call_tool(
            "kg.find_path",
            {"request": {"from_id": "failure-mode:vib", "to_id": "component:mechanical-seal",
                         "max_hops": 4}}),
            list[PathSegment])
        assert hit.error is None and len(hit.data) == 5  # 4 hops -> 5 nodes


async def test_find_path_missing_id_is_not_found():
    async with _client() as c:
        res = _parse(await c.call_tool(
            "kg.find_path",
            {"request": {"from_id": "failure-mode:nope", "to_id": "component:mechanical-seal"}}),
            list[PathSegment])
        assert res.error is not None and res.error.code == "not_found"


# ------------------------------------------------------------------------------- live


@pytest.fixture
async def live_client():
    gateway = Neo4jGateway()
    try:
        async with Client(make_kg_mcp(gateway=gateway)) as c:
            yield c
    finally:
        await gateway.aclose()


@requires_kg
async def test_live_get_ontology_node_vib(live_client):
    res = _parse(await live_client.call_tool(
        "kg.get_ontology_node",
        {"request": {"label": "FailureMode", "node_id": "failure-mode:vib"}}),
        OntologyNode)
    assert res.error is None
    assert res.data.properties["code"] == "VIB"
    assert res.data.properties["iso14224_ref"] == "B.3"
    assert res.data.outgoing.get("CAUSED_BY", 0) >= 2
    assert res.data.outgoing.get("REMEDIED_BY", 0) >= 1
    _assert_kg_provenance(res, "kg.get_ontology_node")


@requires_kg
async def test_live_list_failure_modes_for_bb1(live_client):
    res = _parse(await live_client.call_tool(
        "kg.list_failure_modes_for_class",
        {"request": {"equipment_class_id": "equipment-class:bb1"}}),
        list[FailureModeEntry])
    assert res.error is None and len(res.data) >= 18
    vib = next(e for e in res.data if e.code == "VIB")
    assert vib.mechanisms and all(m.get("id") for m in vib.mechanisms)
    _assert_kg_provenance(res, "kg.list_failure_modes_for_class")


@requires_kg
async def test_live_hierarchy_has_no_asset_label(live_client):
    res = _parse(await live_client.call_tool(
        "kg.get_hierarchy", {"request": {"plant_id": "refinery-gc"}}), HierarchyNode)
    assert res.error is None
    nodes = list(_walk(res.data))
    assert res.data.id == "site:refinery-gc"
    assert len(nodes) == 6  # 1 site + 2 areas + 3 units
    assert {n.label for n in nodes} == {"Site", "Area", "Unit"}


@requires_kg
async def test_live_find_path_proves_driver_wiring(live_client):
    res = _parse(await live_client.call_tool(
        "kg.find_path",
        {"request": {"from_id": "failure-mode:vib", "to_id": "component:mechanical-seal"}}),
        list[PathSegment])
    assert res.error is None and len(res.data) >= 2
    assert res.data[0].node["id"] == "failure-mode:vib"
    assert res.data[-1].node["id"] == "component:mechanical-seal"
    assert res.data[-1].relationship_to_next is None
