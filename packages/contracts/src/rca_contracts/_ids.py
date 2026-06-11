"""Canonical identifier types — AssetID / TenantID (owned by MAR)."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import Field

AssetID = Annotated[UUID, Field(description="Canonical asset UUID from MAR")]
TenantID = Annotated[UUID, Field(description="Tenant scope UUID")]
