"""PostgresRepository — SQLAlchemy 2.0 async implementation of AssetRepository."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from rca_contracts import AssetDescriptor

from .models import Asset, AssetAlias, AssetAliasUnresolved, Connection
from .repository import AliasRow, ConnectionRow, DuplicateActiveConnection


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
    return AliasRow(asset_id=a.asset_id, tenant_id=a.tenant_id, connection_id=a.connection_id,
                    external_id=a.external_id, valid_from=a.valid_from, valid_to=a.valid_to,
                    mapping_source=a.mapping_source, confidence=a.confidence,
                    is_primary=a.is_primary,
                    resolution_status=a.resolution_status,
                    candidate_alternatives=a.candidate_alternatives, resolved_by=a.resolved_by,
                    vendor_path=a.vendor_path, vendor_metadata=a.vendor_metadata,
                    confirmed_by=a.confirmed_by, notes=a.notes)


def _to_connectionrow(c: Connection) -> ConnectionRow:
    return ConnectionRow(
        connection_id=c.connection_id, plant_id=c.plant_id, category=c.category,
        connector_type=c.connector_type, display_name=c.display_name, base_url=c.base_url,
        auth_config=c.auth_config, status=c.status, extra_config=c.extra_config,
        last_tested_at=c.last_tested_at, last_test_result=c.last_test_result)


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
            # close any existing active alias for the same (tenant, connection_id, external_id)
            await s.execute(
                update(AssetAlias)
                .where(and_(AssetAlias.tenant_id == alias.tenant_id,
                            AssetAlias.connection_id == alias.connection_id,
                            AssetAlias.external_id == alias.external_id,
                            AssetAlias.valid_to.is_(None)))
                .values(valid_to=alias.valid_from))
            await s.execute(pg_insert(AssetAlias).values(
                alias_id=uuid4(), asset_id=alias.asset_id, tenant_id=alias.tenant_id,
                connection_id=alias.connection_id,
                external_id=alias.external_id,
                valid_from=alias.valid_from, valid_to=alias.valid_to,
                mapping_source=alias.mapping_source, confidence=alias.confidence,
                resolution_status=alias.resolution_status,
                candidate_alternatives=alias.candidate_alternatives,
                resolved_by=alias.resolved_by, vendor_path=alias.vendor_path,
                vendor_metadata=alias.vendor_metadata,
                is_primary=alias.is_primary,
                confirmed_by=alias.confirmed_by, notes=alias.notes))

    async def find_active_alias(self, tenant, connection_id, external_id, *, valid_at):
        async with self._sf() as s:
            q = select(AssetAlias).where(and_(
                AssetAlias.tenant_id == tenant, AssetAlias.connection_id == connection_id,
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

    async def source_handle_for(self, tenant, asset_id, connection_id):
        async with self._sf() as s:
            q = select(AssetAlias.external_id).where(and_(
                AssetAlias.tenant_id == tenant, AssetAlias.asset_id == asset_id,
                AssetAlias.connection_id == connection_id,
                AssetAlias.valid_to.is_(None))).limit(1)
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

    async def upsert_connection(self, conn: ConnectionRow) -> None:
        values = {
            "connection_id": conn.connection_id, "plant_id": conn.plant_id,
            "category": conn.category, "connector_type": conn.connector_type,
            "display_name": conn.display_name, "base_url": conn.base_url,
            "auth_config": conn.auth_config, "extra_config": conn.extra_config,
            "status": conn.status, "last_tested_at": conn.last_tested_at,
            "last_test_result": conn.last_test_result,
        }
        stmt = pg_insert(Connection).values(**values).on_conflict_do_update(
            index_elements=[Connection.connection_id],
            set_={**{k: v for k, v in values.items() if k != "connection_id"},
                  "updated_at": func.now()})
        try:
            async with self._sf() as s, s.begin():
                await s.execute(stmt)
        except IntegrityError as exc:
            # The partial unique index uq_connection_active_category fired: a second active
            # connection for the same (plant_id, category). Surface as a typed error the API
            # layer maps to 409 — look up the conflicting active row for its id.
            existing = await self.list_connections(
                plant_id=conn.plant_id, category=conn.category, status="active")
            other = next((c for c in existing if c.connection_id != conn.connection_id), None)
            raise DuplicateActiveConnection(
                conn.plant_id, conn.category,
                other.connection_id if other else "<unknown>") from exc

    async def get_connection(self, connection_id: str) -> ConnectionRow | None:
        async with self._sf() as s:
            q = select(Connection).where(Connection.connection_id == connection_id)
            row = (await s.execute(q)).scalar_one_or_none()
            return _to_connectionrow(row) if row else None

    async def list_connections(self, *, plant_id=None, category=None, status=None):
        async with self._sf() as s:
            q = select(Connection)
            if plant_id is not None:
                q = q.where(Connection.plant_id == plant_id)
            if category is not None:
                q = q.where(Connection.category == category)
            if status is not None:
                q = q.where(Connection.status == status)
            return [_to_connectionrow(r) for r in (await s.execute(q)).scalars()]

    async def delete_connection(self, connection_id: str) -> None:
        async with self._sf() as s, s.begin():
            await s.execute(delete(Connection).where(Connection.connection_id == connection_id))

    async def count_aliases_for_connection(self, connection_id: str) -> int:
        async with self._sf() as s:
            q = select(func.count()).select_from(AssetAlias).where(
                AssetAlias.connection_id == connection_id)
            return int((await s.execute(q)).scalar_one())


__all__ = ["PostgresRepository"]
