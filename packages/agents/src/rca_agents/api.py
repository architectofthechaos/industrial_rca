"""Probe REST API (Sprint 3 WI3/WI5/WI6 §3.6/§5.9/§6.6).

FastAPI surface over the ProbeWorkflow. ``POST /probes/run`` starts the workflow and returns
both ids (the API mints ``probe_run_id`` so it can 202-return it, G10/G11). The HITL endpoints
are the G20 bridge: ``GET .../hitl/pending`` queries the running workflow; ``POST
.../hitl/respond`` signals it — LangGraph never signals Temporal, only this handler does.

UX is API-only in Sprint 3 (risk #2): engineers interact via curl/Postman.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Response
from rca_contracts import HitlResponse, StartProbeRequest

from .config import DEFAULT_PLANT_ID, task_queue

ClientFactory = Callable[[], Awaitable[Any]]


def workflow_id_for(probe_run_id: str) -> str:
    return f"probe-{probe_run_id}"


def create_app(*, client_factory: ClientFactory | None = None, runs_repo: Any = None,
               memory_repo: Any = None, conclusion_repo: Any = None) -> FastAPI:
    factory = client_factory or _default_client_factory
    app = FastAPI(title="RCA Probe API", version="0.0.1")

    async def _client():
        return await factory()

    @app.post("/probes/run", status_code=202)
    async def start_probe(body: StartProbeRequest) -> dict[str, str]:
        from .models import ProbeWorkflowInput
        from .workflow import ProbeWorkflow
        probe_run_id = str(uuid4())
        workflow_id = workflow_id_for(probe_run_id)
        client = await _client()
        await client.start_workflow(
            ProbeWorkflow.run,
            ProbeWorkflowInput(prompt=body.prompt, plant_id=body.plant_id or DEFAULT_PLANT_ID,
                               reference_time=body.reference_time,
                               requested_by=body.requested_by, probe_run_id=probe_run_id),
            id=workflow_id, task_queue=task_queue())
        return {"workflow_id": workflow_id, "probe_run_id": probe_run_id}

    @app.get("/probes/runs/{probe_run_id}")
    async def get_run(probe_run_id: str) -> dict[str, Any]:
        run = await _require_repo(runs_repo).get_run(UUID(probe_run_id))
        if run is None:
            raise HTTPException(404, f"probe run {probe_run_id!r} not found")
        return _jsonable(run)

    @app.get("/probes/runs/{probe_run_id}/hitl/pending", response_model=None)
    async def hitl_pending(probe_run_id: str) -> Response | dict[str, Any]:
        from .workflow import ProbeWorkflow
        client = await _client()
        handle = client.get_workflow_handle(workflow_id_for(probe_run_id))
        turn = await handle.query(ProbeWorkflow.pending_hitl_turn)
        if not turn:
            return Response(status_code=204)
        return turn

    @app.post("/probes/runs/{probe_run_id}/hitl/respond", status_code=202)
    async def hitl_respond(probe_run_id: str, body: HitlResponse) -> dict[str, str]:
        from .workflow import ProbeWorkflow
        client = await _client()
        handle = client.get_workflow_handle(workflow_id_for(probe_run_id))
        await handle.signal(ProbeWorkflow.hitl_response, body)
        return {"status": "signaled", "turn_id": str(body.turn_id)}

    @app.get("/probes/runs/{probe_run_id}/plan")
    async def get_plan(probe_run_id: str) -> dict[str, Any]:
        mem = await _require_repo(memory_repo).get(UUID(probe_run_id))
        if mem is None or mem.get("current_plan") is None:
            raise HTTPException(404, "no plan yet")
        return mem["current_plan"]

    @app.get("/probes/runs/{probe_run_id}/plan/history")
    async def get_plan_history(probe_run_id: str) -> list[dict[str, Any]]:
        mem = await _require_repo(memory_repo).get(UUID(probe_run_id))
        return (mem or {}).get("plan_history", [])

    @app.get("/probes/runs/{probe_run_id}/conclusion")
    async def get_conclusion(probe_run_id: str) -> dict[str, Any]:
        c = await _require_repo(conclusion_repo).get_for_probe(UUID(probe_run_id))
        if c is None:
            raise HTTPException(404, "no conclusion yet")
        return c.model_dump(mode="json")

    @app.get("/probes/runs/{probe_run_id}/followup_wo")
    async def get_followup_wo(probe_run_id: str) -> dict[str, Any]:
        run = await _require_repo(runs_repo).get_run(UUID(probe_run_id))
        wo = (run or {}).get("followup_wo") if run else None
        if not wo:
            raise HTTPException(404, "no follow-up WO")
        return wo

    return app


def _require_repo(repo: Any) -> Any:
    if repo is None:
        raise HTTPException(503, "this endpoint requires a persistence repo (not configured)")
    return repo


def _jsonable(run: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in run.items():
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


async def _default_client_factory() -> Any:
    from temporalio.client import Client
    from temporalio.contrib.pydantic import pydantic_data_converter

    from .config import temporal_host, temporal_namespace
    return await Client.connect(temporal_host(), namespace=temporal_namespace(),
                                data_converter=pydantic_data_converter)


def create_live_app() -> FastAPI:
    """Live entrypoint: wire Postgres repos so plan/conclusion/run endpoints work."""
    import os

    from .deps import build_repos

    use_pg = os.environ.get("PROBE_USE_POSTGRES", "1") == "1"
    runs, memory, _evidence, conclusions = build_repos(use_postgres=use_pg)
    return create_app(runs_repo=runs, memory_repo=memory, conclusion_repo=conclusions)


__all__ = ["create_app", "create_live_app", "workflow_id_for"]
