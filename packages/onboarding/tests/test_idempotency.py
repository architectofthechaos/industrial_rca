"""Idempotency (Sprint 2b §2.3) — THE headline acceptance item: a re-run with no source
change writes ZERO rows.

Proven two ways: the second project_to_mar over the same crawl returns all-zero counts AND
the InMemoryRepository's ``write_count`` (bumped on every upsert_asset/upsert_alias) is
unchanged — so the activity skipped the writes entirely, not just wrote the same values back.
project_to_kg gets the same treatment via the InMemoryHierarchyWriter's ``write_count``.
"""
from __future__ import annotations

from onb_helpers import HIERARCHY_CONNECTION_ID, PLANT_ID, hierarchy_connection

from rca_onboarding import activities as act


async def _crawl(deps):
    conn = hierarchy_connection()
    return await act._crawl_hierarchy_impl(deps, {
        "connection_id": conn.connection_id, "plant_id": conn.plant_id,
        "category": conn.category, "connector_type": conn.connector_type,
        "base_url": conn.base_url, "extra_config": conn.extra_config or {}})


async def test_project_to_mar_second_run_writes_nothing(deps):
    await deps.repo.upsert_connection(hierarchy_connection())
    result = await _crawl(deps)

    first = await act._project_to_mar_impl(
        deps, PLANT_ID, HIERARCHY_CONNECTION_ID, result.assets)
    assert first.assets_new == 4
    writes_after_first = deps.repo.write_count
    assert writes_after_first == 8  # 4 assets + 4 bindings

    # Re-crawl (fresh, identical) and re-project: zero counts, zero new writes.
    result2 = await _crawl(deps)
    second = await act._project_to_mar_impl(
        deps, PLANT_ID, HIERARCHY_CONNECTION_ID, result2.assets)
    assert second.assets_new == 0
    assert second.assets_updated == 0
    assert second.assets_decommissioned == 0
    assert second.bindings_pending_review == 0
    assert deps.repo.write_count == writes_after_first  # ZERO additional writes


async def test_project_to_kg_second_run_writes_nothing(deps):
    result = await _crawl(deps)
    assert await act._project_to_kg_impl(deps, result.hierarchy_nodes) == 6
    writes_after_first = deps.kg.write_count  # 6 nodes + 5 edges
    assert writes_after_first == 11

    result2 = await _crawl(deps)
    assert await act._project_to_kg_impl(deps, result2.hierarchy_nodes) == 6  # nodes presented
    assert deps.kg.write_count == writes_after_first  # ZERO additional writes
    assert len(deps.kg.nodes) == 6
