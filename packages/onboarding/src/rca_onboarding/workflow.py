"""OnboardingWorkflow (Sprint 2b §2.2) — deterministic orchestration only; all I/O in activities.

Step order:
  1. resolve_connections — load the active connections for the plant.
  2. write_coverage_report(start) — persist the run row as 'running'.
  3. health_check every connection in parallel (asyncio.gather over execute_activity).
  4. for the HIERARCHY connection, if healthy: crawl -> project_to_mar + project_to_kg +
     reconcile_decommission, aggregating ProjectionCounts. Unhealthy/other categories are
     recorded 'skipped:connection_unhealthy' (or 'ok') and the run still completes (partial
     coverage).
  5. write_coverage_report(end) — status completed/failed. Return OnboardingResult.

Determinism: timestamps come from ``workflow.now()`` (never datetime.now), the run id from
``workflow.uuid4()``, and every side effect goes through an activity. ``health_decision`` is a
pure helper so the per-category mapping is unit-testable without a Temporal runtime.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .activities import (
        crawl_hierarchy,
        health_check_connection,
        project_to_kg,
        project_to_mar,
        reconcile_decommission,
        resolve_connections,
        write_coverage_report,
    )
    from .models import HealthOutcome, OnboardingInput, OnboardingResult, ProjectionCounts

if TYPE_CHECKING:
    # Typing only — the crawler package eagerly imports fastmcp, which the sandbox can't load.
    from rca_connector_asset_hierarchy.models import CrawlResult, DiscoveredAsset

_ACTIVITY_TIMEOUT = timedelta(minutes=2)
_RETRY = RetryPolicy(maximum_attempts=3)


def health_decision(ok: bool) -> str:
    """Per-category result string from a health outcome (pure; unit-testable)."""
    return "ok" if ok else "skipped:connection_unhealthy"


@workflow.defn
class OnboardingWorkflow:
    @workflow.run
    async def run(self, inp: OnboardingInput) -> OnboardingResult:
        run_id = str(workflow.uuid4())
        workflow_id = workflow.info().workflow_id
        started_at = workflow.now()

        connections: list[dict[str, Any]] = await workflow.execute_activity(
            resolve_connections, inp,
            start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_RETRY)

        await workflow.execute_activity(
            write_coverage_report,
            {"phase": "start", "run_id": run_id, "workflow_id": workflow_id,
             "plant_id": inp.plant_id, "connection_ids": inp.connection_ids,
             "started_at": started_at.isoformat()},
            start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_RETRY)

        per_category_results: dict[str, str] = {}
        counts = ProjectionCounts()
        errors: list[dict] = []
        status = "completed"

        try:
            # Step 3: fan out the health checks in parallel.
            outcomes: list[HealthOutcome] = await asyncio.gather(*[
                workflow.execute_activity(
                    health_check_connection, conn,
                    start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_RETRY)
                for conn in connections])
            health_by_id = {o.connection_id: o for o in outcomes}
            for conn in connections:
                outcome = health_by_id[conn["connection_id"]]
                per_category_results[conn["category"]] = health_decision(outcome.ok)

            # Step 4: project the hierarchy connection(s) that are healthy.
            for conn in connections:
                if conn["category"] != "hierarchy":
                    continue
                if not health_by_id[conn["connection_id"]].ok:
                    continue  # already recorded skipped:connection_unhealthy
                conn_counts = await self._project_hierarchy(inp.plant_id, conn)
                counts = counts.merged_with(conn_counts)
        except Exception as exc:  # noqa: BLE001 — surface as a failed run, still write the report
            status = "failed"
            errors.append({"type": type(exc).__name__, "message": str(exc)})

        completed_at = workflow.now()
        await workflow.execute_activity(
            write_coverage_report,
            {"phase": "end", "run_id": run_id, "status": status,
             "per_category_results": per_category_results,
             "counts": counts.model_dump(), "errors": errors,
             "completed_at": completed_at.isoformat()},
            start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_RETRY)

        return OnboardingResult(
            run_id=run_id, workflow_id=workflow_id, status=status,
            per_category_results=per_category_results, counts=counts, errors=errors)

    async def _project_hierarchy(self, plant_id: str, conn: dict[str, Any]) -> ProjectionCounts:
        connection_id = conn["connection_id"]
        result: CrawlResult = await workflow.execute_activity(
            crawl_hierarchy, conn,
            start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_RETRY)
        assets: list[DiscoveredAsset] = result.assets
        seen_vendor_ids = [a.vendor_id for a in assets]

        mar_counts: ProjectionCounts = await workflow.execute_activity(
            project_to_mar, args=[plant_id, connection_id, assets],
            start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_RETRY)
        kg_count: int = await workflow.execute_activity(
            project_to_kg, result.hierarchy_nodes,
            start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_RETRY)
        decommissioned: int = await workflow.execute_activity(
            reconcile_decommission, args=[plant_id, connection_id, seen_vendor_ids],
            start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_RETRY)

        return mar_counts.merged_with(ProjectionCounts(
            hierarchy_nodes_upserted=kg_count, assets_decommissioned=decommissioned))


__all__ = ["OnboardingWorkflow", "health_decision"]
