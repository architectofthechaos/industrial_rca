"""Tool adapter (Sprint 3 WI2 §2.6) — the agents' single route to platform data.

Agents never touch the DB/KG directly; every read/write goes through a ``ToolBox`` whose
methods map 1:1 to the MCP entity tools (the G14 plan-step -> tool mapping lives in
``STEP_TYPE_TO_TOOL``). ``McpToolBox`` calls the mounted entity host over HTTP (production);
``FakeToolBox`` serves deterministic fixtures so the whole probe replays hermetically.

Each data read returns ``(data, ProvenanceEntry)`` so the gather agent can assemble the
Evidence Package's provenance index with a non-null ``connection_id`` per connector-backed
section (G5).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from rca_contracts import ProvenanceEntry

# G14 — PlanStep.step_type -> the MCP tool the gather agent invokes for it.
STEP_TYPE_TO_TOOL: dict[str, str] = {
    "tag_history": "tag.get_history",
    "work_orders": "work_order.list_for_asset",
    "documents": "document.search_for_asset",
    "operator_logs": "operator_log.list_for_asset",
    "kg_query": "kg.get_asset_context",
}


def _prov(section: str, item_id: str, tool: str, connection_id: str | None, count: int,
          when: datetime) -> ProvenanceEntry:
    return ProvenanceEntry(section=section, item_id=item_id, tool_name=tool,
                           connection_id=connection_id, queried_at=when,
                           response_id=uuid4(), record_count=count)


class ToolBox(Protocol):
    async def search_assets(self, keywords: str, plant_id: str | None) -> list[dict]: ...
    async def asset_summary(self, canonical_id: str) -> dict | None: ...
    async def get_asset_context(self, canonical_id: str,
                                iso14224_class: str | None = None) -> dict: ...
    async def failure_modes_for_class(self, equipment_class_id: str) -> list[dict]: ...
    async def tag_history(self, canonical_id: str, *, reference_time: datetime,
                          lookback_hours: int) -> tuple[list[dict], ProvenanceEntry]: ...
    async def work_orders_for_asset(
        self, canonical_id: str) -> tuple[list[dict], ProvenanceEntry]: ...
    async def documents_for_asset(
        self, canonical_id: str, query: str) -> tuple[list[dict], ProvenanceEntry]: ...
    async def search_documents_by_vector(self, *, connection_id: str,
                                         query_embedding: list[float],
                                         doc_types: list[str] | None = None,
                                         top: int = 5) -> list[dict]: ...
    async def operator_logs_for_asset(
        self, canonical_id: str, *, reference_time: datetime,
        lookback_hours: int) -> tuple[list[dict], ProvenanceEntry]: ...
    async def upsert_asset(self, *, canonical_id: str, name: str, iso14224_class: str,
                           confidence: float, method: str, reference_time: datetime) -> bool: ...
    async def link_failure_mode(self, *, canonical_id: str, failure_mode_code: str) -> bool: ...


class FakeToolBox:
    """Deterministic in-memory ToolBox over a fixture dict, for hermetic probes.

    The default fixture is the refplant P-101A seal-leak scenario (G19): a mechanical-seal
    degradation with vibration/seal-flush anomalies, WO-50012402 (leak), a P&ID + datasheet,
    and an operator note. Asset class is the KG EquipmentClass id ``equipment-class:bb1``.
    """

    DEFAULT_FIXTURE: dict[str, Any] = {
        "asset": {
            "canonical_id": "asset:refinery-gc:unit-101:p-101a", "name": "P-101A",
            "iso14224_class": "equipment-class:bb1", "service": "charge pump",
            "criticality": "high", "manufacturer": "Sulzer", "model": "AHLSTAR-A22-50",
            "plant_id": "refinery-gc", "unit": "UNIT-101",
        },
        "tags": [
            {"tag_name": "P-101A.vibration_radial", "role": "vibration_radial",
             "summary": "rose from 2.1 to 6.6 mm/s over 30 days; step-change day 18",
             "mean": 3.4, "max": 6.6, "severity": "critical"},
            {"tag_name": "P-101A.seal_flush_flow", "role": "seal_flush_flow",
             "summary": "declined 4.5 L/min over the window", "mean": 6.0, "max": 9.0,
             "severity": "elevated"},
            {"tag_name": "P-101A.discharge_pressure", "role": "discharge_pressure",
             "summary": "fell ~180 kPa over the window", "mean": 1200.0, "max": 1380.0,
             "severity": "elevated"},
            {"tag_name": "P-101A.motor_amps", "role": "motor_amps",
             "summary": "crept up 8 A", "mean": 142.0, "max": 150.0, "severity": "normal"},
        ],
        "work_orders": [
            {"work_order_id": "WO-50012402", "description": "Mechanical seal leak confirmed, "
             "plan shutdown", "status": "WAPPR", "priority": "1", "failure_code": "LEK",
             "problem_code": "LEAK", "opened_at": "2026-03-28T00:00:00+00:00"},
            {"work_order_id": "WO-50012345", "description": "Vibration trending up - inspect "
             "seal", "status": "COMP", "priority": "3", "problem_code": "VIBR",
             "opened_at": "2026-03-18T00:00:00+00:00"},
        ],
        "documents": [
            {"document_id": "P-101A-DS", "title": "P-101A centrifugal pump datasheet",
             "doc_type": "datasheet", "excerpt": "Sulzer AHLSTAR, mechanical seal, flush plan 11"},
            {"document_id": "RCA-2025-014", "title": "Prior RCA: mechanical seal leak on sister "
             "pump", "doc_type": "rca_report", "excerpt": "dry-running seal face from low flush "
             "flow caused external leakage"},
        ],
        "operator_logs": [
            {"log_id": "NOTE-2026-03-06-001", "text": "P-101A slight whine, watching",
             "author": "J. Operator", "at": "2026-03-06T00:00:00+00:00"},
        ],
        "connection_ids": {
            "historian": "refinery-gc.historian.pi-main",
            "cmms": "refinery-gc.cmms.maximo-main",
            "document": "refinery-gc.document.sp-main",
            "operator_log": "refinery-gc.operator_log.pi-main",
        },
        # which KG failure modes this class can exhibit (codes that VALIDATE in the ontology)
        # mechanisms = real CAUSED_BY rels from packages/kg/seed/iso14224_bb1.cypher (D14)
        "applicable_failure_modes": [
            {"code": "ELP", "id": "failure-mode:elp", "name": "External leakage process medium",
             "mechanisms": [
                 {"id": "failure-mechanism:seal-failure", "name": "Seal failure"},
                 {"id": "failure-mechanism:corrosion", "name": "Corrosion"},
                 {"id": "failure-mechanism:wear", "name": "Wear"}]},
            {"code": "VIB", "id": "failure-mode:vib", "name": "Vibration",
             "mechanisms": [
                 {"id": "failure-mechanism:cavitation", "name": "Cavitation"},
                 {"id": "failure-mechanism:misalignment", "name": "Misalignment"},
                 {"id": "failure-mechanism:imbalance", "name": "Imbalance"},
                 {"id": "failure-mechanism:bearing-wear", "name": "Bearing wear"},
                 {"id": "failure-mechanism:looseness", "name": "Looseness"}]},
            {"code": "OHE", "id": "failure-mode:ohe", "name": "Overheating",
             "mechanisms": [
                 {"id": "failure-mechanism:lubrication-failure", "name": "Lubrication failure"},
                 {"id": "failure-mechanism:bearing-wear", "name": "Bearing wear"},
                 {"id": "failure-mechanism:overheating", "name": "Overheating"},
                 {"id": "failure-mechanism:fouling", "name": "Fouling"}]},
        ],
    }

    def __init__(self, fixture: dict[str, Any] | None = None) -> None:
        self.fixture = fixture if fixture is not None else dict(self.DEFAULT_FIXTURE)
        self.materialized: list[str] = []
        self.linked_modes: list[tuple[str, str]] = []

    def _now(self) -> datetime:
        # toolbox runs inside a Temporal activity, so wall-clock here is allowed; tests freeze
        # it via the fixture's reference_time where determinism matters.
        return datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)

    async def search_assets(self, keywords: str, plant_id: str | None) -> list[dict]:
        asset = self.fixture["asset"]
        kw = keywords.lower()
        hit = asset["name"].lower() in kw or asset["canonical_id"].split(":")[-1] in kw
        return [{"canonical_id": asset["canonical_id"], "name": asset["name"],
                 "confidence": 0.95 if hit else 0.4}] if hit or not kw else [
            {"canonical_id": asset["canonical_id"], "name": asset["name"], "confidence": 0.5}]

    async def asset_summary(self, canonical_id: str) -> dict | None:
        a = self.fixture["asset"]
        return a if a["canonical_id"] == canonical_id else None

    async def get_asset_context(self, canonical_id: str,
                                iso14224_class: str | None = None) -> dict:
        a = self.fixture["asset"]
        return {
            "kg_warm": False, "asset": a if a["canonical_id"] == canonical_id else None,
            "iso14224_class": a["iso14224_class"],
            "applicable_failure_modes": self.fixture["applicable_failure_modes"],
            "prior_events_on_asset": [], "prior_events_for_class_at_plant": [],
        }

    async def tag_history(self, canonical_id: str, *, reference_time: datetime,
                          lookback_hours: int) -> tuple[list[dict], ProvenanceEntry]:
        tags = self.fixture["tags"]
        prov = _prov("tag", canonical_id, "tag.get_history",
                     self.fixture["connection_ids"]["historian"], len(tags), reference_time)
        return tags, prov

    async def work_orders_for_asset(
        self, canonical_id: str) -> tuple[list[dict], ProvenanceEntry]:
        wos = self.fixture["work_orders"]
        prov = _prov("work_order", canonical_id, "work_order.list_for_asset",
                     self.fixture["connection_ids"]["cmms"], len(wos), self._now())
        return wos, prov

    async def documents_for_asset(
        self, canonical_id: str, query: str) -> tuple[list[dict], ProvenanceEntry]:
        docs = self.fixture["documents"]
        prov = _prov("document", canonical_id, "document.search_for_asset",
                     self.fixture["connection_ids"]["document"], len(docs), self._now())
        return docs, prov

    async def search_documents_by_vector(self, *, connection_id: str,
                                         query_embedding: list[float],
                                         doc_types: list[str] | None = None,
                                         top: int = 5) -> list[dict]:
        # Demonstrate the SEMANTIC WIN: the prior RCA (rca_report) ranks above the datasheet
        # because its embedding is closest to the failure-mode query — the opposite of what
        # keyword overlap produces (the datasheet matches more failure-mode keyword terms).
        docs = self.fixture["documents"]
        by_id = {d["document_id"]: d for d in docs}
        hits = [
            {"document_id": "RCA-2025-014", "doc_type": "rca_report",
             "description": "prior seal-leak RCA", "score": 0.95},
            {"document_id": "P-101A-DS", "doc_type": "datasheet",
             "description": "pump datasheet", "score": 0.55},
        ]
        # Filter to only hits whose document_id actually exists in the fixture and match doc_types
        result = []
        for h in hits:
            if h["document_id"] not in by_id:
                continue
            if doc_types and h["doc_type"] not in doc_types:
                continue
            result.append(h)
        return result[:top]

    async def operator_logs_for_asset(
        self, canonical_id: str, *, reference_time: datetime,
        lookback_hours: int) -> tuple[list[dict], ProvenanceEntry]:
        logs = self.fixture["operator_logs"]
        prov = _prov("operator_log", canonical_id, "operator_log.list_for_asset",
                     self.fixture["connection_ids"]["operator_log"], len(logs), reference_time)
        return logs, prov

    async def upsert_asset(self, *, canonical_id: str, name: str, iso14224_class: str,
                           confidence: float, method: str, reference_time: datetime) -> bool:
        created = canonical_id not in self.materialized
        if created:
            self.materialized.append(canonical_id)
        return created

    async def link_failure_mode(self, *, canonical_id: str, failure_mode_code: str) -> bool:
        pair = (canonical_id, failure_mode_code)
        if pair in self.linked_modes:
            return False
        self.linked_modes.append(pair)
        return True

    async def failure_modes_for_class(self, equipment_class_id: str) -> list[dict]:
        return list(self.fixture["applicable_failure_modes"])


__all__ = ["ToolBox", "FakeToolBox", "STEP_TYPE_TO_TOOL", "ProvenanceEntry"]
