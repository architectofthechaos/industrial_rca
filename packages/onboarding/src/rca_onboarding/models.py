"""Pydantic I/O models for the onboarding workflow (Sprint 2b Track 2).

All flat + JSON-serializable so they travel cleanly as Temporal payloads via the
``temporalio.contrib.pydantic`` data converter wired on both client and worker. The crawler's
own ``DiscoveredAsset`` / ``DiscoveredHierarchyNode`` / ``CrawlResult`` (also pydantic) pass
through the same converter, so activities take/return those models directly rather than dicts.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class OnboardingInput(BaseModel):
    plant_id: str
    connection_ids: list[str] | None = None


class HealthOutcome(BaseModel):
    connection_id: str
    category: str
    ok: bool
    error: str | None = None


class ProjectionCounts(BaseModel):
    assets_new: int = 0
    assets_updated: int = 0
    assets_decommissioned: int = 0
    bindings_pending_review: int = 0
    hierarchy_nodes_upserted: int = 0

    def merged_with(self, other: ProjectionCounts) -> ProjectionCounts:
        """Field-wise sum (the workflow aggregates per-connection counts into a run total)."""
        return ProjectionCounts(
            assets_new=self.assets_new + other.assets_new,
            assets_updated=self.assets_updated + other.assets_updated,
            assets_decommissioned=self.assets_decommissioned + other.assets_decommissioned,
            bindings_pending_review=self.bindings_pending_review + other.bindings_pending_review,
            hierarchy_nodes_upserted=(
                self.hierarchy_nodes_upserted + other.hierarchy_nodes_upserted))


class OnboardingResult(BaseModel):
    run_id: str
    workflow_id: str
    status: str
    per_category_results: dict[str, str] = Field(default_factory=dict)
    counts: ProjectionCounts = Field(default_factory=ProjectionCounts)
    errors: list[dict] = Field(default_factory=list)


__all__ = ["OnboardingInput", "HealthOutcome", "ProjectionCounts", "OnboardingResult"]
