"""Onboarding Temporal worker (Sprint 2b Track 2): `python -m rca_onboarding.worker`.

Connects to the Temporal dev cluster (the pydantic data converter wired so our models +
the crawler's models pass through payloads cleanly), builds the production ActivityDeps
(PG MAR repo, Neo4j hierarchy writer, an httpx client factory, the auto-accept threshold,
the PG runs repo, the default tenant), registers them via ``set_activity_deps``, and serves
the OnboardingWorkflow + all activities on the ``rca-onboarding`` task queue.
"""
from __future__ import annotations

import asyncio
import os
from uuid import UUID

import httpx
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from rca_kg.config import kg_database, make_async_driver
from rca_kg.write import Neo4jHierarchyWriter
from rca_mar.config import auto_accept_threshold, make_engine, make_session_factory
from rca_mar.repository_pg import PostgresRepository

from . import DEFAULT_TENANT_ID, TASK_QUEUE
from .activities import ActivityDeps, ALL_ACTIVITIES, set_activity_deps
from .runs_repo import PostgresOnboardingRunsRepo
from .workflow import OnboardingWorkflow


def temporal_host() -> str:
    return os.environ.get("TEMPORAL_HOST", "localhost:7233")


def temporal_namespace() -> str:
    return os.environ.get("TEMPORAL_NAMESPACE", "default")


def task_queue() -> str:
    return os.environ.get("TEMPORAL_TASK_QUEUE", TASK_QUEUE)


def tenant_id() -> UUID:
    return UUID(os.environ.get("ONBOARDING_TENANT_ID", DEFAULT_TENANT_ID))


def _http_factory(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=10.0)


# The activities module pulls in the AF crawler -> rca_connector_sdk -> fastmcp, which installs
# a global beartype import claw whose loader the workflow sandbox can't re-import. Pass those
# modules through so the sandbox reuses the already-loaded real modules (it imports the
# activities module under workflow.unsafe.imports_passed_through() either way; this covers the
# sandbox's workflow-validation import too).
# MAINTENANCE: this list is load-bearing — if rca_connector_sdk / the AF crawler later pull in
# another library that installs an import hook (like beartype's claw), add it here or the worker
# will fail to start with a sandbox import error.
_WORKFLOW_RUNNER = SandboxedWorkflowRunner(
    restrictions=SandboxRestrictions.default.with_passthrough_modules(
        "beartype", "fastmcp", "rca_connector_asset_hierarchy", "rca_connector_sdk"))


def build_deps() -> ActivityDeps:
    engine = make_engine()
    session_factory = make_session_factory(engine)
    repo = PostgresRepository(session_factory)
    kg = Neo4jHierarchyWriter(driver=make_async_driver(), database=kg_database())
    runs = PostgresOnboardingRunsRepo(session_factory)
    return ActivityDeps(
        repo=repo, kg=kg, http_factory=_http_factory,
        threshold=auto_accept_threshold(), runs=runs, tenant_id=tenant_id())


async def make_worker(client: Client | None = None,
                      deps: ActivityDeps | None = None) -> tuple[Client, Worker]:
    """Build (but don't run) the client + worker — used by `main` and import/registration tests."""
    if client is None:
        client = await Client.connect(
            temporal_host(), namespace=temporal_namespace(),
            data_converter=pydantic_data_converter)
    set_activity_deps(deps or build_deps())
    worker = Worker(
        client, task_queue=task_queue(), workflows=[OnboardingWorkflow],
        activities=ALL_ACTIVITIES, workflow_runner=_WORKFLOW_RUNNER)
    return client, worker


async def main() -> None:
    _client, worker = await make_worker()
    print(f"onboarding worker serving task queue {task_queue()!r} on {temporal_host()}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
