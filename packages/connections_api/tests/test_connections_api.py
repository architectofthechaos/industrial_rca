"""Connections API CRUD + lifecycle tests (Sprint 2b §1.3, §1.5).

Hermetic: a FastAPI TestClient over create_app(repo=InMemoryRepository()). No DB, no sim.
"""
from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from rca_connections_api import create_app
from rca_connector_sdk.health import TestConnectionResponse
from rca_mar.repository import AliasRow, InMemoryRepository
from datetime import datetime, timezone
from uuid import uuid4


def _client(repo=None, **kw):
    repo = repo or InMemoryRepository()
    app = create_app(repo=repo, **kw)
    return TestClient(app), repo


def _create_body(**over):
    body = {
        "plant_id": "refinery-gc",
        "category": "historian",
        "connector_type": "pi_historian",
        "display_name": "PI Main",
        "base_url": "http://localhost:8001",
        "auth_config": {"type": "none", "secret_ref": None},
    }
    body.update(over)
    return body


# -- create --------------------------------------------------------------

def test_post_synthesizes_id_and_pending_status():
    client, _ = _client()
    resp = client.post("/connections", json=_create_body())
    assert resp.status_code == 201, resp.text
    data = resp.json()
    # id = {plant}.{category}.{slug(display_name)}
    assert data["connection_id"] == "refinery-gc.historian.pi-main"
    assert data["status"] == "pending"
    assert data["auth_config"] == {"type": "none", "secret_ref": None}


def test_post_duplicate_id_409():
    client, _ = _client()
    assert client.post("/connections", json=_create_body()).status_code == 201
    dup = client.post("/connections", json=_create_body())
    assert dup.status_code == 409


# -- list ----------------------------------------------------------------

def test_list_filters_by_plant_category_status():
    client, _ = _client()
    client.post("/connections", json=_create_body(display_name="A", category="historian"))
    client.post("/connections", json=_create_body(display_name="B", category="cmms",
                                                   connector_type="maximo"))
    client.post("/connections", json=_create_body(display_name="C", plant_id="other-plant",
                                                   category="historian"))

    all_gc = client.get("/connections", params={"plant_id": "refinery-gc"}).json()
    assert {c["connection_id"] for c in all_gc} == {
        "refinery-gc.historian.a", "refinery-gc.cmms.b"}

    cmms = client.get("/connections",
                      params={"plant_id": "refinery-gc", "category": "cmms"}).json()
    assert [c["connection_id"] for c in cmms] == ["refinery-gc.cmms.b"]

    pending = client.get("/connections", params={"status": "pending"}).json()
    assert len(pending) == 3   # nothing activated yet


# -- get single ----------------------------------------------------------

def test_get_single_and_404():
    client, _ = _client()
    client.post("/connections", json=_create_body())
    ok = client.get("/connections/refinery-gc.historian.pi-main")
    assert ok.status_code == 200
    missing = client.get("/connections/nope.historian.x")
    assert missing.status_code == 404


# -- patch ---------------------------------------------------------------

def test_patch_allowed_fields():
    client, _ = _client()
    client.post("/connections", json=_create_body())
    resp = client.patch("/connections/refinery-gc.historian.pi-main",
                        json={"display_name": "Renamed", "base_url": "http://host:9000"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["display_name"] == "Renamed"
    assert data["base_url"] == "http://host:9000"
    # connection_id never changes on rename
    assert data["connection_id"] == "refinery-gc.historian.pi-main"


def test_patch_forbidden_field_rejected():
    client, _ = _client()
    client.post("/connections", json=_create_body())
    # connector_type / plant_id are not patchable; extra=forbid -> 422
    resp = client.patch("/connections/refinery-gc.historian.pi-main",
                        json={"connector_type": "maximo"})
    assert resp.status_code == 422


def test_patch_endpoint_driven_status_rejected():
    client, _ = _client()
    client.post("/connections", json=_create_body())
    # pending -> active is /activate's job, not PATCH's -> 409
    resp = client.patch("/connections/refinery-gc.historian.pi-main",
                        json={"status": "active"})
    assert resp.status_code == 409


# -- delete --------------------------------------------------------------

def test_delete_hard_when_no_aliases():
    client, repo = _client()
    client.post("/connections", json=_create_body())
    resp = client.delete("/connections/refinery-gc.historian.pi-main")
    assert resp.status_code == 204
    # hard-deleted: gone from the repo
    assert client.get("/connections/refinery-gc.historian.pi-main").status_code == 404


def test_delete_soft_when_aliases_reference_it():
    client, repo = _client()
    client.post("/connections", json=_create_body())
    cid = "refinery-gc.historian.pi-main"
    # an alias referencing the connection blocks the hard delete -> soft disable only.
    # InMemoryRepository.upsert_alias only touches in-memory lists, so a synchronous append
    # to repo.aliases is equivalent and avoids spinning a second event loop under TestClient.
    repo.aliases.append(AliasRow(
        asset_id=uuid4(), tenant_id=uuid4(), connection_id=cid, external_id="X1",
        valid_from=datetime(1970, 1, 1, tzinfo=timezone.utc), valid_to=None,
        mapping_source="authoritative_import", confidence=1.0))
    resp = client.delete(f"/connections/{cid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "disabled"
    # still present (soft delete)
    assert client.get(f"/connections/{cid}").json()["status"] == "disabled"


# -- activation_listener seam (Sprint 6 WI4 G29) -------------------------

async def _ok_probe_historian(base_url, timeout, extra_config):
    return TestConnectionResponse(success=True, checks=[])


def _create_test_activate(client):
    """Helper: create → test → activate a historian connection. Returns connection_id."""
    body = _create_body()
    cid = client.post("/connections", json=body).json()["connection_id"]
    tested = client.post(f"/connections/{cid}/test")
    assert tested.status_code == 200 and tested.json()["success"] is True, tested.text
    return cid


def test_activation_listener_invoked_on_activate():
    """An activation_listener injected via create_app receives the activated row."""
    received: list = []

    async def _listener(row):
        received.append(row)

    repo = InMemoryRepository()
    client, _ = _client(
        repo=repo,
        probes={"pi_historian": _ok_probe_historian},
        activation_listener=_listener,
    )
    cid = _create_test_activate(client)
    resp = client.post(f"/connections/{cid}/activate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"

    assert len(received) == 1
    row = received[0]
    assert row.connection_id == cid
    assert row.status == "active"
    assert row.category == "historian"


def test_activation_listener_failure_does_not_break_activation():
    """A listener that raises must not cause activation to fail (error is swallowed)."""

    async def _bad_listener(row):
        raise RuntimeError("listener exploded")

    repo = InMemoryRepository()
    client, _ = _client(
        repo=repo,
        probes={"pi_historian": _ok_probe_historian},
        activation_listener=_bad_listener,
    )
    cid = _create_test_activate(client)
    resp = client.post(f"/connections/{cid}/activate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"


# -- deactivation_listener seam (Sprint 6 WI4 D16) -----------------------

def test_deactivation_listener_invoked_on_patch_to_disabled():
    """A deactivation_listener receives the row when PATCH drives status to 'disabled'."""
    received: list = []

    async def _listener(row):
        received.append(row)

    repo = InMemoryRepository()
    client, _ = _client(
        repo=repo,
        probes={"pi_historian": _ok_probe_historian},
        deactivation_listener=_listener,
    )
    cid = _create_test_activate(client)
    # activate first so the transition active->disabled is valid
    client.post(f"/connections/{cid}/activate")
    assert len(received) == 0  # listener not triggered by activate

    resp = client.patch(f"/connections/{cid}", json={"status": "disabled"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "disabled"

    assert len(received) == 1
    row = received[0]
    assert row.connection_id == cid
    assert row.status == "disabled"


def test_deactivation_listener_invoked_on_delete():
    """A deactivation_listener receives the row when DELETE soft-disables the connection."""
    received: list = []

    async def _listener(row):
        received.append(row)

    repo = InMemoryRepository()
    client, _ = _client(
        repo=repo,
        probes={"pi_historian": _ok_probe_historian},
        deactivation_listener=_listener,
    )
    cid = _create_test_activate(client)
    client.post(f"/connections/{cid}/activate")

    resp = client.delete(f"/connections/{cid}")
    # hard-deleted (no aliases) -> 204
    assert resp.status_code == 204, resp.text

    assert len(received) == 1
    row = received[0]
    assert row.connection_id == cid
    assert row.status == "disabled"


def test_deactivation_listener_failure_does_not_break_request():
    """A raising deactivation_listener must not cause PATCH/DELETE to fail."""

    async def _bad_listener(row):
        raise RuntimeError("deactivation listener exploded")

    repo = InMemoryRepository()
    client, _ = _client(
        repo=repo,
        probes={"pi_historian": _ok_probe_historian},
        deactivation_listener=_bad_listener,
    )
    cid = _create_test_activate(client)
    client.post(f"/connections/{cid}/activate")

    # PATCH to disabled still succeeds despite listener exception
    resp = client.patch(f"/connections/{cid}", json={"status": "disabled"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "disabled"

    # Re-create to test DELETE path
    repo2 = InMemoryRepository()
    client2, _ = _client(
        repo=repo2,
        probes={"pi_historian": _ok_probe_historian},
        deactivation_listener=_bad_listener,
    )
    cid2 = _create_test_activate(client2)
    client2.post(f"/connections/{cid2}/activate")
    resp2 = client2.delete(f"/connections/{cid2}")
    assert resp2.status_code == 204, resp2.text


# -- secret never exposed (§1.5) -----------------------------------------

_SECRET_ENV = "PI_TEST_PASSWORD_XYZ"
_SECRET_VALUE = "super-secret-value-3f9a2"


@pytest.fixture()
def _secret_env(monkeypatch):
    monkeypatch.setenv(_SECRET_ENV, _SECRET_VALUE)


def test_secret_ref_value_never_in_any_response(_secret_env):
    """The resolved secret value must never appear in any GET/list/POST response body."""

    async def _fake_probe(base_url, timeout, extra_config):
        return TestConnectionResponse(success=True, checks=[])

    client, _ = _client(probes={"pi_historian": _fake_probe})
    body = _create_body(
        auth_config={"type": "bearer", "secret_ref": f"env:{_SECRET_ENV}"})
    created = client.post("/connections", json=body)
    cid = created.json()["connection_id"]
    # secret_ref pointer IS returned; the resolved value is NOT.
    assert created.json()["auth_config"]["secret_ref"] == f"env:{_SECRET_ENV}"

    bodies = [
        created.text,
        client.get(f"/connections/{cid}").text,
        client.get("/connections").text,
        client.post(f"/connections/{cid}/test").text,   # resolves the secret internally
        client.get(f"/connections/{cid}").text,          # after the test result is persisted
    ]
    for text in bodies:
        assert _SECRET_VALUE not in text
