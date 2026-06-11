"""OpenAPI smoke test — the app serves a schema listing every endpoint, /docs is wired."""
from __future__ import annotations

from fastapi.testclient import TestClient

from rca_connections_api import create_app
from rca_mar.repository import InMemoryRepository


def test_openapi_lists_all_endpoints():
    client = TestClient(create_app(repo=InMemoryRepository()))
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]

    assert set(paths) == {
        "/connections",
        "/connections/{connection_id}",
        "/connections/{connection_id}/test",
        "/connections/{connection_id}/activate",
        # Resolution Queue (Sprint 2b §4.2) — same app, shared review surface.
        "/resolution_queue",
        "/resolution_queue/stats",
        "/resolution_queue/{alias_id}/validate",
        "/resolution_queue/{alias_id}/reject",
    }
    # CRUD verbs present on the right paths.
    assert set(paths["/connections"]) >= {"post", "get"}
    assert set(paths["/connections/{connection_id}"]) >= {"get", "patch", "delete"}
    assert "post" in paths["/connections/{connection_id}/test"]
    assert "post" in paths["/connections/{connection_id}/activate"]

    # Resolution Queue verbs.
    assert "get" in paths["/resolution_queue"]
    assert "get" in paths["/resolution_queue/stats"]
    assert "post" in paths["/resolution_queue/{alias_id}/validate"]
    assert "post" in paths["/resolution_queue/{alias_id}/reject"]

    assert spec["info"]["title"] == "RCA Connections API"


def test_swagger_docs_served():
    client = TestClient(create_app(repo=InMemoryRepository()))
    assert client.get("/docs").status_code == 200
