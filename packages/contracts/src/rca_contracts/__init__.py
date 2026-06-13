"""rca_contracts — canonical Pydantic contracts for the RCA MVP.

Single source of truth for all cross-package interfaces (ADR-0007). Every other
product package imports models from here; this package depends on nothing but Pydantic.
"""
from ._ids import AssetID, TenantID
from .agent import AgentLegResult, AgentName, Message
from .agent_io import LLMResponse, TokenBudget, TokenBudgetExceeded, TokenUsage
from .asset import AssetDescriptor, Criticality, ResolveAssetOutput, ResolveStatus
from .alarm import Alarm
from .canonical import CanonicalParts, parse_canonical_id
from .document import DocType, DocumentEmbeddingHit, DocumentRef
from .enums import HistorianMode, PressureReference, Quality
from .evidence import (
    AssetSummary,
    CategoryCoverage,
    CoverageReport,
    DocumentEvidence,
    EvidenceCitation,
    EvidencePackage,
    HierarchyPath,
    ISO14224Context,
    OperatorLogEvidence,
    PlanExecutionNote,
    ProvenanceEntry,
    ScoredDocument,
    TagAnomaly,
    TagEvidence,
    WorkOrderEvidence,
)
from .hitl import (
    ConclusionEdit,
    HitlAnswer,
    HitlQuestion,
    HitlResponse,
    HitlTurn,
    PlanEdit,
)
from .measurement import Measurement, MeasurementSeries
from .plan import FailureModeCandidate, InvestigationPlan, PlanStep, PlanStepType
from .probe import ProbeRunStatus, StartProbeRequest
from .provenance import Provenance
from .rca import (
    EngineerEdit,
    FishboneCategory,
    FishboneCause,
    FiveWhysChain,
    FiveWhysStep,
    OpenDataRequest,
    RankedHypothesis,
    RcaConclusion,
    RecommendedAction,
)
from .tag_descriptor import TagDescriptor
from .time_basis import TimeBasis
from .tool_error import ToolError, ToolErrorCode
from .tool_response import ToolResponse
from .work_order import WorkOrder

__contract_version__ = "0.0.1"

__all__ = [
    "__contract_version__",
    "AssetID", "TenantID",
    "PressureReference", "HistorianMode", "Quality",
    "TimeBasis", "TagDescriptor",
    "CanonicalParts", "parse_canonical_id",
    "Measurement", "MeasurementSeries",
    "Alarm", "WorkOrder", "DocumentRef", "DocType", "DocumentEmbeddingHit",
    "AssetDescriptor", "Criticality", "ResolveAssetOutput", "ResolveStatus",
    "Provenance",
    "ToolError", "ToolErrorCode",
    "ToolResponse",
    # --- Sprint 3 additions ---
    # LLM / agent I/O (WI1/WI2)
    "LLMResponse", "TokenBudget", "TokenBudgetExceeded", "TokenUsage",
    "AgentLegResult", "AgentName", "Message",
    # Planning (WI3)
    "FailureModeCandidate", "InvestigationPlan", "PlanStep", "PlanStepType",
    # HITL (WI3)
    "HitlQuestion", "HitlTurn", "HitlAnswer", "HitlResponse", "PlanEdit", "ConclusionEdit",
    # Evidence (WI4)
    "EvidencePackage", "EvidenceCitation", "ProvenanceEntry", "AssetSummary",
    "HierarchyPath", "ISO14224Context", "TagEvidence", "TagAnomaly", "WorkOrderEvidence",
    "DocumentEvidence", "ScoredDocument", "OperatorLogEvidence", "PlanExecutionNote",
    "CoverageReport", "CategoryCoverage",
    # RCA conclusion (WI5)
    "RcaConclusion", "RankedHypothesis", "FishboneCategory", "FishboneCause",
    "FiveWhysChain", "FiveWhysStep", "RecommendedAction", "OpenDataRequest", "EngineerEdit",
    # Probe lifecycle (WI2/WI3)
    "ProbeRunStatus", "StartProbeRequest",
]
