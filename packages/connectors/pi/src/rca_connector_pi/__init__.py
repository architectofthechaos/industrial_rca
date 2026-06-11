"""rca_connector_pi — the PI-backed entity MCPs (Sprint 2b Track 3).

Repurposes the former vendor-prefixed PI connector into two canonical entity MCPs that
both front the PI Web API REST surface (the EPIC-002 PI simulator in dev, a real PI server
in prod): ``tag`` (PI historian) and ``operator_log`` (PI event frames). No ``pi.*`` tool
name exists. Product code never imports rca_simulator (ADR-0012).
"""
from .gateway import AssetGateway, CanonicalSlugAssetGateway, StaticAssetGateway
from .server import make_operator_log_mcp, make_tag_mcp

__all__ = [
    "make_tag_mcp", "make_operator_log_mcp",
    "AssetGateway", "CanonicalSlugAssetGateway", "StaticAssetGateway",
]
