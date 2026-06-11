"""Sprint 3 KG asset layer: lazy Asset materialization, ontology-validated failure-mode
links, asset context (cold/warm), and warm-layer failure-event writes (WI4/WI6).

Hermetic — InMemoryAssetGraph over a miniature ontology mirroring the seed's ids
(equipment-class:bb1, failure-mode:elp [ELP], failure-mechanism:seal-failure).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastmcp import Client
from rca_contracts import ToolResponse

from rca_kg.assets import (
    AssetContext,
    InMemoryAssetGraph,
    InvalidFailureModePair,
)
from rca_kg.queries import InMemoryGateway
from rca_kg.server import UpsertAssetResult, make_kg_mcp

P101A = "asset:refinery-gc:unit-101:p-101a"
P102A = "asset:refinery-gc:unit-101:p-102a"
BB1 = "equipment-class:bb1"
ELP = "failure-mode:elp"
SEAL = "failure-mechanism:seal-failure"
REF_TIME = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)


def _seed() -> dict:
    nodes: dict[tuple[str, str], dict] = {}
    edges: list[tuple[str, str, str]] = []
    nodes[("EquipmentClass", BB1)] = {"id": BB1, "code": "BB1", "name": "Centrifugal pump"}
    nodes[("FailureMode", ELP)] = {"id": ELP, "code": "ELP",
                                   "name": "External leakage process medium"}
    nodes[("FailureMode", "failure-mode:vib")] = {"id": "failure-mode:vib", "code": "VIB",
                                                  "name": "Vibration"}
    nodes[("FailureMechanism", SEAL)] = {"id": SEAL, "name": "Seal failure"}
    nodes[("Unit", "unit:refinery-gc:unit-101")] = {"id": "unit:refinery-gc:unit-101",
                                                    "name": "UNIT-101", "plant_id": "refinery-gc"}
    edges.append((BB1, "CAN_EXHIBIT", ELP))
    edges.append((BB1, "CAN_EXHIBIT", "failure-mode:vib"))
    return {"nodes": nodes, "edges": edges}


def _graph() -> InMemoryAssetGraph:
    s = _seed()
    return InMemoryAssetGraph(nodes=s["nodes"], edges=s["edges"])


def _parse(result, model):
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[model].model_validate_json(json.dumps(payload))


# --------------------------------------------------------------------- direct (graph)


async def test_upsert_asset_materializes_node_and_edges_idempotently():
    g = _graph()
    created = await g.upsert_asset(canonical_id=P101A, name="P-101A", iso14224_class=BB1,
                                   iso14224_class_confidence=0.95, iso14224_class_method="register",
                                   probed_at=REF_TIME)
    assert created is True
    assert ("Asset", P101A) in g.nodes
    assert g._has_edge(P101A, "LOCATED_IN", "unit:refinery-gc:unit-101")
    assert g._has_edge(P101A, "INSTANCE_OF", BB1)

    writes_after_first = g.write_count
    created2 = await g.upsert_asset(canonical_id=P101A, name="P-101A", iso14224_class=BB1,
                                    iso14224_class_confidence=0.95, iso14224_class_method="register",
                                    probed_at=REF_TIME)
    assert created2 is False
    assert g.write_count == writes_after_first   # re-upsert writes nothing structural (G3/§4.6)


async def test_upsert_asset_rejects_bad_canonical_id_g4():
    g = _graph()
    with pytest.raises(ValueError):
        await g.upsert_asset(canonical_id="P-101A", name="P-101A", iso14224_class=BB1,
                             iso14224_class_confidence=0.9, iso14224_class_method="llm_v1",
                             probed_at=REF_TIME)


async def test_link_failure_mode_validates_ontology_pair_g3():
    g = _graph()
    await g.upsert_asset(canonical_id=P101A, name="P-101A", iso14224_class=BB1,
                         iso14224_class_confidence=0.9, iso14224_class_method="register",
                         probed_at=REF_TIME)
    await g.link_failure_mode(canonical_id=P101A, failure_mode_code="ELP")  # valid pair
    assert g._has_edge(P101A, "CAN_EXHIBIT", ELP)

    with pytest.raises(InvalidFailureModePair):
        await g.link_failure_mode(canonical_id=P101A, failure_mode_code="ZZZ")  # not in ontology


async def test_get_asset_context_cold_then_warm():
    g = _graph()
    await g.upsert_asset(canonical_id=P101A, name="P-101A", iso14224_class=BB1,
                         iso14224_class_confidence=0.9, iso14224_class_method="register",
                         probed_at=REF_TIME)
    cold = await g.get_asset_context(canonical_id=P101A)
    assert cold.kg_warm is False
    assert cold.asset is not None and cold.asset.name == "P-101A"
    assert {m["code"] for m in cold.applicable_failure_modes} == {"ELP", "VIB"}
    assert cold.prior_events_on_asset == []

    created = await g.persist_failure_event(
        event_id="fe-1", probe_run_id="pr-1", conclusion_id="c-1", canonical_id=P101A,
        iso14224_failure_mode="ELP", iso14224_mechanism=SEAL, iso14224_cause=None,
        narrative="mechanical seal leak", confidence=0.8, detected_at=REF_TIME,
        concluded_at=REF_TIME, engineer_approval_status="approved")
    assert created is True
    warm = await g.get_asset_context(canonical_id=P101A)
    assert warm.kg_warm is True
    assert [e.event_id for e in warm.prior_events_on_asset] == ["fe-1"]
    assert warm.prior_events_on_asset[0].iso14224_failure_mode == "ELP"


async def test_persist_failure_event_is_idempotent_zero_second_write():
    g = _graph()
    kwargs = dict(event_id="fe-1", probe_run_id="pr-1", conclusion_id="c-1", canonical_id=P101A,
                  iso14224_failure_mode="ELP", iso14224_mechanism=SEAL, iso14224_cause=None,
                  narrative="seal leak", confidence=0.8, detected_at=REF_TIME,
                  concluded_at=REF_TIME, engineer_approval_status="approved")
    await g.persist_failure_event(**kwargs)
    writes_after_first = g.write_count
    created2 = await g.persist_failure_event(**kwargs)
    assert created2 is False
    assert g.write_count == writes_after_first   # §6.7 — zero second-write operations


async def test_persist_failure_event_rejects_unknown_ontology_codes():
    g = _graph()
    with pytest.raises(InvalidFailureModePair):
        await g.persist_failure_event(
            event_id="fe-2", probe_run_id="pr", conclusion_id="c", canonical_id=P101A,
            iso14224_failure_mode="NOPE", iso14224_mechanism=SEAL, iso14224_cause=None,
            narrative="x", confidence=0.5, detected_at=REF_TIME, concluded_at=REF_TIME,
            engineer_approval_status="approved")


async def test_link_resulted_in_wo_g21():
    g = _graph()
    await g.persist_failure_event(
        event_id="fe-1", probe_run_id="pr", conclusion_id="c", canonical_id=P101A,
        iso14224_failure_mode="ELP", iso14224_mechanism=SEAL, iso14224_cause=None,
        narrative="seal leak", confidence=0.8, detected_at=REF_TIME, concluded_at=REF_TIME,
        engineer_approval_status="approved")
    await g.link_resulted_in_wo(event_id="fe-1", work_order_id="WO-99001")
    assert ("WorkOrder", "WO-99001") in g.nodes
    assert g._has_edge("fe-1", "RESULTED_IN", "WO-99001")


async def test_class_level_prior_events_at_plant():
    g = _graph()
    for cid in (P101A, P102A):
        await g.upsert_asset(canonical_id=cid, name=cid.split(":")[-1].upper(), iso14224_class=BB1,
                             iso14224_class_confidence=0.9, iso14224_class_method="register",
                             probed_at=REF_TIME)
    # an event on P-102A should appear in P-101A's class-level prior events
    await g.persist_failure_event(
        event_id="fe-other", probe_run_id="pr", conclusion_id="c", canonical_id=P102A,
        iso14224_failure_mode="ELP", iso14224_mechanism=SEAL, iso14224_cause=None,
        narrative="seal leak on sister pump", confidence=0.7, detected_at=REF_TIME,
        concluded_at=REF_TIME, engineer_approval_status="approved")
    ctx = await g.get_asset_context(canonical_id=P101A)
    assert ctx.kg_warm is True
    assert ctx.prior_events_on_asset == []
    assert [e.event_id for e in ctx.prior_events_for_class_at_plant] == ["fe-other"]


# --------------------------------------------------------------------- via MCP tools


def _mcp_client() -> Client:
    s = _seed()
    gateway = InMemoryGateway(s["nodes"], s["edges"])
    asset_graph = InMemoryAssetGraph(nodes=s["nodes"], edges=s["edges"])
    return Client(make_kg_mcp(gateway=gateway, asset_graph=asset_graph))


async def test_make_kg_mcp_exposes_seven_tools_when_asset_graph_wired():
    async with _mcp_client() as c:
        tools = {t.name for t in await c.list_tools()}
        assert tools == {
            "kg.get_ontology_node", "kg.list_failure_modes_for_class", "kg.get_hierarchy",
            "kg.find_path", "kg.upsert_asset", "kg.link_failure_mode", "kg.get_asset_context",
        }


async def test_kg_mcp_omits_asset_tools_when_no_asset_graph():
    s = _seed()
    gateway = InMemoryGateway(s["nodes"], s["edges"])
    async with Client(make_kg_mcp(gateway=gateway)) as c:
        tools = {t.name for t in await c.list_tools()}
        assert "kg.upsert_asset" not in tools
        assert len(tools) == 4


async def test_kg_upsert_asset_tool_roundtrip_and_bad_id_validation():
    async with _mcp_client() as c:
        ok = _parse(await c.call_tool("kg.upsert_asset", {"request": {
            "canonical_id": P101A, "name": "P-101A", "iso14224_class": BB1,
            "iso14224_class_confidence": 0.95, "iso14224_class_method": "register",
            "reference_time": REF_TIME.isoformat()}}), UpsertAssetResult)
        assert ok.error is None and ok.data.created is True
        assert ok.provenance is not None and ok.provenance.source == "kg"

        bad = _parse(await c.call_tool("kg.upsert_asset", {"request": {
            "canonical_id": "not-canonical", "name": "x", "iso14224_class": BB1,
            "iso14224_class_confidence": 0.5, "iso14224_class_method": "llm_v1",
            "reference_time": REF_TIME.isoformat()}}), UpsertAssetResult)
        assert bad.data is None and bad.error is not None
        assert bad.error.code == "validation_failed"


async def test_kg_link_failure_mode_tool_invalid_pair_is_validation_failed():
    async with _mcp_client() as c:
        await c.call_tool("kg.upsert_asset", {"request": {
            "canonical_id": P101A, "name": "P-101A", "iso14224_class": BB1,
            "iso14224_class_confidence": 0.95, "iso14224_class_method": "register",
            "reference_time": REF_TIME.isoformat()}})
        bad = _parse(await c.call_tool("kg.link_failure_mode", {"request": {
            "canonical_id": P101A, "failure_mode_code": "ZZZ"}}), dict)
        assert bad.error is not None and bad.error.code == "validation_failed"


async def test_kg_get_asset_context_tool():
    async with _mcp_client() as c:
        await c.call_tool("kg.upsert_asset", {"request": {
            "canonical_id": P101A, "name": "P-101A", "iso14224_class": BB1,
            "iso14224_class_confidence": 0.95, "iso14224_class_method": "register",
            "reference_time": REF_TIME.isoformat()}})
        ctx = _parse(await c.call_tool("kg.get_asset_context", {"request": {
            "canonical_id": P101A}}), AssetContext)
        assert ctx.error is None
        assert ctx.data.kg_warm is False
        assert ctx.data.asset is not None
        assert {m["code"] for m in ctx.data.applicable_failure_modes} == {"ELP", "VIB"}
