"""canonical_id -> vendor handle lookup, shared by every entity connector.

A canonical_id (`asset:{plant}:{unit}:{name}`) identifies an asset in the platform's
vocabulary; each source keys its records by its own vendor string — the historian by a
tag (e.g. "P-101A"), the CMMS by a location/equipment handle (e.g. "CRDU-P101A"). An
``AssetGateway`` bridges canonical_id -> source handle. The production binding is
MAR-backed (wired during onboarding); these implementations cover dev/tests:

* ``CanonicalSlugAssetGateway`` derives the historian tag from the canonical_id's name
  segment (``name_slug.upper()`` -> "P-101A"). It has NO rule for vendor source handles
  (a CMMS location is not derivable from the slug), so ``source_handle`` raises NotFound.
* ``StaticAssetGateway`` maps explicit canonical_id -> tag and (canonical_id, category) ->
  handle, for overrides/tests that need a value the slug rule wouldn't produce.
* ``MarAssetGateway`` resolves (canonical_id, category) -> source handle via the MAR
  asset register (D13/G28): canonical_id -> asset_id -> active connection -> source handle.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from rca_contracts import parse_canonical_id

from .errors import NotFound


@runtime_checkable
class AssetGateway(Protocol):
    async def tag_for(self, canonical_id: str) -> str:
        """Resolve a canonical_id to the historian's vendor tag (e.g. "P-101A")."""
        ...

    async def source_handle(self, canonical_id: str, category: str) -> str:
        """Resolve a canonical_id to a source category's vendor handle.

        e.g. the CMMS location ``"CRDU-P101A"`` for category ``"cmms"``.
        """
        ...


class CanonicalSlugAssetGateway:
    """Derive the historian tag from the canonical_id's name slug (``p-101a`` -> "P-101A").

    The reference fleet's PI tags share the asset's name slug uppercased, so ``tag_for``
    needs no external state. There is no slug rule for vendor source handles (a CMMS
    location is arbitrary), so ``source_handle`` raises NotFound — inject a real gateway
    (or the MAR-backed binding) when a handle is required. parse_canonical_id raises
    ValueError on a malformed id (caller maps it).
    """

    async def tag_for(self, canonical_id: str) -> str:
        return parse_canonical_id(canonical_id).name_slug.upper()

    async def source_handle(self, canonical_id: str, category: str) -> str:
        raise NotFound(
            f"no slug rule for source handle of canonical_id {canonical_id!r} "
            f"(category {category!r}); inject a gateway with the binding"
        )


class StaticAssetGateway:
    """Dict-backed gateway; raises NotFound on a miss (for explicit overrides/tests).

    ``tags`` maps canonical_id -> historian tag. ``handles`` maps
    (canonical_id, category) -> vendor source handle.
    """

    def __init__(
        self,
        tags: dict[str, str] | None = None,
        handles: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self._tags = dict(tags or {})
        self._handles = dict(handles or {})

    async def tag_for(self, canonical_id: str) -> str:
        try:
            return self._tags[canonical_id]
        except KeyError as exc:
            raise NotFound(f"no tag mapping for canonical_id {canonical_id!r}") from exc

    async def source_handle(self, canonical_id: str, category: str) -> str:
        try:
            return self._handles[(canonical_id, category)]
        except KeyError as exc:
            raise NotFound(
                f"no source handle for canonical_id {canonical_id!r} "
                f"in category {category!r}"
            ) from exc


class MarAssetGateway(CanonicalSlugAssetGateway):
    """AssetGateway backed by MAR's asset register (D13/G28). Resolves (canonical_id, category)
    -> source handle (e.g. the Maximo location) via: canonical_id -> asset_id ->
    active (plant, category) connection -> source_handle_for. Unresolved -> NotFound (typed skip,
    never a silent empty)."""

    def __init__(self, *, repo: Any, tenant_id: Any) -> None:
        self._repo = repo
        self._tenant = tenant_id

    async def source_handle(self, canonical_id: str, category: str) -> str:
        asset = await self._repo.find_asset_by_canonical_id(self._tenant, canonical_id)
        if asset is None:
            raise NotFound(
                f"no MAR asset for canonical_id {canonical_id!r} (category {category!r})")
        plant_id = parse_canonical_id(canonical_id).plant_id
        conn = await self._active_connection(plant_id, category)
        if conn is None:
            raise NotFound(
                f"no active {category!r} connection for plant {plant_id!r} "
                f"(canonical_id {canonical_id!r})")
        handle = await self._repo.source_handle_for(
            self._tenant, asset.asset_id, conn.connection_id)
        if handle is None:
            raise NotFound(
                f"no {category!r} source handle (alias) for {canonical_id!r} "
                f"on connection {conn.connection_id!r}")
        return handle

    async def _active_connection(self, plant_id: str, category: str) -> Any:
        conns = await self._repo.list_connections(
            plant_id=plant_id, category=category, status="active")
        return conns[0] if conns else None


__all__ = ["AssetGateway", "CanonicalSlugAssetGateway", "MarAssetGateway", "StaticAssetGateway"]
