"""FastMCP server for MAR read/resolve tools (hand-wired; they read MAR's own repository).

Reuses the connector_sdk envelope/provenance/error-mapping discipline: every tool returns
ToolResponse[T] with provenance, and exceptions become a mapped ToolError. status='unresolved'
/'ambiguous' are SUCCESSFUL results (not errors); assets.get on a missing id is not_found.

assets.get accepts exactly one of asset_id (UUID) or canonical_id (dual-key identity,
Phase 1 spec §2.1); the resolve auto-accept gate defaults to MAR_AUTO_ACCEPT_THRESHOLD
(env, default 0.92) unless the request sets min_confidence explicitly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastmcp import FastMCP
from pydantic import AwareDatetime, BaseModel
from rca_connector_sdk import NotFound, ProvenanceAccumulator, build_server, map_source_error
from rca_contracts import (
    AssetDescriptor,
    ResolveAssetOutput,
    ToolError,
    ToolResponse,
)

from .pattern_rules import PatternRule, load_rules
from .repository import AssetRepository
from .resolution import resolve_asset

_VERSION = "0.1.0"
_SOURCE = "mar"


class ResolveRequest(BaseModel):
    external_id: str
    source_system: str
    time: AwareDatetime | None = None
    min_confidence: float | None = None  # None -> MAR_AUTO_ACCEPT_THRESHOLD (default 0.92)


class GetRequest(BaseModel):
    asset_id: UUID | None = None
    canonical_id: str | None = None


class SearchRequest(BaseModel):
    iso14224_class: str | None = None
    tag_pattern: str | None = None
    canonical_id_pattern: str | None = None
    criticality: list[str] | None = None
    service: str | None = None
    limit: int = 50


def _ok(envelope, data, *, tool, source_query, record_count, raw_tags):
    prov = ProvenanceAccumulator()
    prov.record(source_query=source_query, record_count=record_count, raw_tags=raw_tags)
    provenance = prov.build(tool_name=tool, tool_version=_VERSION, source=_SOURCE,
                            queried_at=datetime.now(timezone.utc), response_id=uuid4())
    return envelope.ok(data, provenance)


def make_mar_mcp(*, repo: AssetRepository, tenant_id: UUID,
                 rules: list[PatternRule] | None = None) -> FastMCP:
    """Build the MAR FastMCP server. rules=None uses the default pattern-rule registry
    (loaded eagerly here so a broken registry fails at construction, not first resolve;
    load_rules() is cached so this costs nothing); rules=[] disables resolution step 3."""
    if rules is None:
        load_rules()  # fail fast on a corrupt/invalid registry file
    mcp = build_server("mar")

    @mcp.tool(name="assets.resolve")
    async def resolve(request: ResolveRequest) -> ToolResponse[ResolveAssetOutput]:
        envelope = ToolResponse[ResolveAssetOutput]
        try:
            r = await resolve_asset(repo, request.external_id, request.source_system, tenant_id,
                                    valid_at=request.time, min_confidence=request.min_confidence,
                                    rules=rules)
            asset = await repo.get_asset(tenant_id, r.asset_id) if r.asset_id else None
            alts = [a for a in
                    [await repo.get_asset(tenant_id, x) for x in r.alternatives] if a is not None]
            out = ResolveAssetOutput(status=r.status, asset=asset,
                                     canonical_id=asset.canonical_id if asset else None,
                                     confidence=r.confidence,
                                     mapping_source=r.mapping_source, alternatives=alts)
            return _ok(envelope, out, tool="assets.resolve",
                       source_query=f"resolve {request.source_system}:{request.external_id}",
                       record_count=1 if asset else 0,
                       raw_tags=[f"{request.source_system}:{request.external_id}"])
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="assets.get")
    async def get(request: GetRequest) -> ToolResponse[AssetDescriptor]:
        envelope = ToolResponse[AssetDescriptor]
        try:
            if (request.asset_id is None) == (request.canonical_id is None):
                return envelope.fail(ToolError(
                    code="validation_failed",
                    message="assets.get requires exactly one of asset_id or canonical_id",
                    retryable=False))
            if request.asset_id is not None:
                key = str(request.asset_id)
                asset = await repo.get_asset(tenant_id, request.asset_id)
            else:
                assert request.canonical_id is not None  # guarded by the XOR check above
                key = request.canonical_id
                asset = await repo.find_asset_by_canonical_id(tenant_id, request.canonical_id)
            if asset is None:
                raise NotFound(f"asset {key} not found")
            return _ok(envelope, asset, tool="assets.get",
                       source_query=f"get {key}", record_count=1,
                       raw_tags=[key])
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="assets.search")
    async def search(request: SearchRequest) -> ToolResponse[list[AssetDescriptor]]:
        envelope = ToolResponse[list[AssetDescriptor]]
        try:
            assets = await repo.search_assets(
                tenant_id, iso14224_class=request.iso14224_class, tag_pattern=request.tag_pattern,
                canonical_id_pattern=request.canonical_id_pattern, criticality=request.criticality,
                service=request.service, limit=request.limit)
            return _ok(envelope, assets, tool="assets.search",
                       source_query=(f"search class={request.iso14224_class}"
                                     f" tag={request.tag_pattern}"
                                     f" canonical_id={request.canonical_id_pattern}"),
                       record_count=len(assets), raw_tags=[a.tag for a in assets])
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    return mcp


__all__ = ["make_mar_mcp", "ResolveRequest", "GetRequest", "SearchRequest"]
