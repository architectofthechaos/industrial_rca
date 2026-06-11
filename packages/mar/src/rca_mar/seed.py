"""Seed MAR from a product-owned YAML asset register (the authoritative-import path).

MAR registers LEAF assets only: units are knowledge-graph nodes from Sprint 2 on.
Each register entry carries a `unit:` slug consumed solely to mint the canonical id
`asset:{plant}:{unit}:{name}` — it is never persisted as a column.

`external_ids` values are plain external_id strings OR mappings with required
`external_id` + optional `vendor_path` (the Sprint 2a re-keyed pi_af form: AF WebId
as external_id, AF path as display/debug provenance).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict
from uuid import UUID

import yaml

from rca_contracts import AssetDescriptor
from rca_kg.slugs import slug as _slug

from .repository import AliasRow, AssetRepository, ConnectionRow

# Register criticality words -> canonical A/B/C/D (SPEC-011 design decision).
_CRITICALITY = {"high": "A", "medium": "C", "low": "D"}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_EXTERNAL_ID_KEYS = {"external_id", "vendor_path"}


class _ConnSpec(TypedDict):
    category: str
    connector_type: str
    status: str
    base_url: str
    extra_config: dict[str, str] | None


# Legacy register source key -> the default connection it seeds against (Sprint 2b §1.2).
# These mirror the synth rows the 0003 migration backfills for an existing 0002 DB:
# id `{plant}.{category}.{source.replace('_','-')}-default`, the same categories/base_urls/
# statuses. `sap_pm` is seeded `disabled` so it never clashes with `maximo` on the
# one-active-per-(plant, category) cmms slot. Keyed by source; the connection_id embeds
# the plant_id, so it is templated per register at seed time.
_DEFAULT_CONNECTION_SPECS: dict[str, _ConnSpec] = {
    "maximo": {"category": "cmms", "connector_type": "maximo", "status": "active",
               "base_url": "http://localhost:8002", "extra_config": None},
    "sap_pm": {"category": "cmms", "connector_type": "sap_pm", "status": "disabled",
               "base_url": "http://localhost:8003", "extra_config": None},
    "pi_af": {"category": "hierarchy", "connector_type": "pi_af", "status": "active",
              "base_url": "http://localhost:8001",
              "extra_config": {"database_name": "Refinery-GC"}},
    "uns": {"category": "historian", "connector_type": "uns", "status": "active",
            "base_url": "mqtt://localhost:1883", "extra_config": None},
}


def _connection_id(plant_id: str, source: str) -> str:
    spec = _DEFAULT_CONNECTION_SPECS[source]
    return f"{plant_id}.{spec['category']}.{source.replace('_', '-')}-default"


def _default_connection_row(plant_id: str, source: str) -> ConnectionRow:
    spec = _DEFAULT_CONNECTION_SPECS[source]
    return ConnectionRow(
        connection_id=_connection_id(plant_id, source), plant_id=plant_id,
        category=spec["category"], connector_type=spec["connector_type"],
        display_name=f"{source} (default)", base_url=spec["base_url"],
        auth_config={"type": "none", "secret_ref": None}, status=spec["status"],
        extra_config=spec["extra_config"])


def _split_external_id(source: str, tag: str, value: object) -> tuple[str, str | None]:
    """A register source value is either a plain external_id string or a mapping with
    required `external_id` + optional `vendor_path` (the re-keyed pi_af form). The
    register is authoritative input: anything else in the mapping is a bug — fail loudly."""
    if not isinstance(value, dict):
        return str(value), None
    unknown = sorted(set(value) - _EXTERNAL_ID_KEYS)
    if unknown:
        raise ValueError(
            f"unknown external_ids key(s) {unknown} under source {source!r} in register "
            f"entry {tag!r}; known: {sorted(_EXTERNAL_ID_KEYS)}")
    if "external_id" not in value:
        raise ValueError(
            f"missing required key 'external_id' under source {source!r} in register "
            f"entry {tag!r}")
    vendor_path = value.get("vendor_path")
    return str(value["external_id"]), None if vendor_path is None else str(vendor_path)


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

    # Upsert the default connection rows for every source the register references, BEFORE
    # any alias (each alias FKs its connection). Only seed connections actually used.
    used_sources = {
        source
        for a in doc.get("assets", [])
        for source in (a.get("external_ids") or {})}
    for source in used_sources:
        if source not in _DEFAULT_CONNECTION_SPECS:
            # The register is authoritative, human-curated input: an unknown source key is a
            # register bug — fail loudly rather than synthesize a connection for it.
            raise ValueError(
                f"unknown source system {source!r} in register {register_path.name}; "
                f"known: {sorted(_DEFAULT_CONNECTION_SPECS)}")
        await repo.upsert_connection(_default_connection_row(plant_id, source))

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
        for source, value in (a.get("external_ids") or {}).items():
            if source not in _DEFAULT_CONNECTION_SPECS:
                # The register is authoritative, human-curated input: an unknown source
                # key is a register bug — fail loudly rather than guess a connection.
                raise ValueError(
                    f"unknown source system {source!r} in register entry {a['tag']!r}; "
                    f"known: {sorted(_DEFAULT_CONNECTION_SPECS)}")
            external_id, vendor_path = _split_external_id(source, str(a["tag"]), value)
            await repo.upsert_alias(AliasRow(
                asset_id=aid, tenant_id=tenant, connection_id=_connection_id(plant_id, source),
                external_id=external_id, valid_from=_EPOCH, valid_to=None,
                mapping_source="authoritative_import", confidence=1.0, is_primary=True,
                resolution_status="auto_resolved", resolved_by="system",
                vendor_path=vendor_path))


__all__ = ["seed_from_register", "default_connection_row", "default_connection_id"]


# Public aliases so the Connections API / onboarding pipeline can reuse the synth defaults.
default_connection_row = _default_connection_row
default_connection_id = _connection_id
