"""Onboarding trigger/query REST API (Sprint 2b §2.4): `uvicorn rca_onboarding.api:create_app`.

- POST /onboarding/run {plant_id, connection_ids?} -> start the OnboardingWorkflow on the
  Temporal cluster and return {run_id, workflow_id} immediately (202; async). The workflow
  itself writes the onboarding_runs row (start + end), so the API does not create it — that
  keeps the runs row single-writer (the worker) and avoids a race with the workflow's own
  start-phase write.
- GET /onboarding/runs/{run_id} -> the persisted run row (404 if unknown).
- GET /onboarding/runs?plant_id=&status=&limit= -> list of run rows.
- OpenAPI/Swagger at /docs.

``client_factory`` (async, returns a connected Temporal ``Client``) and ``runs_repo`` are
injectable so tests drive the API without a live Temporal cluster. In production both are
built from env config lazily.
"""
from __future__ import annotations

import os
from typing import Any, Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .models import OnboardingInput

ClientFactory = Callable[[], Awaitable[Any]]


class RunRequest(BaseModel):
    plant_id: str
    connection_ids: list[str] | None = None


def create_app(*, client_factory: ClientFactory | None = None,
               runs_repo: Any | None = None) -> FastAPI:
    factory = client_factory or _default_client_factory
    repo = runs_repo if runs_repo is not None else _default_runs_repo()

    app = FastAPI(title="RCA Onboarding API", version="0.0.1")

    @app.post("/onboarding/run", status_code=202)
    async def start_run(body: RunRequest) -> dict[str, str]:
        from .workflow import OnboardingWorkflow  # lazy: keeps temporalio off the import path
        workflow_id = f"onboarding-{body.plant_id}-{uuid4()}"
        client = await factory()
        handle = await client.start_workflow(
            OnboardingWorkflow.run,
            OnboardingInput(plant_id=body.plant_id, connection_ids=body.connection_ids),
            id=workflow_id, task_queue=_task_queue())
        # The workflow mints its own run_id; expose the workflow_id (and run_id once known via
        # the runs list / the workflow result). For the immediate 202 we return the workflow_id
        # as the durable handle the caller polls with.
        return {"workflow_id": workflow_id, "run_id": getattr(handle, "run_id", workflow_id)}

    @app.get("/onboarding/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        rec = await repo.get_run(run_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"onboarding run {run_id!r} not found")
        return rec.to_dict()

    @app.get("/onboarding/runs")
    async def list_runs(plant_id: str | None = None, status: str | None = None,
                        limit: int = 50) -> list[dict[str, Any]]:
        rows = await repo.list_runs(plant_id=plant_id, status=status, limit=limit)
        return [r.to_dict() for r in rows]

    return app


def _task_queue() -> str:
    from . import TASK_QUEUE
    return os.environ.get("TEMPORAL_TASK_QUEUE", TASK_QUEUE)


async def _default_client_factory() -> Any:
    from temporalio.client import Client
    from temporalio.contrib.pydantic import pydantic_data_converter

    from .worker import temporal_host, temporal_namespace
    return await Client.connect(
        temporal_host(), namespace=temporal_namespace(),
        data_converter=pydantic_data_converter)


def _default_runs_repo() -> Any:
    from rca_mar.config import make_engine, make_session_factory

    from .runs_repo import PostgresOnboardingRunsRepo
    engine = make_engine()
    return PostgresOnboardingRunsRepo(make_session_factory(engine))


__all__ = ["create_app", "RunRequest"]
