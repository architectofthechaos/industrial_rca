"""Evidence Package contracts (Sprint 3 WI4).

The `EvidencePackage` is the canonical hand-off from gather to RCA, and the long-term
boundary a partner engine sits behind (`EvidencePackage` -> `RcaConclusion`).
LLM-derived fields carry `*_method` provenance so a reader can tell signal from model.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ._base import JsonModel
from .plan import InvestigationPlan


class EvidenceCitation(JsonModel):
    section: str          # "tag" | "work_order" | "document" | "operator_log" | "kg" | "asset"
    item_id: str
    relevance: str | None = None


class ProvenanceEntry(JsonModel):
    """Cross-section index into the per-call Provenance (G5). One per section touched."""

    section: str          # "tag" | "work_order" | "document" | "operator_log" | "kg" | "asset"
    item_id: str
    connection_id: str | None = None
    tool_name: str
    queried_at: datetime
    response_id: UUID
    record_count: int


class AssetSummary(JsonModel):
    canonical_id: str
    name: str
    iso14224_class: str
    service: str | None = None
    criticality: str | None = None
    manufacturer: str | None = None
    model: str | None = None


class HierarchyPath(JsonModel):
    site: str | None = None
    area: str | None = None
    unit: str | None = None
    plant_id: str


class ISO14224Context(JsonModel):
    equipment_class: str
    applicable_failure_modes: list[dict] = Field(default_factory=list)  # {code, name, mechanisms}


class TagAnomaly(JsonModel):
    tag_name: str
    role: str | None = None
    summary: str
    severity: str | None = None      # "normal" | "elevated" | "critical"


class TagEvidence(JsonModel):
    tags: list[dict] = Field(default_factory=list)        # per-tag summary stats
    anomalies: list[TagAnomaly] = Field(default_factory=list)
    anomaly_method: Literal["llm_v1", "rule:3sigma"] = "rule:3sigma"


class WorkOrderEvidence(JsonModel):
    work_orders: list[dict] = Field(default_factory=list)


class ScoredDocument(JsonModel):
    document_id: str
    title: str
    doc_type: str | None = None
    score: float
    excerpt: str | None = None


class DocumentEvidence(JsonModel):
    documents: list[ScoredDocument] = Field(default_factory=list)
    score_method: Literal["embedding_v1", "keyword_overlap"] = "keyword_overlap"


class OperatorLogEvidence(JsonModel):
    entries: list[dict] = Field(default_factory=list)


class CategoryCoverage(JsonModel):
    status: str          # "ok" | "skipped:connection_unhealthy" | "empty" | "skipped:no_connection"
    record_count: int = 0
    note: str | None = None


class CoverageReport(JsonModel):
    historian: CategoryCoverage
    cmms: CategoryCoverage
    documents: CategoryCoverage
    operator_log: CategoryCoverage
    llm_status: Literal["ok", "budget_exceeded", "fallback_used"] = "ok"


class PlanExecutionNote(JsonModel):
    step_id: UUID
    step_type: str
    records_returned: int
    status: str          # "ok" | "empty" | "skipped" | "error"
    deviation: str | None = None


class EvidencePackage(JsonModel):
    evidence_package_id: UUID
    probe_run_id: UUID
    canonical_id: str
    investigated_failure_modes: list[str] = Field(default_factory=list)
    reference_time: datetime
    lookback_hours: int

    # Cold context (from MAR + KG)
    asset: AssetSummary
    location: HierarchyPath
    iso14224_context: ISO14224Context

    # Warm evidence
    tag_evidence: TagEvidence
    work_order_evidence: WorkOrderEvidence
    document_evidence: DocumentEvidence
    operator_log_evidence: OperatorLogEvidence

    # Plan + agent context
    investigation_plan: InvestigationPlan
    plan_execution_notes: list[PlanExecutionNote] = Field(default_factory=list)

    # Coverage + provenance
    coverage: CoverageReport
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    assembled_at: datetime
    schema_version: str = "v1"
