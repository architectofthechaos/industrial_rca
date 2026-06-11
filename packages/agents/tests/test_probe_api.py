"""Probe REST API (WI3/§3.6, §5.9, §6.6) — hermetic: fake Temporal client + in-memory repos."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from rca_agents.api import create_app, workflow_id_for
from rca_agents.repos import (
    InMemoryProbeMemoryRepo,
    InMemoryProbeRunsRepo,
    InMemoryRcaConclusionRepo,
)

REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)


class _FakeHandle:
    def __init__(self, store: dict, workflow_id: str) -> None:
        self._store = store
        self._wfid = workflow_id

    async def query(self, _q):
        return self._store["pending"].get(self._wfid)

    async def signal(self, _sig, body):
        self._store["signals"].append((self._wfid, body))


class _FakeClient:
    def __init__(self) -> None:
        self.started: list[dict] = []
        self.store: dict = {"pending": {}, "signals": []}

    async def start_workflow(self, run_fn, inp, *, id, task_queue):  # noqa: A002
        self.started.append({"id": id, "probe_run_id": inp.probe_run_id, "prompt": inp.prompt,
                             "task_queue": task_queue})
        return _FakeHandle(self.store, id)

    def get_workflow_handle(self, workflow_id):
        return _FakeHandle(self.store, workflow_id)


def _app(fake: _FakeClient, **repos):
    async def factory():
        return fake
    return TestClient(create_app(client_factory=factory, **repos))


def test_post_run_starts_workflow_and_returns_both_ids():
    fake = _FakeClient()
    client = _app(fake)
    resp = client.post("/probes/run", json={
        "prompt": "P-101A vibration climbing", "requested_by": "eng@deepiq.com"})
    assert resp.status_code == 202
    body = resp.json()
    assert "workflow_id" in body and "probe_run_id" in body
    assert body["workflow_id"] == workflow_id_for(body["probe_run_id"])
    assert len(fake.started) == 1
    assert fake.started[0]["probe_run_id"] == body["probe_run_id"]
    assert fake.started[0]["task_queue"] == "rca-probes"


def test_hitl_pending_returns_204_when_no_turn_then_turn_when_present():
    fake = _FakeClient()
    pid = str(uuid4())
    client = _app(fake)
    # no pending turn -> 204
    assert client.get(f"/probes/runs/{pid}/hitl/pending").status_code == 204
    # seed a pending turn for this workflow
    fake.store["pending"][workflow_id_for(pid)] = {"turn_id": "t1", "agent_name": "planning",
                                                   "questions": []}
    r = client.get(f"/probes/runs/{pid}/hitl/pending")
    assert r.status_code == 200 and r.json()["turn_id"] == "t1"


def test_hitl_respond_signals_workflow():
    fake = _FakeClient()
    pid = str(uuid4())
    client = _app(fake)
    body = {"turn_id": str(uuid4()), "approved": True, "responded_by": "eng@deepiq.com",
            "responded_at": REF.isoformat(), "answers": []}
    r = client.post(f"/probes/runs/{pid}/hitl/respond", json=body)
    assert r.status_code == 202
    assert len(fake.store["signals"]) == 1
    wfid, signaled = fake.store["signals"][0]
    assert wfid == workflow_id_for(pid)
    assert str(signaled.turn_id) == body["turn_id"]


def test_get_run_404_then_200():
    fake = _FakeClient()
    runs = InMemoryProbeRunsRepo()
    client = _app(fake, runs_repo=runs)
    pid = uuid4()
    assert client.get(f"/probes/runs/{pid}").status_code == 404
    # seed the in-memory store directly (avoid an event-loop dance inside a sync test)
    runs.runs[pid] = {"probe_run_id": str(pid), "status": "running", "plant_id": "refinery-gc"}
    r = client.get(f"/probes/runs/{pid}")
    assert r.status_code == 200 and r.json()["status"] == "running"


def test_conclusion_endpoint_404_without_persistence():
    fake = _FakeClient()
    conclusions = InMemoryRcaConclusionRepo()
    client = _app(fake, conclusion_repo=conclusions)
    assert client.get(f"/probes/runs/{uuid4()}/conclusion").status_code == 404


def test_plan_endpoints_read_probe_memory():
    fake = _FakeClient()
    mem = InMemoryProbeMemoryRepo()
    pid = uuid4()
    row = mem._row(pid)            # seed the in-memory store directly
    row["current_plan"] = {"plan_id": "p1", "version": 1}
    row["plan_history"] = [{"plan_id": "p1", "version": 1}]
    client = _app(fake, memory_repo=mem)
    assert client.get(f"/probes/runs/{pid}/plan").json()["version"] == 1
    assert len(client.get(f"/probes/runs/{pid}/plan/history").json()) == 1
