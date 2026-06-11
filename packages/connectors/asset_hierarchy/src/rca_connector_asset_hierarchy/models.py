"""Tool I/O models for the asset_hierarchy connector (Sprint 2a spec §2.2).

DiscoveredAsset/DiscoveredHierarchyNode are PROPOSALS for MAR onboarding, not MAR
rows: vendor_id is the AF WebId (stable across path renames — Sprint 2a decision),
vendor_path the AF Path, and proposed_canonical_id the slug-minted dual-key identity
that seed/onboarding may accept. ISO 14224 class fields carry the pattern-rule
provenance (`rule:<id>`, or "none" with class None / confidence 0.0).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CrawlRequest(BaseModel):
    base_url: str
    database_name: str
    plant_id: str
    max_depth: int = 6


class CrawlSubtreeRequest(BaseModel):
    base_url: str
    root_web_id: str
    plant_id: str
    max_depth: int = 6


class DiscoveredAsset(BaseModel):
    vendor_id: str
    vendor_path: str
    plant_id: str
    unit_slug: str
    name: str
    proposed_canonical_id: str
    iso14224_class: str | None
    iso14224_class_confidence: float
    iso14224_class_method: str
    attributes: dict[str, str]
    parent_unit_vendor_id: str
    parent_area_vendor_id: str
    site_vendor_id: str


class DiscoveredHierarchyNode(BaseModel):
    vendor_id: str
    vendor_path: str
    kind: Literal["site", "area", "unit"]
    name: str
    plant_id: str
    parent_vendor_id: str | None


class CrawlResult(BaseModel):
    assets: list[DiscoveredAsset]
    hierarchy_nodes: list[DiscoveredHierarchyNode]


__all__ = [
    "CrawlRequest", "CrawlSubtreeRequest",
    "DiscoveredAsset", "DiscoveredHierarchyNode", "CrawlResult",
]
