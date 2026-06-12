"""KG Asset/event layer — lazy materialization + warm-layer writes (Sprint 3 WI4/WI6).

The read-only ontology/hierarchy lives behind ``queries.KgGateway``; this module adds the
**writable** Asset layer the probe needs: ``kg.upsert_asset`` (lazy first-touch), the
``kg.link_failure_mode`` ontology-validated edge, ``kg.get_asset_context`` (cold/warm
context for planning + gather), and the close-phase ``persist_failure_event`` /
``link_resulted_in_wo`` (the FIRST writes to the warm KG layer).

Invariants:
- ``upsert_asset`` validates ``Asset.id`` against the Sprint-1 canonical regex (G4) BEFORE any
  write, deriving plant_id/unit_slug from the id (never trusting a passed-in plant_id).
- ``link_failure_mode`` MATCHes ``(EquipmentClass)-[:CAN_EXHIBIT]->(FailureMode {code})`` in the
  Sprint-2a ontology and refuses to write an invalid (class, mode) pair (G3).
- ``persist_failure_event`` MATCHes the ontology FailureMode (by ``code``) and FailureMechanism
  (by ``id``) — never MERGE-creating them — so the warm write can't fork the ontology (G23).
- All writes are idempotent: a re-run creates zero new nodes/edges (asserted via ``write_count``
  on the in-memory impl, mirroring ``InMemoryHierarchyWriter``).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from neo4j import AsyncDriver, AsyncManagedTransaction
from pydantic import BaseModel, Field
from rca_contracts import parse_canonical_id

from rca_kg import config
from rca_kg.class_map import UnknownEquipmentClass


def _native_props(props: dict[str, Any]) -> dict[str, Any]:
    """Coerce Neo4j temporal property values (``neo4j.time.DateTime``/``Date``/``Time``) to
    their python natives so Pydantic ``datetime`` fields validate (G23). Non-temporal values
    pass through untouched. Neo4j returns stored datetimes as ``neo4j.time.DateTime``, which
    Pydantic rejects for a ``datetime`` field — this bites when reading a *materialized* asset
    back (``get_asset_context`` on a warm asset / the flywheel)."""
    return {k: (v.to_native() if hasattr(v, "to_native") else v) for k, v in props.items()}


class AssetContextSummary(BaseModel):
    id: str
    name: str
    plant_id: str
    unit_slug: str
    iso14224_class: str
    iso14224_class_confidence: float | None = None
    iso14224_class_method: str | None = None
    materialized_at: datetime | None = None
    last_probed_at: datetime | None = None


class FailureEventSummary(BaseModel):
    event_id: str
    canonical_id: str
    iso14224_failure_mode: str
    iso14224_mechanism: str | None = None
    iso14224_cause: str | None = None
    narrative: str | None = None
    confidence: float | None = None
    concluded_at: datetime | None = None


class AssetContext(BaseModel):
    kg_warm: bool                                  # True if any prior failure event (asset or class)
    asset: AssetContextSummary | None = None       # None on a cold KG (asset not yet materialized)
    iso14224_class: str | None = None
    applicable_failure_modes: list[dict] = Field(default_factory=list)
    prior_events_on_asset: list[FailureEventSummary] = Field(default_factory=list)
    prior_events_for_class_at_plant: list[FailureEventSummary] = Field(default_factory=list)


def _unit_id(plant_id: str, unit_slug: str) -> str:
    return f"unit:{plant_id}:{unit_slug}"


class AssetGraph(Protocol):
    """Read+write access to the Asset/event layer (the four kg.* asset tools + close phase)."""

    async def upsert_asset(
        self, *, canonical_id: str, name: str, iso14224_class: str,
        iso14224_class_confidence: float, iso14224_class_method: str, probed_at: datetime,
    ) -> bool: ...

    async def link_failure_mode(self, *, canonical_id: str, failure_mode_code: str) -> None: ...

    async def get_asset_context(
        self, *, canonical_id: str, iso14224_class: str | None = None
    ) -> AssetContext: ...

    async def persist_failure_event(
        self, *, event_id: str, probe_run_id: str, conclusion_id: str, canonical_id: str,
        iso14224_failure_mode: str, iso14224_mechanism: str, iso14224_cause: str | None,
        narrative: str, confidence: float, detected_at: datetime, concluded_at: datetime,
        engineer_approval_status: str,
    ) -> bool: ...

    async def link_resulted_in_wo(self, *, event_id: str, work_order_id: str) -> None: ...


class InvalidFailureModePair(ValueError):
    """(EquipmentClass, FailureMode) pair not present in the ISO 14224 ontology."""


# --------------------------------------------------------------------------------------
# In-memory implementation (hermetic tests). Shares the {(label,id):props} / edge-list
# representation of queries.InMemoryGateway so the same store can back both seams.
# --------------------------------------------------------------------------------------
class InMemoryAssetGraph:
    def __init__(
        self,
        nodes: dict[tuple[str, str], dict[str, Any]] | None = None,
        edges: list[tuple[str, str, str]] | None = None,
    ) -> None:
        self.nodes: dict[tuple[str, str], dict[str, Any]] = dict(nodes or {})
        self.edges: list[tuple[str, str, str]] = list(edges or [])
        self.write_count = 0

    # -- helpers ----------------------------------------------------------------
    def _node(self, label: str, node_id: str) -> dict[str, Any] | None:
        return self.nodes.get((label, node_id))

    def _has_edge(self, src: str, rel: str, dst: str) -> bool:
        return (src, rel, dst) in self.edges

    def _add_edge(self, src: str, rel: str, dst: str) -> None:
        if not self._has_edge(src, rel, dst):
            self.edges.append((src, rel, dst))
            self.write_count += 1

    def _failure_mode_id_for_code(self, code: str) -> str | None:
        for (label, node_id), props in self.nodes.items():
            if label == "FailureMode" and props.get("code") == code:
                return node_id
        return None

    # -- writes -----------------------------------------------------------------
    async def upsert_asset(
        self, *, canonical_id: str, name: str, iso14224_class: str,
        iso14224_class_confidence: float, iso14224_class_method: str, probed_at: datetime,
    ) -> bool:
        parts = parse_canonical_id(canonical_id)   # G4 — raises ValueError on a bad id
        key = ("Asset", canonical_id)
        existing = self.nodes.get(key)
        created = existing is None
        props = {
            "id": canonical_id, "name": name, "plant_id": parts.plant_id,
            "unit_slug": parts.unit_slug, "iso14224_class": iso14224_class,
            "iso14224_class_confidence": iso14224_class_confidence,
            "iso14224_class_method": iso14224_class_method,
            "materialized_at": (existing or {}).get("materialized_at", probed_at),
            "last_probed_at": probed_at,
        }
        if created:
            self.write_count += 1
        self.nodes[key] = props
        # LOCATED_IN the unit (only if the hierarchy node exists), INSTANCE_OF the class.
        unit_id = _unit_id(parts.plant_id, parts.unit_slug)
        if self._node("Unit", unit_id) is not None:
            self._add_edge(canonical_id, "LOCATED_IN", unit_id)
        if self._node("EquipmentClass", iso14224_class) is None:
            raise UnknownEquipmentClass(
                f"EquipmentClass {iso14224_class!r} not in KG; cannot link INSTANCE_OF "
                f"for {canonical_id!r}")
        self._add_edge(canonical_id, "INSTANCE_OF", iso14224_class)
        return created

    async def link_failure_mode(self, *, canonical_id: str, failure_mode_code: str) -> None:
        asset = self._node("Asset", canonical_id)
        if asset is None:
            raise ValueError(f"asset {canonical_id} is not materialized; upsert it first")
        ec_id = asset["iso14224_class"]
        fm_id = self._failure_mode_id_for_code(failure_mode_code)
        if fm_id is None or not self._has_edge(ec_id, "CAN_EXHIBIT", fm_id):
            raise InvalidFailureModePair(
                f"({ec_id}, {failure_mode_code}) is not a valid ISO 14224 (class, mode) pair")
        self._add_edge(canonical_id, "CAN_EXHIBIT", fm_id)

    async def persist_failure_event(
        self, *, event_id: str, probe_run_id: str, conclusion_id: str, canonical_id: str,
        iso14224_failure_mode: str, iso14224_mechanism: str, iso14224_cause: str | None,
        narrative: str, confidence: float, detected_at: datetime, concluded_at: datetime,
        engineer_approval_status: str,
    ) -> bool:
        fm_id = self._failure_mode_id_for_code(iso14224_failure_mode)
        if fm_id is None:
            raise InvalidFailureModePair(
                f"failure mode code {iso14224_failure_mode!r} not in ontology")
        if self._node("FailureMechanism", iso14224_mechanism) is None:
            raise InvalidFailureModePair(
                f"failure mechanism {iso14224_mechanism!r} not in ontology")
        key = ("HistoricalFailureEvent", event_id)
        created = key not in self.nodes
        if created:
            self.write_count += 1
        self.nodes[key] = {
            "id": event_id, "probe_run_id": probe_run_id, "conclusion_id": conclusion_id,
            "canonical_id": canonical_id, "iso14224_failure_mode": iso14224_failure_mode,
            "iso14224_mechanism": iso14224_mechanism, "iso14224_cause": iso14224_cause,
            "narrative": narrative, "confidence": confidence, "detected_at": detected_at,
            "concluded_at": concluded_at, "engineer_approved": True,
            "engineer_approval_status": engineer_approval_status,
        }
        # Asset is MERGEd (probe always upserts it during gather, but be defensive).
        if self._node("Asset", canonical_id) is None:
            self.nodes[("Asset", canonical_id)] = {"id": canonical_id}
            self.write_count += 1
        self._add_edge(canonical_id, "HAS_FAILURE_EVENT", event_id)
        self._add_edge(event_id, "CLASSIFIED_AS", fm_id)
        self._add_edge(event_id, "CAUSED_BY_MECHANISM", iso14224_mechanism)
        return created

    async def link_resulted_in_wo(self, *, event_id: str, work_order_id: str) -> None:
        key = ("WorkOrder", work_order_id)
        if key not in self.nodes:
            self.nodes[key] = {"id": work_order_id}
            self.write_count += 1
        self._add_edge(event_id, "RESULTED_IN", work_order_id)

    # -- reads ------------------------------------------------------------------
    async def get_asset_context(
        self, *, canonical_id: str, iso14224_class: str | None = None
    ) -> AssetContext:
        asset_props = self._node("Asset", canonical_id)
        summary = None
        cls = iso14224_class
        plant_id = None
        if asset_props is not None and asset_props.get("iso14224_class"):
            summary = AssetContextSummary.model_validate(asset_props)
            cls = asset_props["iso14224_class"]
            plant_id = asset_props.get("plant_id")
        elif canonical_id.count(":") == 3:
            plant_id = parse_canonical_id(canonical_id).plant_id

        applicable = self._applicable_failure_modes(cls) if cls else []
        on_asset = self._events_for(lambda p: p.get("canonical_id") == canonical_id)
        for_class = []
        if cls and plant_id:
            asset_ids_in_class = {
                nid for (lbl, nid), p in self.nodes.items()
                if lbl == "Asset" and p.get("iso14224_class") == cls
                and p.get("plant_id") == plant_id and nid != canonical_id
            }
            for_class = self._events_for(
                lambda p: p.get("canonical_id") in asset_ids_in_class)
        return AssetContext(
            kg_warm=bool(on_asset or for_class),
            asset=summary, iso14224_class=cls,
            applicable_failure_modes=applicable,
            prior_events_on_asset=on_asset,
            prior_events_for_class_at_plant=for_class,
        )

    def _applicable_failure_modes(self, equipment_class_id: str) -> list[dict]:
        out = []
        for src, rel, dst in self.edges:
            if src == equipment_class_id and rel == "CAN_EXHIBIT":
                props = self._node("FailureMode", dst)
                if props is not None:
                    out.append({"code": props.get("code"), "id": dst,
                                "name": props.get("name")})
        return sorted(out, key=lambda e: e.get("code") or "")

    def _events_for(self, pred: Any) -> list[FailureEventSummary]:
        out = []
        for (label, nid), props in self.nodes.items():
            if label == "HistoricalFailureEvent" and pred(props):
                out.append(FailureEventSummary(
                    event_id=nid, canonical_id=props.get("canonical_id", ""),
                    iso14224_failure_mode=props.get("iso14224_failure_mode", ""),
                    iso14224_mechanism=props.get("iso14224_mechanism"),
                    iso14224_cause=props.get("iso14224_cause"),
                    narrative=props.get("narrative"), confidence=props.get("confidence"),
                    concluded_at=props.get("concluded_at")))
        return sorted(out, key=lambda e: e.event_id)


# --------------------------------------------------------------------------------------
# Neo4j implementation.
# --------------------------------------------------------------------------------------
class Neo4jAssetGraph:
    def __init__(self, driver: AsyncDriver | None = None, database: str | None = None) -> None:
        self._driver = driver if driver is not None else config.make_async_driver()
        self._database = database if database is not None else config.kg_database()

    async def aclose(self) -> None:
        await self._driver.close()

    async def _write(self, query: str, **params: Any) -> list[dict[str, Any]]:
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            result = await tx.run(query, params)  # type: ignore[arg-type]
            return await result.data()

        async with self._driver.session(database=self._database) as session:
            return await session.execute_write(work)

    async def _read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            result = await tx.run(query, params)  # type: ignore[arg-type]
            return await result.data()

        async with self._driver.session(database=self._database) as session:
            return await session.execute_read(work)

    async def upsert_asset(
        self, *, canonical_id: str, name: str, iso14224_class: str,
        iso14224_class_confidence: float, iso14224_class_method: str, probed_at: datetime,
    ) -> bool:
        parts = parse_canonical_id(canonical_id)   # G4
        exists = await self._read(
            "MATCH (ec:EquipmentClass {id: $cls}) RETURN ec.id AS id", cls=iso14224_class)
        if not exists:
            raise UnknownEquipmentClass(
                f"EquipmentClass {iso14224_class!r} not in KG; refusing to upsert "
                f"{canonical_id!r} (would orphan the asset)")
        rows = await self._write(
            "MERGE (a:Asset {id: $id})\n"
            "ON CREATE SET a.materialized_at = $probed_at, a._created = true\n"
            "SET a.name = $name, a.plant_id = $plant_id, a.unit_slug = $unit_slug,\n"
            "    a.iso14224_class = $cls, a.iso14224_class_confidence = $conf,\n"
            "    a.iso14224_class_method = $method, a.last_probed_at = $probed_at\n"
            "WITH a, coalesce(a._created, false) AS created\n"
            "REMOVE a._created\n"
            "WITH a, created\n"
            "OPTIONAL MATCH (u:Unit {id: $unit_id})\n"
            "FOREACH (_ IN CASE WHEN u IS NULL THEN [] ELSE [1] END |\n"
            "    MERGE (a)-[:LOCATED_IN]->(u))\n"
            "WITH a, created\n"
            "MATCH (ec:EquipmentClass {id: $cls})\n"
            "MERGE (a)-[:INSTANCE_OF]->(ec)\n"
            "RETURN created",
            id=canonical_id, name=name, plant_id=parts.plant_id, unit_slug=parts.unit_slug,
            cls=iso14224_class, conf=iso14224_class_confidence, method=iso14224_class_method,
            probed_at=probed_at, unit_id=_unit_id(parts.plant_id, parts.unit_slug),
        )
        return bool(rows and rows[0].get("created"))

    async def link_failure_mode(self, *, canonical_id: str, failure_mode_code: str) -> None:
        rows = await self._write(
            "MATCH (a:Asset {id: $id})\n"
            "MATCH (ec:EquipmentClass {id: a.iso14224_class})-[:CAN_EXHIBIT]->"
            "(fm:FailureMode {code: $code})\n"
            "MERGE (a)-[:CAN_EXHIBIT]->(fm)\n"
            "RETURN fm.id AS fm_id",
            id=canonical_id, code=failure_mode_code,
        )
        if not rows:
            raise InvalidFailureModePair(
                f"({canonical_id}, {failure_mode_code}) is not a valid ISO 14224 (class, mode) "
                "pair, or the asset is not materialized")

    async def persist_failure_event(
        self, *, event_id: str, probe_run_id: str, conclusion_id: str, canonical_id: str,
        iso14224_failure_mode: str, iso14224_mechanism: str, iso14224_cause: str | None,
        narrative: str, confidence: float, detected_at: datetime, concluded_at: datetime,
        engineer_approval_status: str,
    ) -> bool:
        # Ontology nodes are MATCHed, never MERGE-created (G23). Pre-validate they exist.
        check = await self._read(
            "OPTIONAL MATCH (fm:FailureMode {code: $code})\n"
            "OPTIONAL MATCH (mech:FailureMechanism {id: $mech})\n"
            "RETURN fm IS NOT NULL AS has_fm, mech IS NOT NULL AS has_mech",
            code=iso14224_failure_mode, mech=iso14224_mechanism,
        )
        if not check or not check[0]["has_fm"]:
            raise InvalidFailureModePair(f"failure mode {iso14224_failure_mode!r} not in ontology")
        if not check[0]["has_mech"]:
            raise InvalidFailureModePair(f"mechanism {iso14224_mechanism!r} not in ontology")
        rows = await self._write(
            "MERGE (fe:HistoricalFailureEvent {id: $event_id})\n"
            "ON CREATE SET fe._created = true\n"
            "SET fe.probe_run_id = $probe_run_id, fe.conclusion_id = $conclusion_id,\n"
            "    fe.canonical_id = $canonical_id, fe.iso14224_failure_mode = $mode,\n"
            "    fe.iso14224_mechanism = $mech, fe.iso14224_cause = $cause,\n"
            "    fe.narrative = $narrative, fe.confidence = $confidence,\n"
            "    fe.detected_at = $detected_at, fe.concluded_at = $concluded_at,\n"
            "    fe.engineer_approved = true, fe.engineer_approval_status = $status\n"
            "WITH fe, coalesce(fe._created, false) AS created\n"
            "REMOVE fe._created\n"
            "MERGE (a:Asset {id: $canonical_id})\n"
            "MERGE (a)-[:HAS_FAILURE_EVENT]->(fe)\n"
            "WITH fe, created\n"
            "MATCH (fm:FailureMode {code: $mode})\n"
            "MERGE (fe)-[:CLASSIFIED_AS]->(fm)\n"
            "WITH fe, created\n"
            "MATCH (mech:FailureMechanism {id: $mech})\n"
            "MERGE (fe)-[:CAUSED_BY_MECHANISM]->(mech)\n"
            "RETURN created",
            event_id=event_id, probe_run_id=probe_run_id, conclusion_id=conclusion_id,
            canonical_id=canonical_id, mode=iso14224_failure_mode, mech=iso14224_mechanism,
            cause=iso14224_cause, narrative=narrative, confidence=confidence,
            detected_at=detected_at, concluded_at=concluded_at, status=engineer_approval_status,
        )
        return bool(rows and rows[0].get("created"))

    async def link_resulted_in_wo(self, *, event_id: str, work_order_id: str) -> None:
        await self._write(
            "MATCH (fe:HistoricalFailureEvent {id: $event_id})\n"
            "MERGE (wo:WorkOrder {id: $wo_id})\n"
            "MERGE (fe)-[:RESULTED_IN]->(wo)",
            event_id=event_id, wo_id=work_order_id,
        )

    async def get_asset_context(
        self, *, canonical_id: str, iso14224_class: str | None = None
    ) -> AssetContext:
        rows = await self._read(
            "OPTIONAL MATCH (a:Asset {id: $id}) RETURN properties(a) AS props", id=canonical_id)
        asset_props = rows[0]["props"] if rows and rows[0]["props"] else None
        summary = None
        cls = iso14224_class
        plant_id = None
        if asset_props and asset_props.get("iso14224_class"):
            summary = AssetContextSummary.model_validate(_native_props(asset_props))
            cls = asset_props.get("iso14224_class") or cls
            plant_id = asset_props.get("plant_id")
        elif canonical_id.count(":") == 3:
            plant_id = parse_canonical_id(canonical_id).plant_id

        applicable: list[dict] = []
        if cls:
            fm_rows = await self._read(
                "MATCH (ec:EquipmentClass {id: $cls})-[:CAN_EXHIBIT]->(fm:FailureMode)\n"
                "RETURN fm.code AS code, fm.id AS id, fm.name AS name ORDER BY fm.code", cls=cls)
            applicable = [dict(r) for r in fm_rows]

        on_asset = await self._read(
            "MATCH (a:Asset {id: $id})-[:HAS_FAILURE_EVENT]->(fe:HistoricalFailureEvent)\n"
            "RETURN properties(fe) AS props ORDER BY fe.id", id=canonical_id)
        for_class: list[dict[str, Any]] = []
        if cls and plant_id:
            for_class = await self._read(
                "MATCH (other:Asset {iso14224_class: $cls, plant_id: $plant})"
                "-[:HAS_FAILURE_EVENT]->(fe:HistoricalFailureEvent)\n"
                "WHERE other.id <> $id\n"
                "RETURN properties(fe) AS props ORDER BY fe.id",
                cls=cls, plant=plant_id, id=canonical_id)

        def _summ(rows_: list[dict[str, Any]]) -> list[FailureEventSummary]:
            out = []
            for r in rows_:
                p = _native_props(r["props"])
                out.append(FailureEventSummary(
                    event_id=p.get("id", ""), canonical_id=p.get("canonical_id", ""),
                    iso14224_failure_mode=p.get("iso14224_failure_mode", ""),
                    iso14224_mechanism=p.get("iso14224_mechanism"),
                    iso14224_cause=p.get("iso14224_cause"), narrative=p.get("narrative"),
                    confidence=p.get("confidence"), concluded_at=p.get("concluded_at")))
            return out

        ev_asset = _summ(on_asset)
        ev_class = _summ(for_class)
        return AssetContext(
            kg_warm=bool(ev_asset or ev_class), asset=summary, iso14224_class=cls,
            applicable_failure_modes=applicable, prior_events_on_asset=ev_asset,
            prior_events_for_class_at_plant=ev_class,
        )


__all__ = [
    "AssetGraph", "InMemoryAssetGraph", "Neo4jAssetGraph",
    "InvalidFailureModePair", "UnknownEquipmentClass",
    "AssetContext", "AssetContextSummary", "FailureEventSummary",
]
