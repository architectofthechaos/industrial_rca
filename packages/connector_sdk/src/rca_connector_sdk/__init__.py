"""rca_connector_sdk — the shared platform every connector is built on.

Provides the cross-cutting machinery (FastMCP skeleton, Pydantic validation,
provenance stamping, unit/time normalization, retry/circuit-breaker, error
mapping, cost accounting) so connectors only implement source fetch + translate.
Must never import `rca_simulator` (ADR-0012).
"""
from .context import RawPoint, ToolConfig, ToolContext, ToolDeps
from .errors import (
    ConnectorError,
    MalformedResponse,
    NotFound,
    PermissionDenied,
    SourceTimeout,
    SourceUnavailable,
    UnitConversionAmbiguous,
    UnresolvedSignal,
    map_source_error,
)
from .mcp import build_server, register
from .orchestrator import EvidenceTool, evidence_tool
from .ports import (
    CollectingEventSink,
    CostSink,
    Credential,
    CredentialBroker,
    EventSink,
    InMemorySignalResolver,
    NullCostSink,
    NullEventSink,
    SignalResolver,
    SourceBinding,
    StaticCredentialBroker,
)
from .subscription import RingBuffer, SubscriptionState, run_with_reconnect
from .provenance import ProvenanceAccumulator, ProvenanceMissingError
from .responses import ok_response
from .retry import with_retry
from .series import build_measurement_series
from .timeutil import build_time_basis, to_utc
from .units import to_si

__version__ = "0.0.1"

__all__ = [
    "__version__",
    # authoring
    "evidence_tool", "EvidenceTool", "RawPoint", "ToolContext", "ToolConfig", "ToolDeps",
    "build_measurement_series",
    # mcp
    "build_server", "register",
    # ports
    "SignalResolver", "CredentialBroker", "CostSink", "EventSink", "Credential", "SourceBinding",
    "InMemorySignalResolver", "StaticCredentialBroker", "NullCostSink",
    "NullEventSink", "CollectingEventSink",
    # streaming primitives
    "RingBuffer", "SubscriptionState", "run_with_reconnect",
    # helpers
    "to_si", "to_utc", "build_time_basis", "with_retry",
    "ProvenanceAccumulator", "ProvenanceMissingError", "ok_response",
    # errors
    "ConnectorError", "SourceUnavailable", "SourceTimeout", "UnresolvedSignal",
    "PermissionDenied", "NotFound", "UnitConversionAmbiguous", "MalformedResponse",
    "map_source_error",
]
