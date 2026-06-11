"""Resolution Queue REST endpoints (Sprint 2b §4.2).

These endpoints expose the MAR resolution-queue write paths over the same FastAPI app as the
Connections API (they share the review surface). UX is out of scope — this is the machinery:
list pending-review bindings, validate (optionally re-pointing to a candidate alternative),
reject, and aggregate stats.

The MVP is single-tenant: ``tenant_id`` is fixed at build time (matching ``make_mar_mcp``),
not derived per-request. ``InvalidTransition`` from the repo maps to 409; an unknown
``alias_id`` maps to 404.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from rca_mar.repository import AliasRow, AssetRepository, InvalidTransition

from .schemas import (
    PendingBindingResponse,
    RejectBindingRequest,
    ResolutionStatRow,
    ValidateBindingRequest,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_resolution_router(*, repo: AssetRepository, tenant_id: UUID) -> APIRouter:
    router = APIRouter(prefix="/resolution_queue", tags=["resolution_queue"])

    async def _require_alias(alias_id: UUID) -> AliasRow:
        row = await repo.get_alias(alias_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no binding {alias_id}")
        return row

    async def _canonical_id_of(asset_id: UUID) -> str | None:
        asset = await repo.get_asset(tenant_id, asset_id)
        return asset.canonical_id if asset else None

    # -- list pending --------------------------------------------------------
    @router.get("", response_model=list[PendingBindingResponse])
    async def list_pending(
        plant_id: str | None = Query(default=None),
        connection_id: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[PendingBindingResponse]:
        rows = await repo.list_pending_bindings(
            tenant_id, plant_id=plant_id, connection_id=connection_id, limit=limit)
        out: list[PendingBindingResponse] = []
        for r in rows:
            out.append(PendingBindingResponse.from_alias(
                r, canonical_id=await _canonical_id_of(r.asset_id)))
        return out

    # -- stats ---------------------------------------------------------------
    # NOTE: declared before /{alias_id}/* so "stats" is never captured as an alias_id path param.
    @router.get("/stats", response_model=list[ResolutionStatRow])
    async def stats() -> list[ResolutionStatRow]:
        return [ResolutionStatRow(**row) for row in await repo.resolution_stats(tenant_id)]

    # -- validate ------------------------------------------------------------
    @router.post("/{alias_id}/validate", response_model=PendingBindingResponse)
    async def validate(alias_id: UUID, body: ValidateBindingRequest) -> PendingBindingResponse:
        row = await _require_alias(alias_id)
        current_canonical = await _canonical_id_of(row.asset_id)

        # Accept the current binding when no alternative is named (or it matches the bound asset).
        if body.accepted_canonical_id is None or body.accepted_canonical_id == current_canonical:
            try:
                validated = await repo.validate_binding(alias_id, body.validated_by)
            except InvalidTransition as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return PendingBindingResponse.from_alias(
                validated, canonical_id=await _canonical_id_of(validated.asset_id))

        # A DIFFERENT canonical was accepted: it must be one of the candidate alternatives AND a
        # real asset. Supersede the current binding and mint a new manual human_validated one.
        candidate_ids = {c.get("canonical_id")
                         for c in (row.candidate_alternatives or [])}
        if body.accepted_canonical_id not in candidate_ids:
            raise HTTPException(
                status_code=422,
                detail=f"{body.accepted_canonical_id!r} is not a candidate alternative")
        target = await repo.find_asset_by_canonical_id(tenant_id, body.accepted_canonical_id)
        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"no asset with canonical_id {body.accepted_canonical_id!r}")

        try:
            await repo.supersede_binding(alias_id, system_initiated=False)
        except InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        now = _utcnow()
        new_alias = AliasRow(
            asset_id=target.asset_id, tenant_id=tenant_id, connection_id=row.connection_id,
            external_id=row.external_id, valid_from=now, valid_to=None,
            mapping_source="manual", confidence=1.0, is_primary=row.is_primary,
            resolution_status="human_validated", resolved_by="system",
            vendor_path=row.vendor_path, vendor_metadata=row.vendor_metadata,
            validated_by=body.validated_by, validated_at=now,
            notes=f"manually re-pointed from alias {alias_id}")
        await repo.upsert_alias(new_alias)
        created = await repo.find_active_alias(
            tenant_id, row.connection_id, row.external_id, valid_at=None)
        # `created` is the freshly-minted row; fall back to new_alias defensively.
        result = created or new_alias
        return PendingBindingResponse.from_alias(result, canonical_id=target.canonical_id)

    # -- reject --------------------------------------------------------------
    @router.post("/{alias_id}/reject", response_model=PendingBindingResponse)
    async def reject(alias_id: UUID, body: RejectBindingRequest) -> PendingBindingResponse:
        await _require_alias(alias_id)
        try:
            rejected = await repo.reject_binding(alias_id, body.rejected_by, body.reason)
        except InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return PendingBindingResponse.from_alias(
            rejected, canonical_id=await _canonical_id_of(rejected.asset_id))

    return router


__all__ = ["build_resolution_router"]
