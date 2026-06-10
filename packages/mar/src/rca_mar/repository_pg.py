"""PostgresRepository — SQLAlchemy 2.0 async implementation of AssetRepository."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from rca_contracts import AssetDescriptor

from .models import Asset, AssetAlias, AssetAliasUnresolved
from .repository import AliasRow


def _to_descriptor(a: Asset) -> AssetDescriptor:
    return AssetDescriptor(
        asset_id=a.asset_id, canonical_id=a.canonical_id, tenant_id=a.tenant_id,
        plant_id=a.plant_id,
        iso14224_class=a.iso14224_class, iso14224_level=a.iso14224_level, tag=a.tag,
        service=a.service, criticality=a.criticality,  # type: ignore[arg-type]  # str col -> A/B/C/D Literal
        manufacturer=a.manufacturer,
        model=a.model, serial_number=a.serial_number, commissioned_at=a.commissioned_at,
        decommissioned_at=a.decommissioned_at, location_description=a.location_description,
        description=a.description)


def _to_aliasrow(a: AssetAlias) -> AliasRow:
    return AliasRow(asset_id=a.asset_id, tenant_id=a.tenant_id, source_system=a.source_system,
                    external_id=a.external_id, valid_from=a.valid_from, valid_to=a.valid_to,
                    mapping_source=a.mapping_source, confidence=a.confidence,
                    is_primary=a.is_primary, source_system_type=a.source_system_type,
                    resolution_status=a.resolution_status,
                    candidate_alternatives=a.candidate_alternatives, resolved_by=a.resolved_by,
                    vendor_path=a.vendor_path, vendor_metadata=a.vendor_metadata,
                    confirmed_by=a.confirmed_by, notes=a.notes)


class PostgresRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def upsert_asset(self, asset: AssetDescriptor) -> None:
        async with self._sf() as s, s.begin():
            values = asset.model_dump()
            stmt = pg_insert(Asset).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Asset.asset_id],
                set_={**{k: values[k] for k in values if k != "asset_id"},
                      "updated_at": func.now()})
            await s.execute(stmt)

    async def upsert_alias(self, alias: AliasRow) -> None:
        async with self._sf() as s, s.begin():
            # close any existing active alias for the same (tenant, source, external_id)
            await s.execute(
                update(AssetAlias)
                .where(and_(AssetAlias.tenant_id == alias.tenant_id,
                            AssetAlias.source_system == alias.source_system,
                            AssetAlias.external_id == alias.external_id,
                            AssetAlias.valid_to.is_(None)))
                .values(valid_to=alias.valid_from))
            await s.execute(pg_insert(AssetAlias).values(
                alias_id=uuid4(), asset_id=alias.asset_id, tenant_id=alias.tenant_id,
                source_system=alias.source_system, source_system_type=alias.source_system_type,
                external_id=alias.external_id,
                valid_from=alias.valid_from, valid_to=alias.valid_to,
                mapping_source=alias.mapping_source, confidence=alias.confidence,
                resolution_status=alias.resolution_status,
                candidate_alternatives=alias.candidate_alternatives,
                resolved_by=alias.resolved_by, vendor_path=alias.vendor_path,
                vendor_metadata=alias.vendor_metadata,
                is_primary=alias.is_primary,
                confirmed_by=alias.confirmed_by, notes=alias.notes))

    async def find_active_alias(self, tenant, source, external_id, *, valid_at):
        async with self._sf() as s:
            q = select(AssetAlias).where(and_(
                AssetAlias.tenant_id == tenant, AssetAlias.source_system == source,
                AssetAlias.external_id == external_id))
            if valid_at is None:
                q = q.where(AssetAlias.valid_to.is_(None))
            else:
                q = q.where(and_(AssetAlias.valid_from <= valid_at,
                                 or_(AssetAlias.valid_to.is_(None), AssetAlias.valid_to > valid_at)))
            row = (await s.execute(q.limit(1))).scalar_one_or_none()
            return _to_aliasrow(row) if row else None

    async def find_crosswalk_candidates(self, tenant, external_id):
        async with self._sf() as s:
            q = select(AssetAlias).where(and_(
                AssetAlias.tenant_id == tenant, AssetAlias.external_id == external_id,
                AssetAlias.valid_to.is_(None)))
            return [_to_aliasrow(r) for r in (await s.execute(q)).scalars()]

    async def find_asset_by_tag(self, tenant, tag):
        async with self._sf() as s:
            q = select(Asset).where(and_(Asset.tenant_id == tenant, Asset.tag == tag)).limit(1)
            row = (await s.execute(q)).scalar_one_or_none()
            return _to_descriptor(row) if row else None

    async def find_asset_by_canonical_id(self, tenant, canonical_id):
        async with self._sf() as s:
            q = select(Asset).where(and_(
                Asset.tenant_id == tenant, Asset.canonical_id == canonical_id)).limit(1)
            row = (await s.execute(q)).scalar_one_or_none()
            return _to_descriptor(row) if row else None

    async def get_asset(self, tenant, asset_id):
        async with self._sf() as s:
            q = select(Asset).where(and_(Asset.tenant_id == tenant, Asset.asset_id == asset_id))
            row = (await s.execute(q)).scalar_one_or_none()
            return _to_descriptor(row) if row else None

    async def search_assets(self, tenant, *, iso14224_class=None, tag_pattern=None,
                            canonical_id_pattern=None, criticality=None, service=None, limit=50):
        async with self._sf() as s:
            q = select(Asset).where(Asset.tenant_id == tenant)
            if iso14224_class:
                q = q.where(Asset.iso14224_class == iso14224_class)
            if tag_pattern:
                q = q.where(Asset.tag.like(tag_pattern))
            if canonical_id_pattern:
                q = q.where(Asset.canonical_id.like(canonical_id_pattern))
            if criticality:
                q = q.where(Asset.criticality.in_(criticality))
            if service:
                q = q.where(Asset.service == service)
            rows = (await s.execute(q.limit(limit))).scalars()
            return [_to_descriptor(r) for r in rows]

    async def source_handle_for(self, tenant, asset_id, source):
        async with self._sf() as s:
            q = select(AssetAlias.external_id).where(and_(
                AssetAlias.tenant_id == tenant, AssetAlias.asset_id == asset_id,
                AssetAlias.source_system == source, AssetAlias.valid_to.is_(None))).limit(1)
            return (await s.execute(q)).scalar_one_or_none()

    async def upsert_unresolved(self, tenant, source, external_id, payload):
        async with self._sf() as s, s.begin():
            stmt = pg_insert(AssetAliasUnresolved).values(
                tenant_id=tenant, source_system=source, external_id=external_id,
                occurrence_count=1, candidate_payload=payload)
            stmt = stmt.on_conflict_do_update(
                index_elements=[AssetAliasUnresolved.tenant_id, AssetAliasUnresolved.source_system,
                                AssetAliasUnresolved.external_id],
                set_={"occurrence_count": AssetAliasUnresolved.occurrence_count + 1})
            await s.execute(stmt)


__all__ = ["PostgresRepository"]
