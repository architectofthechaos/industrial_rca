"""Pydantic request/response models for the Connections API (Sprint 2b §1.3, §1.5).

These are the HTTP wire models — deliberately distinct from `rca_mar.models.Connection`
(the ORM) and `rca_mar.repository.ConnectionRow` (the repo dataclass). The crucial invariant
(§1.5): `auth_config` round-trips only `{type, secret_ref}` — the secret_ref is a *pointer*
(e.g. ``env:PI_PASSWORD``), never the resolved value, which is dereferenced at /test time and
never serialized into any response body.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rca_mar.repository import AliasRow, ConnectionRow

# The category vocabulary (Sprint 2b): hierarchy / historian / cmms / document / operator_log.
Category = Literal["hierarchy", "historian", "cmms", "document", "operator_log"]
Status = Literal["pending", "active", "error", "disabled"]
AuthType = Literal["basic", "bearer", "none"]


class AuthConfig(BaseModel):
    """How a connection authenticates. ``secret_ref`` is a pointer like ``env:PI_PASSWORD`` —
    the resolved secret is NEVER stored here or returned in any response (§1.5)."""

    model_config = ConfigDict(extra="forbid")

    type: AuthType
    secret_ref: str | None = None


class CreateConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plant_id: str
    category: Category
    connector_type: str
    display_name: str
    base_url: str
    auth_config: AuthConfig
    extra_config: dict | None = None


class UpdateConnectionRequest(BaseModel):
    """Partial update. All fields optional; unknown fields are rejected (extra=forbid -> 422).
    A ``status`` change is validated through the state machine (PATCH-allowed transitions only).
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    base_url: str | None = None
    auth_config: AuthConfig | None = None
    extra_config: dict | None = None
    status: Status | None = None


class ConnectionResponse(BaseModel):
    """Mirrors the connection row, but ``auth_config`` exposes only ``{type, secret_ref}`` —
    never a resolved secret (§1.5)."""

    connection_id: str
    plant_id: str
    category: str
    connector_type: str
    display_name: str
    base_url: str
    auth_config: AuthConfig
    extra_config: dict | None = None
    status: str
    last_tested_at: datetime | None = None
    last_test_result: dict | None = None

    @classmethod
    def from_row(cls, row: ConnectionRow) -> ConnectionResponse:
        # Project the stored auth_config dict down to the write-only contract: type + secret_ref
        # ONLY. Any other key a row might carry (it shouldn't) is dropped here so a resolved
        # secret can never leak into a response body.
        raw = row.auth_config or {}
        auth = AuthConfig(type=raw.get("type", "none"), secret_ref=raw.get("secret_ref"))
        return cls(
            connection_id=row.connection_id,
            plant_id=row.plant_id,
            category=row.category,
            connector_type=row.connector_type,
            display_name=row.display_name,
            base_url=row.base_url,
            auth_config=auth,
            extra_config=row.extra_config,
            status=row.status,
            last_tested_at=row.last_tested_at,
            last_test_result=row.last_test_result,
        )


class CategoryConflict(BaseModel):
    """Structured 409 body when activating a second connection for a (plant, category) (§1.4)."""

    error: Literal["category_conflict"] = "category_conflict"
    conflicting_connection_id: str


# -- Resolution Queue (Sprint 2b §4.2) -------------------------------------------------------

class PendingBindingResponse(BaseModel):
    """A pending-review asset binding awaiting human judgment (Sprint 2b §4.2).

    Surfaces ``candidate_alternatives`` (every candidate the resolver considered) so a reviewer
    can accept the current binding or pick an alternative. ``canonical_id`` is the canonical id
    of the currently-bound asset when it can be resolved cheaply, else null.
    """

    alias_id: UUID
    asset_id: UUID
    canonical_id: str | None = None
    connection_id: str
    external_id: str
    resolution_status: str
    confidence: float
    mapping_source: str
    candidate_alternatives: list[dict[str, Any]] | None = None
    valid_from: datetime
    valid_to: datetime | None = None
    validated_by: str | None = None
    validated_at: datetime | None = None

    @classmethod
    def from_alias(cls, row: AliasRow, *, canonical_id: str | None = None
                   ) -> PendingBindingResponse:
        return cls(
            alias_id=row.alias_id,  # type: ignore[arg-type]  # always set on rows read from store
            asset_id=row.asset_id,
            canonical_id=canonical_id,
            connection_id=row.connection_id,
            external_id=row.external_id,
            resolution_status=row.resolution_status,
            confidence=row.confidence,
            mapping_source=row.mapping_source,
            candidate_alternatives=row.candidate_alternatives,
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            validated_by=row.validated_by,
            validated_at=row.validated_at,
        )


class ValidateBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validated_by: str
    # When set and DIFFERENT from the bound asset's canonical_id, the current binding is
    # superseded and a new manual human_validated binding is created to the chosen alternative.
    accepted_canonical_id: str | None = None


class RejectBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejected_by: str
    reason: str


class ResolutionStatRow(BaseModel):
    """One aggregate count of bindings by (connection_id, resolution_status) (§4.2)."""

    connection_id: str
    resolution_status: str
    count: int


__all__ = [
    "Category", "Status", "AuthType", "AuthConfig",
    "CreateConnectionRequest", "UpdateConnectionRequest", "ConnectionResponse",
    "CategoryConflict",
    "PendingBindingResponse", "ValidateBindingRequest", "RejectBindingRequest",
    "ResolutionStatRow",
]
