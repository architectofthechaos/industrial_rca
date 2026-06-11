"""Connections REST endpoints (Sprint 2b §1.3).

The router is built by ``build_router`` with its collaborators injected (repo, secret
resolver, probe registry) so the same code path serves both the Postgres-backed app and the
hermetic InMemoryRepository tests. State changes go through ``state_machine`` and the
one-active-per-category invariant is enforced both proactively (here, on /activate) and as a
backstop (catching the repo's ``DuplicateActiveConnection``).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Response
from rca_connector_sdk import SecretResolver
from rca_kg.slugs import slug

from rca_mar.repository import (
    AssetRepository,
    ConnectionRow,
    DuplicateActiveConnection,
)

from .registry import Probe, probe_for
from .schemas import (
    Category,
    ConnectionResponse,
    CreateConnectionRequest,
    Status,
    UpdateConnectionRequest,
)
from .state_machine import InvalidTransition, assert_patch_transition

ProbeLookup = "dict[str, Probe] | None"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_router(
    *,
    repo: AssetRepository,
    secret_resolver: SecretResolver,
    probes: dict[str, Probe] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/connections", tags=["connections"])

    def _probe_for(connector_type: str) -> Probe:
        # Test override: a `probes=` map injected via create_app wins (deterministic tests);
        # otherwise the real connector registry is used.
        if probes is not None and connector_type in probes:
            return probes[connector_type]
        return probe_for(connector_type)

    async def _require(connection_id: str) -> ConnectionRow:
        row = await repo.get_connection(connection_id)
        if row is None:
            raise HTTPException(status_code=404,
                                detail=f"no connection {connection_id!r}")
        return row

    # -- create --------------------------------------------------------------
    @router.post("", response_model=ConnectionResponse, status_code=201)
    async def create_connection(body: CreateConnectionRequest) -> ConnectionResponse:
        connection_id = f"{body.plant_id}.{body.category}.{slug(body.display_name)}"
        if await repo.get_connection(connection_id) is not None:
            raise HTTPException(
                status_code=409,
                detail=f"connection {connection_id!r} already exists")
        row = ConnectionRow(
            connection_id=connection_id,
            plant_id=body.plant_id,
            category=body.category,
            connector_type=body.connector_type,
            display_name=body.display_name,
            base_url=body.base_url,
            auth_config=body.auth_config.model_dump(),
            status="pending",
            extra_config=body.extra_config,
        )
        await repo.upsert_connection(row)
        return ConnectionResponse.from_row(row)

    # -- list ----------------------------------------------------------------
    @router.get("", response_model=list[ConnectionResponse])
    async def list_connections(
        plant_id: str | None = Query(default=None),
        category: Category | None = Query(default=None),
        status: Status | None = Query(default=None),
    ) -> list[ConnectionResponse]:
        rows = await repo.list_connections(
            plant_id=plant_id, category=category, status=status)
        return [ConnectionResponse.from_row(r) for r in rows]

    # -- get single ----------------------------------------------------------
    @router.get("/{connection_id}", response_model=ConnectionResponse)
    async def get_connection(connection_id: str) -> ConnectionResponse:
        return ConnectionResponse.from_row(await _require(connection_id))

    # -- patch ---------------------------------------------------------------
    @router.patch("/{connection_id}", response_model=ConnectionResponse)
    async def update_connection(
        connection_id: str, body: UpdateConnectionRequest
    ) -> ConnectionResponse:
        row = await _require(connection_id)
        changes: dict = {}
        if body.display_name is not None:
            changes["display_name"] = body.display_name
        if body.base_url is not None:
            changes["base_url"] = body.base_url
        if body.auth_config is not None:
            changes["auth_config"] = body.auth_config.model_dump()
        if body.extra_config is not None:
            changes["extra_config"] = body.extra_config
        if body.status is not None and body.status != row.status:
            # PATCH may only make operator-driven lifecycle moves (active->disabled,
            # disabled->pending). Test/activate-driven moves are rejected here.
            try:
                assert_patch_transition(row.status, body.status)
            except InvalidTransition as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            changes["status"] = body.status

        updated = replace(row, **changes)
        try:
            await repo.upsert_connection(updated)
        except DuplicateActiveConnection as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "category_conflict",
                        "conflicting_connection_id": exc.existing_connection_id}) from exc
        return ConnectionResponse.from_row(updated)

    # -- delete --------------------------------------------------------------
    @router.delete("/{connection_id}")
    async def delete_connection(connection_id: str) -> Response:
        """Soft-delete (status -> disabled). If NO asset_aliases reference the connection,
        the row is then hard-deleted (204). If aliases reference it, the row survives as
        disabled and the updated ConnectionResponse is returned (200)."""
        row = await _require(connection_id)
        # Soft delete: park it disabled. (active->disabled is legal; from pending/error we
        # still drive it to disabled — DELETE is the terminal operator action.)
        disabled = replace(row, status="disabled")
        await repo.upsert_connection(disabled)
        refs = await repo.count_aliases_for_connection(connection_id)
        if refs == 0:
            await repo.delete_connection(connection_id)
            return Response(status_code=204)
        return Response(
            content=ConnectionResponse.from_row(disabled).model_dump_json(),
            media_type="application/json", status_code=200)

    # -- test ----------------------------------------------------------------
    @router.post("/{connection_id}/test", response_model=None)
    async def test_connection(connection_id: str):
        row = await _require(connection_id)
        # Resolve a secret_ref if present — used by the probe, NEVER returned/stored (§1.5).
        auth = row.auth_config or {}
        secret_ref = auth.get("secret_ref")
        if secret_ref:
            try:
                secret_resolver.resolve(secret_ref)
            except Exception:  # noqa: BLE001 — a bad secret_ref shouldn't 500 the test path
                pass
        probe = _probe_for(row.connector_type)
        result = await probe(row.base_url, 5.0, row.extra_config)

        # Persist the probe outcome and transition status per §1.4:
        #   success: error -> pending (now re-testable/activatable); pending/active unchanged.
        #   failure: pending/active -> error.  A test NEVER auto-activates (that's /activate).
        new_status = row.status
        if result.success:
            if row.status == "error":
                new_status = "pending"
        else:
            if row.status in ("pending", "active"):
                new_status = "error"
        tested = replace(
            row, status=new_status,
            last_tested_at=_utcnow(), last_test_result=result.model_dump())
        await repo.upsert_connection(tested)
        return result

    # -- activate ------------------------------------------------------------
    @router.post("/{connection_id}/activate", response_model=ConnectionResponse)
    async def activate_connection(connection_id: str) -> ConnectionResponse:
        row = await _require(connection_id)
        # Must be activatable from `pending` and only after a successful test (§1.4).
        if row.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"connection {connection_id!r} is {row.status!r}, "
                       f"only a pending connection can be activated")
        if not (row.last_test_result or {}).get("success"):
            raise HTTPException(
                status_code=409,
                detail="a successful test is required before activation; "
                       "POST /connections/{id}/test first")
        # One-active-per-category: refuse if another connection for (plant, category) is active.
        for other in await repo.list_connections(
                plant_id=row.plant_id, category=row.category, status="active"):
            if other.connection_id != connection_id:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "category_conflict",
                            "conflicting_connection_id": other.connection_id})
        activated = replace(row, status="active")
        try:
            await repo.upsert_connection(activated)
        except DuplicateActiveConnection as exc:
            # Backstop: the repo's partial-unique invariant won the race — map to the same 409.
            raise HTTPException(
                status_code=409,
                detail={"error": "category_conflict",
                        "conflicting_connection_id": exc.existing_connection_id}) from exc
        return ConnectionResponse.from_row(activated)

    return router


__all__ = ["build_router"]
