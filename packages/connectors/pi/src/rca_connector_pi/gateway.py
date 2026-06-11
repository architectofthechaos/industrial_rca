"""canonical_id -> vendor tag lookup for the tag / operator_log connectors.

A canonical_id (`asset:{plant}:{unit}:{name}`) identifies an asset in the platform's
vocabulary; PI keys its points by a vendor tag string (e.g. "P-101A"). An AssetGateway
bridges the two. The production binding is MAR-backed (wired in onboarding); these
implementations cover dev/tests:

* ``CanonicalSlugAssetGateway`` derives the tag from the canonical_id's name segment
  (``name_slug.upper()`` -> "P-101A"). Good enough for the reference fleet and the live
  simulator, where the name slug matches the PI tag prefix exactly.
* ``StaticAssetGateway`` maps explicit canonical_id -> tag, for overrides/tests that need
  a tag the slug rule wouldn't produce.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from rca_connector_sdk import NotFound
from rca_contracts import parse_canonical_id


@runtime_checkable
class AssetGateway(Protocol):
    async def tag_for(self, canonical_id: str) -> str:
        """Resolve a canonical_id to the source's vendor tag (e.g. "P-101A")."""
        ...


class CanonicalSlugAssetGateway:
    """Derive the vendor tag from the canonical_id's name slug (``p-101a`` -> "P-101A").

    The reference fleet's PI tags share the asset's name slug uppercased, so this needs no
    external state. parse_canonical_id raises ValueError on a malformed id (caller maps it).
    """

    async def tag_for(self, canonical_id: str) -> str:
        return parse_canonical_id(canonical_id).name_slug.upper()


class StaticAssetGateway:
    """Dict-backed canonical_id -> tag; raises NotFound on a miss (for explicit overrides)."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = dict(mapping)

    async def tag_for(self, canonical_id: str) -> str:
        try:
            return self._mapping[canonical_id]
        except KeyError as exc:
            raise NotFound(f"no tag mapping for canonical_id {canonical_id!r}") from exc


__all__ = ["AssetGateway", "CanonicalSlugAssetGateway", "StaticAssetGateway"]
