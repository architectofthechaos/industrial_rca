"""FastMCP server for the read-only KG tools (Sprint 2a Task 5).

Exactly four tools: kg.get_ontology_node, kg.list_failure_modes_for_class,
kg.get_hierarchy, kg.find_path. Reuses the connector_sdk envelope/provenance/error
discipline: every tool returns ToolResponse[T] with provenance; exceptions become a
mapped ToolError (ValueError from gateway validation -> validation_failed; missing
nodes/paths -> not_found via NotFound). kg.get_hierarchy walks Site/Area/Unit only —
Assets are MAR's, never the KG's, to return (Phase 1 spec §1.4).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field
from rca_connector_sdk import NotFound, build_server, map_source_error, ok_response
from rca_contracts import ToolError, ToolResponse

from .assets import AssetContext, AssetGraph, InvalidFailureModePair
from .queries import KgGateway

_VERSION = "0.1.0"
_SOURCE = "kg"


class GetOntologyNodeRequest(BaseModel):
    label: str
    node_id: str


class ListFailureModesRequest(BaseModel):
    equipment_class_id: str


class GetHierarchyRequest(BaseModel):
    root_id: str | None = None
    plant_id: str | None = None
    max_depth: int = 3


class FindPathRequest(BaseModel):
    from_id: str
    to_id: str
    max_hops: int = 6


class UpsertAssetRequest(BaseModel):
    canonical_id: str                    # MUST match the Sprint-1 canonical regex (G4)
    name: str
    iso14224_class: str                  # ontology EquipmentClass id, e.g. "bb1"
    iso14224_class_confidence: float
    iso14224_class_method: str           # "register" | "rule:<id>" | "llm_v1"
    reference_time: datetime             # workflow-frozen; sets materialized_at/last_probed_at


class LinkFailureModeRequest(BaseModel):
    canonical_id: str
    failure_mode_code: str               # ISO code, validated against the ontology before write


class GetAssetContextRequest(BaseModel):
    canonical_id: str
    iso14224_class: str | None = None    # fallback class when the Asset isn't materialized yet


class UpsertAssetResult(BaseModel):
    canonical_id: str
    created: bool                        # True on first materialization, False on re-upsert


class OntologyNode(BaseModel):
    label: str
    properties: dict[str, Any]
    outgoing: dict[str, int]  # outgoing relationship type -> count


class FailureModeEntry(BaseModel):
    code: str
    id: str
    name: str
    description: str
    iso14224_ref: str
    mechanisms: list[dict[str, Any]]


class HierarchyNode(BaseModel):
    id: str
    label: str
    name: str
    children: list["HierarchyNode"] = Field(default_factory=list)


class PathSegment(BaseModel):
    node: dict[str, Any]
    relationship_to_next: str | None = None  # None terminates the path


def _fail(envelope, exc: Exception):
    if isinstance(exc, ValueError):  # gateway input validation (label/depth/hops)
        return envelope.fail(ToolError(code="validation_failed", message=str(exc),
                                       retryable=False))
    return envelope.fail(map_source_error(exc))


def _build_tree(rows: list[dict[str, Any]]) -> HierarchyNode:
    """Assemble flat {id,label,name,parent_id} rows (tree-shaped CONTAINS) into one root."""
    rows = sorted(rows, key=lambda r: r["id"])  # deterministic child order
    ids = {row["id"] for row in rows}
    nodes = {row["id"]: HierarchyNode(id=row["id"], label=row["label"], name=row["name"])
             for row in rows}
    roots: list[HierarchyNode] = []
    for row in rows:
        parent_id = row.get("parent_id")
        if parent_id is None or parent_id not in ids:
            roots.append(nodes[row["id"]])
        else:
            nodes[parent_id].children.append(nodes[row["id"]])
    if len(roots) != 1:
        raise ValueError(
            f"hierarchy matched {len(roots)} roots; pass plant_id or root_id to disambiguate")
    return roots[0]


def make_kg_mcp(*, gateway: KgGateway, asset_graph: AssetGraph | None = None) -> FastMCP:
    mcp = build_server("kg")

    @mcp.tool(name="kg.get_ontology_node")
    async def get_ontology_node(request: GetOntologyNodeRequest) -> ToolResponse[OntologyNode]:
        envelope = ToolResponse[OntologyNode]
        try:
            props = await gateway.get_node(request.label, request.node_id)
            if props is None:
                raise NotFound(f"{request.label} {request.node_id} not found")
            outgoing = await gateway.outgoing_rel_counts(request.label, request.node_id)
            node = OntologyNode(label=request.label, properties=props, outgoing=outgoing)
            return ok_response(node, tool="kg.get_ontology_node",
                               version=_VERSION, source=_SOURCE,
                               source_query=f"get_node {request.label} {request.node_id}",
                               record_count=1, raw_tags=[request.node_id])
        except Exception as exc:  # noqa: BLE001
            return _fail(envelope, exc)

    @mcp.tool(name="kg.list_failure_modes_for_class")
    async def list_failure_modes_for_class(
        request: ListFailureModesRequest,
    ) -> ToolResponse[list[FailureModeEntry]]:
        envelope = ToolResponse[list[FailureModeEntry]]
        try:
            rows = await gateway.failure_modes_for_class(request.equipment_class_id)
            entries = [
                FailureModeEntry(code=row["code"], id=row["id"], name=row["name"],
                                 description=row["description"],
                                 iso14224_ref=row["iso14224_ref"],
                                 mechanisms=row["mechanisms"])
                for row in rows
            ]
            return ok_response(entries, tool="kg.list_failure_modes_for_class",
                               version=_VERSION, source=_SOURCE,
                               source_query=("failure_modes_for_class"
                                             f" {request.equipment_class_id}"),
                               record_count=len(entries), raw_tags=[e.id for e in entries])
        except Exception as exc:  # noqa: BLE001
            return _fail(envelope, exc)

    @mcp.tool(name="kg.get_hierarchy")
    async def get_hierarchy(request: GetHierarchyRequest) -> ToolResponse[HierarchyNode]:
        envelope = ToolResponse[HierarchyNode]
        try:
            rows = await gateway.hierarchy(request.root_id, request.plant_id, request.max_depth)
            if not rows:
                key = request.root_id or request.plant_id or "<any site>"
                raise NotFound(f"hierarchy root {key} not found")
            tree = _build_tree(rows)
            return ok_response(tree, tool="kg.get_hierarchy",
                               version=_VERSION, source=_SOURCE,
                               source_query=(f"hierarchy root_id={request.root_id}"
                                             f" plant_id={request.plant_id}"
                                             f" max_depth={request.max_depth}"),
                               record_count=len(rows), raw_tags=[row["id"] for row in rows])
        except Exception as exc:  # noqa: BLE001
            return _fail(envelope, exc)

    @mcp.tool(name="kg.find_path")
    async def find_path(request: FindPathRequest) -> ToolResponse[list[PathSegment]]:
        envelope = ToolResponse[list[PathSegment]]
        try:
            segments = await gateway.shortest_path(request.from_id, request.to_id,
                                                   request.max_hops)
            if segments is None:
                raise NotFound(f"no path from {request.from_id} to {request.to_id} "
                               f"within {request.max_hops} hops")
            data = [PathSegment(node={"label": seg["label"], **seg["node"]},
                                relationship_to_next=seg["rel_to_next"])
                    for seg in segments]
            return ok_response(data, tool="kg.find_path", version=_VERSION, source=_SOURCE,
                               source_query=(f"shortest_path {request.from_id}"
                                             f" -> {request.to_id}"
                                             f" max_hops={request.max_hops}"),
                               record_count=len(data),
                               raw_tags=[request.from_id, request.to_id])
        except Exception as exc:  # noqa: BLE001
            return _fail(envelope, exc)

    # --- Sprint 3 asset-layer tools (registered only when an AssetGraph is wired) ---
    if asset_graph is not None:
        _register_asset_tools(mcp, asset_graph)

    return mcp


def _register_asset_tools(mcp: FastMCP, asset_graph: AssetGraph) -> None:
    @mcp.tool(name="kg.upsert_asset")
    async def upsert_asset(request: UpsertAssetRequest) -> ToolResponse[UpsertAssetResult]:
        envelope = ToolResponse[UpsertAssetResult]
        try:
            created = await asset_graph.upsert_asset(
                canonical_id=request.canonical_id, name=request.name,
                iso14224_class=request.iso14224_class,
                iso14224_class_confidence=request.iso14224_class_confidence,
                iso14224_class_method=request.iso14224_class_method,
                probed_at=request.reference_time)
            result = UpsertAssetResult(canonical_id=request.canonical_id, created=created)
            return ok_response(result, tool="kg.upsert_asset", version=_VERSION, source=_SOURCE,
                               source_query=f"upsert_asset {request.canonical_id}",
                               record_count=1, raw_tags=[request.canonical_id])
        except Exception as exc:  # noqa: BLE001
            return _fail(envelope, exc)

    @mcp.tool(name="kg.link_failure_mode")
    async def link_failure_mode(request: LinkFailureModeRequest) -> ToolResponse[dict]:
        envelope = ToolResponse[dict]
        try:
            await asset_graph.link_failure_mode(
                canonical_id=request.canonical_id,
                failure_mode_code=request.failure_mode_code)
            return ok_response(
                {"canonical_id": request.canonical_id,
                 "failure_mode_code": request.failure_mode_code, "linked": True},
                tool="kg.link_failure_mode", version=_VERSION, source=_SOURCE,
                source_query=f"link {request.canonical_id} {request.failure_mode_code}",
                record_count=1, raw_tags=[request.canonical_id])
        except InvalidFailureModePair as exc:
            return envelope.fail(ToolError(code="validation_failed", message=str(exc),
                                           retryable=False))
        except Exception as exc:  # noqa: BLE001
            return _fail(envelope, exc)

    @mcp.tool(name="kg.get_asset_context")
    async def get_asset_context(request: GetAssetContextRequest) -> ToolResponse[AssetContext]:
        envelope = ToolResponse[AssetContext]
        try:
            ctx = await asset_graph.get_asset_context(
                canonical_id=request.canonical_id, iso14224_class=request.iso14224_class)
            return ok_response(ctx, tool="kg.get_asset_context", version=_VERSION,
                               source=_SOURCE,
                               source_query=f"asset_context {request.canonical_id}",
                               record_count=1, raw_tags=[request.canonical_id])
        except Exception as exc:  # noqa: BLE001
            return _fail(envelope, exc)


__all__ = [
    "make_kg_mcp",
    "GetOntologyNodeRequest", "ListFailureModesRequest", "GetHierarchyRequest",
    "FindPathRequest",
    "OntologyNode", "FailureModeEntry", "HierarchyNode", "PathSegment",
    # Sprint 3 asset-layer tools
    "UpsertAssetRequest", "LinkFailureModeRequest", "GetAssetContextRequest",
    "UpsertAssetResult",
]
