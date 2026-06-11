"""FastAPI app factory for the Connections API (Sprint 2b §1).

``create_app`` wires the connections router over an ``AssetRepository``. For production the
repo is None and a Postgres-backed repo is built from the MAR config; tests inject an
``InMemoryRepository`` (and optionally a ``probes=`` map for a deterministic /test path).
OpenAPI/Swagger is served at ``/docs`` by default.

The secret_resolver (default ``EnvSecretResolver``) is used ONLY on the /test path to
dereference an ``auth_config.secret_ref`` at call time; the resolved value is never stored
or returned (§1.5). This app has NO onboarding/workflow dependency (§1.6 negative-trigger):
activating a connection only writes the connections table.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI
from rca_connector_sdk import EnvSecretResolver, SecretResolver

from rca_mar.repository import AssetRepository

from .connections_router import build_router
from .registry import Probe
from .resolution_router import build_resolution_router

# Single-tenant MVP default (matches the seed `tenant_id` and `make_mar_mcp`'s build param).
# The Resolution Queue endpoints scope to this tenant; per-request tenancy is out of scope.
DEFAULT_TENANT_ID = UUID("0190d3c9-0000-7000-8000-0000000000ff")


def create_app(
    repo: AssetRepository | None = None,
    *,
    secret_resolver: SecretResolver | None = None,
    probes: dict[str, Probe] | None = None,
    tenant_id: UUID = DEFAULT_TENANT_ID,
) -> FastAPI:
    if repo is None:
        repo = _postgres_repo()
    resolver = secret_resolver or EnvSecretResolver()

    app = FastAPI(title="RCA Connections API", version="0.0.1")
    app.include_router(
        build_router(repo=repo, secret_resolver=resolver, probes=probes))
    app.include_router(build_resolution_router(repo=repo, tenant_id=tenant_id))
    return app


def _postgres_repo() -> AssetRepository:
    """Build the Postgres-backed MAR repo from env config (production default).

    Imported lazily so tests that always inject a repo never need asyncpg/a live DB, and the
    connections router stays importable without a database.
    """
    from rca_mar.config import make_engine, make_session_factory
    from rca_mar.repository_pg import PostgresRepository

    engine = make_engine()
    session_factory = make_session_factory(engine)
    return PostgresRepository(session_factory)


__all__ = ["create_app", "DEFAULT_TENANT_ID"]
