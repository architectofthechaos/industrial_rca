"""canonical_id -> vendor tag lookup for the tag / operator_log connectors.

The AssetGateway port and its dev/test implementations were promoted to the SDK
(``rca_connector_sdk.assets``) once multiple entity connectors needed them (Sprint 2b
Track 3 Task 5). This module re-exports them so pi's existing imports keep working.

pi only uses ``tag_for`` (the historian tag); ``CanonicalSlugAssetGateway.source_handle``
raises NotFound, which is fine here.
"""
from __future__ import annotations

from rca_connector_sdk import (
    AssetGateway,
    CanonicalSlugAssetGateway,
    StaticAssetGateway,
)

__all__ = ["AssetGateway", "CanonicalSlugAssetGateway", "StaticAssetGateway"]
