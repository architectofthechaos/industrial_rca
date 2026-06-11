"""rca_contracts — canonical Pydantic contracts for the RCA MVP.

Single source of truth for all cross-package interfaces (ADR-0007). Every other
product package imports models from here; this package depends on nothing but Pydantic.
"""
from ._ids import AssetID, TenantID
from .asset import AssetDescriptor, Criticality, ResolveAssetOutput, ResolveStatus
from .alarm import Alarm
from .canonical import CanonicalParts, parse_canonical_id
from .document import DocType, DocumentRef
from .enums import HistorianMode, PressureReference, Quality
from .measurement import Measurement, MeasurementSeries
from .provenance import Provenance
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
    "Alarm", "WorkOrder", "DocumentRef", "DocType",
    "AssetDescriptor", "Criticality", "ResolveAssetOutput", "ResolveStatus",
    "Provenance",
    "ToolError", "ToolErrorCode",
    "ToolResponse",
]
