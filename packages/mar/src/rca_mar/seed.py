"""Seed MAR from a product-owned YAML asset register (the authoritative-import path).

MAR registers LEAF assets only: units are knowledge-graph nodes from Sprint 2 on.
Each register entry carries a `unit:` slug consumed solely to mint the canonical id
`asset:{plant}:{unit}:{name}` — it is never persisted as a column.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import yaml

from rca_contracts import AssetDescriptor
from rca_kg.slugs import slug as _slug

from .models import SOURCE_SYSTEM_CATEGORIES
from .repository import AliasRow, AssetRepository

# Register criticality words -> canonical A/B/C/D (SPEC-011 design decision).
_CRITICALITY = {"high": "A", "medium": "C", "low": "D"}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _descriptor(tenant: UUID, *, asset_id, canonical_id, plant_id, tag, iso_class, iso_level,
                service=None, criticality="C", manufacturer=None, model=None,
                serial_number=None) -> AssetDescriptor:
    return AssetDescriptor(
        asset_id=asset_id, canonical_id=canonical_id, tenant_id=tenant, plant_id=plant_id,
        iso14224_class=iso_class, iso14224_level=iso_level, tag=tag, service=service,
        criticality=criticality, manufacturer=manufacturer, model=model,
        serial_number=serial_number, commissioned_at=None, decommissioned_at=None,
        location_description=None, description=None)


async def seed_from_register(repo: AssetRepository, register_path: Path) -> None:
    doc = yaml.safe_load(register_path.read_text())
    tenant = UUID(str(doc["tenant_id"]))
    plant_id = str(doc["plant_id"])

    for a in doc.get("assets", []):
        aid = UUID(str(a["asset_id"]))
        canonical_id = f"asset:{plant_id}:{_slug(str(a['unit']))}:{_slug(str(a['tag']))}"
        crit_word = a["criticality"]
        if crit_word not in _CRITICALITY:
            raise ValueError(
                f"unknown criticality {crit_word!r} in register entry {a['tag']!r}; "
                f"known: {sorted(_CRITICALITY)}")
        await repo.upsert_asset(_descriptor(
            tenant, asset_id=aid, canonical_id=canonical_id, plant_id=plant_id,
            tag=a["tag"], iso_class=a["iso14224_class"], iso_level=int(a["iso14224_level"]),
            service=a.get("service"), criticality=_CRITICALITY[crit_word],
            manufacturer=a.get("manufacturer"), model=a.get("model"),
            serial_number=a.get("serial_number")))
        for source, external_id in (a.get("external_ids") or {}).items():
            if source not in SOURCE_SYSTEM_CATEGORIES:
                # The register is authoritative, human-curated input: an unknown source
                # key is a register bug — fail loudly rather than guess a category.
                raise ValueError(
                    f"unknown source system {source!r} in register entry {a['tag']!r}; "
                    f"known: {sorted(SOURCE_SYSTEM_CATEGORIES)}")
            await repo.upsert_alias(AliasRow(
                asset_id=aid, tenant_id=tenant, source_system=source,
                external_id=str(external_id), valid_from=_EPOCH, valid_to=None,
                mapping_source="authoritative_import", confidence=1.0, is_primary=True,
                source_system_type=SOURCE_SYSTEM_CATEGORIES[source],
                resolution_status="auto_resolved", resolved_by="system"))


__all__ = ["seed_from_register"]
