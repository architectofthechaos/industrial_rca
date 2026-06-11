"""Onboarding API tests (Sprint 2b §2.4) — inject a fake Temporal client + in-memory runs repo
so the trigger/query endpoints are exercised without a live cluster.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from rca_onboarding.api import create_app
from rca_onboarding.runs_repo import InMemoryOnboardingRunsRepo


class _FakeHandle:
    run_id = "run-abc"


class _FakeClient:
    def __init__(self) -> None:
        self.started: list[dict] = []

    async def start_workflow(self, run_fn, inp, *, id, task_queue):  # noqa: A002
        self.started.append({"id": id, "task_queue": task_queue, "plant_id": inp.plant_id})
        return _FakeHandle()


def _now() -> datetime:
    return datetime(2026, 6, 11, tzinfo=timezone.utc)


async def test_post_run_starts_workflow_and_returns_ids():
    fake = _FakeClient()
    runs = InMemoryOnboardingRunsRepo()

    async def factory():
        return fake

    client = TestClient(create_app(client_factory=factory, runs_repo=runs))
    resp = client.post("/onboarding/run", json={"plant_id": "refinery-gc"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["workflow_id"].startswith("onboarding-refinery-gc-")
    # the 202 returns only workflow_id — a Temporal start handle has no application run_id yet
    assert "run_id" not in body
    assert len(fake.started) == 1
    assert fake.started[0]["task_queue"] == "rca-onboarding"


async def test_get_run_404_then_found():
    runs = InMemoryOnboardingRunsRepo()
    await runs.create_run("11111111-1111-1111-1111-111111111111", "wf-1", "refinery-gc",
                          None, _now())

    async def factory():
        return _FakeClient()

    client = TestClient(create_app(client_factory=factory, runs_repo=runs))
    assert client.get("/onboarding/runs/does-not-exist").status_code == 404
    found = client.get("/onboarding/runs/11111111-1111-1111-1111-111111111111")
    assert found.status_code == 200
    assert found.json()["status"] == "running"
    # the row is also resolvable by workflow_id — the key the 202 hands back to callers
    by_wf = client.get("/onboarding/runs/wf-1")
    assert by_wf.status_code == 200
    assert by_wf.json()["run_id"] == "11111111-1111-1111-1111-111111111111"


async def test_list_runs_filters():
    runs = InMemoryOnboardingRunsRepo()
    await runs.create_run("11111111-1111-1111-1111-111111111111", "wf-1", "refinery-gc",
                          None, _now())
    await runs.complete_run("11111111-1111-1111-1111-111111111111", "completed", {}, {}, [],
                            _now())
    await runs.create_run("22222222-2222-2222-2222-222222222222", "wf-2", "other-plant",
                          None, _now())

    async def factory():
        return _FakeClient()

    client = TestClient(create_app(client_factory=factory, runs_repo=runs))
    all_runs = client.get("/onboarding/runs").json()
    assert len(all_runs) == 2
    completed = client.get("/onboarding/runs?status=completed").json()
    assert [r["run_id"] for r in completed] == ["11111111-1111-1111-1111-111111111111"]
    by_plant = client.get("/onboarding/runs?plant_id=other-plant").json()
    assert [r["run_id"] for r in by_plant] == ["22222222-2222-2222-2222-222222222222"]
