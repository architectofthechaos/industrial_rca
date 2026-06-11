"""rca_connector_asset_hierarchy — the PI AF crawler connector (Sprint 2a Task 7).

Crawls the PI AF REST surface (the EPIC-002 PI simulator in dev, a real PI Web API
in prod) into DiscoveredAsset / DiscoveredHierarchyNode proposals for MAR onboarding.
vendor_id is the AF WebId (stable across path renames); ISO 14224 classes come from
the deterministic pattern-rule registry (rca_mar.pattern_rules). Product code:
never imports rca_simulator.
"""
from .crawler import crawl, crawl_subtree
from .models import (
    CrawlRequest,
    CrawlResult,
    CrawlSubtreeRequest,
    DiscoveredAsset,
    DiscoveredHierarchyNode,
)
from .server import make_asset_hierarchy_mcp

__all__ = [
    "crawl", "crawl_subtree", "make_asset_hierarchy_mcp",
    "CrawlRequest", "CrawlSubtreeRequest", "CrawlResult",
    "DiscoveredAsset", "DiscoveredHierarchyNode",
]
