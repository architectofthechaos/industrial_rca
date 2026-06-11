"""One-active-source-per-category conflict (Sprint 2b §1.4) — the highest-value acceptance.

Register + test + activate connection A (cmms); register + test B (same plant + cmms);
activating B returns a structured 409 ``{error: "category_conflict",
conflicting_connection_id: <A's id>}``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from rca_connections_api import create_app
from rca_connector_sdk.health import TestConnectionResponse
from rca_mar.repository import InMemoryRepository


async def _ok_probe(base_url, timeout, extra_config):
    return TestConnectionResponse(success=True, checks=[])


def _client():
    repo = InMemoryRepository()
    app = create_app(repo=repo, probes={"maximo": _ok_probe})
    return TestClient(app), repo


def _register_test_cmms(client, display_name):
    body = {
        "plant_id": "refinery-gc", "category": "cmms", "connector_type": "maximo",
        "display_name": display_name, "base_url": "http://localhost:8002",
        "auth_config": {"type": "none", "secret_ref": None},
    }
    created = client.post("/connections", json=body)
    assert created.status_code == 201, created.text
    cid = created.json()["connection_id"]
    tested = client.post(f"/connections/{cid}/test")
    assert tested.status_code == 200, tested.text
    assert tested.json()["success"] is True
    return cid


def test_second_activation_same_category_409():
    client, _ = _client()
    a_id = _register_test_cmms(client, "Maximo A")
    b_id = _register_test_cmms(client, "Maximo B")

    activate_a = client.post(f"/connections/{a_id}/activate")
    assert activate_a.status_code == 200, activate_a.text
    assert activate_a.json()["status"] == "active"

    activate_b = client.post(f"/connections/{b_id}/activate")
    assert activate_b.status_code == 409, activate_b.text
    detail = activate_b.json()["detail"]
    assert detail["error"] == "category_conflict"
    assert detail["conflicting_connection_id"] == a_id


def test_activate_requires_prior_successful_test():
    client, _ = _client()
    body = {
        "plant_id": "refinery-gc", "category": "cmms", "connector_type": "maximo",
        "display_name": "Untested", "base_url": "http://localhost:8002",
        "auth_config": {"type": "none", "secret_ref": None},
    }
    cid = client.post("/connections", json=body).json()["connection_id"]
    resp = client.post(f"/connections/{cid}/activate")
    assert resp.status_code == 409
    assert "test" in resp.json()["detail"].lower()


def test_activate_only_from_pending():
    client, _ = _client()
    a_id = _register_test_cmms(client, "Maximo A")
    assert client.post(f"/connections/{a_id}/activate").status_code == 200
    # second activate of the SAME already-active connection: not pending -> 409
    resp = client.post(f"/connections/{a_id}/activate")
    assert resp.status_code == 409
