"""POST /connections/{id}/test (Sprint 2b §1.3, §1.4).

Covers: persisting last_tested_at/last_test_result; the §1.4 status transitions a test drives
(failure pending->error; success error->pending; a test never auto-activates); and that the
real connector registry probe runs (builds the connector FastMCP + calls its test_connection
tool) against a non-running base_url and reports success=False.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from rca_connections_api import create_app
from rca_connector_sdk.health import CheckResult, TestConnectionResponse
from rca_mar.repository import InMemoryRepository


def _body(**over):
    body = {
        "plant_id": "refinery-gc", "category": "historian",
        "connector_type": "pi_historian", "display_name": "PI Main",
        "base_url": "http://localhost:8001",
        "auth_config": {"type": "none", "secret_ref": None},
    }
    body.update(over)
    return body


def test_test_persists_result_and_failure_sets_error():
    async def _fail_probe(base_url, timeout, extra_config):
        return TestConnectionResponse(
            success=False,
            checks=[CheckResult(name="reachability", status="fail", latency_ms=1.0,
                                message="down")],
            error_summary="reachability: down")

    repo = InMemoryRepository()
    client = TestClient(create_app(repo=repo, probes={"pi_historian": _fail_probe}))
    cid = client.post("/connections", json=_body()).json()["connection_id"]

    resp = client.post(f"/connections/{cid}/test")
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is False

    row = client.get(f"/connections/{cid}").json()
    assert row["status"] == "error"                      # pending -> error on failure
    assert row["last_tested_at"] is not None
    assert row["last_test_result"]["success"] is False


def test_test_success_does_not_auto_activate():
    async def _ok_probe(base_url, timeout, extra_config):
        return TestConnectionResponse(success=True, checks=[])

    repo = InMemoryRepository()
    client = TestClient(create_app(repo=repo, probes={"pi_historian": _ok_probe}))
    cid = client.post("/connections", json=_body()).json()["connection_id"]

    client.post(f"/connections/{cid}/test")
    row = client.get(f"/connections/{cid}").json()
    # success from pending leaves it pending (now activatable) — NOT active.
    assert row["status"] == "pending"
    assert row["last_test_result"]["success"] is True


def test_test_success_transitions_error_to_pending():
    state = {"ok": False}

    async def _flip_probe(base_url, timeout, extra_config):
        return TestConnectionResponse(success=state["ok"], checks=[])

    repo = InMemoryRepository()
    client = TestClient(create_app(repo=repo, probes={"pi_historian": _flip_probe}))
    cid = client.post("/connections", json=_body()).json()["connection_id"]

    client.post(f"/connections/{cid}/test")              # fails -> error
    assert client.get(f"/connections/{cid}").json()["status"] == "error"

    state["ok"] = True
    client.post(f"/connections/{cid}/test")              # succeeds -> error -> pending
    assert client.get(f"/connections/{cid}").json()["status"] == "pending"


def test_real_registry_probe_against_down_url_fails_cleanly():
    """No injected probes: the REAL registry builds the pi connector FastMCP and calls its
    test_connection tool against a port nothing is listening on -> success=False, no exception."""
    repo = InMemoryRepository()
    client = TestClient(create_app(repo=repo))   # real CONNECTOR_PROBES
    cid = client.post(
        "/connections", json=_body(base_url="http://127.0.0.1:9")).json()["connection_id"]

    resp = client.post(f"/connections/{cid}/test")
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is False
    assert client.get(f"/connections/{cid}").json()["status"] == "error"


def test_unknown_connector_type_returns_no_probe_failure():
    repo = InMemoryRepository()
    client = TestClient(create_app(repo=repo))
    cid = client.post(
        "/connections",
        json=_body(connector_type="totally_unknown")).json()["connection_id"]
    resp = client.post(f"/connections/{cid}/test")
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "no test probe" in (resp.json()["error_summary"] or "")


def test_bad_secret_ref_fails_test_with_clear_summary_not_500():
    """A secret_ref that can't be resolved surfaces as a test failure naming the ref,
    not an opaque connection error and not a 500 (review fix)."""
    async def _ok_probe(base_url, timeout, extra_config):
        return TestConnectionResponse(success=True, checks=[])  # would pass if reached

    repo = InMemoryRepository()
    client = TestClient(create_app(repo=repo, probes={"pi_historian": _ok_probe}))
    cid = client.post("/connections", json=_body(
        auth_config={"type": "basic", "secret_ref": "env:DEFINITELY_MISSING_VAR_XYZ"},
    )).json()["connection_id"]

    resp = client.post(f"/connections/{cid}/test")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is False
    assert "secret_ref resolution failed" in (body["error_summary"] or "")
    assert "env:DEFINITELY_MISSING_VAR_XYZ" in body["error_summary"]
    # the probe (which would have succeeded) must NOT have run; status -> error
    assert client.get(f"/connections/{cid}").json()["status"] == "error"
