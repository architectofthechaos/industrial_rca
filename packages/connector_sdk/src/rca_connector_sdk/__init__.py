"""rca_connector_sdk — the shared platform every connector is built on.

Provides the cross-cutting machinery (FastMCP skeleton, Pydantic validation,
provenance stamping, unit/time normalization, retry/circuit-breaker, error
mapping, cost accounting) so connectors only implement source fetch + translate.
Must never import `rca_simulator` (ADR-0012).
"""
from .assets import AssetGateway, CanonicalSlugAssetGateway, StaticAssetGateway
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
from .health import (
    CheckResult,
    HealthProbe,
    HealthReport,
    ProbeResult,
    TestConnectionRequest,
    TestConnectionResponse,
    register_health,
    skipped_check,
    timed_check,
)
from .mcp import build_server, register
from .orchestrator import EvidenceTool, evidence_tool
from .ports import (
    CollectingEventSink,
    CostSink,
    Credential,
    CredentialBroker,
    EventSink,
    InMemoryTagResolver,
    NullCostSink,
    NullEventSink,
    SourceBinding,
    StaticCredentialBroker,
    TagResolver,
)
from .routing import (
    ConnectionInfo,
    ConnectionRouter,
    NoActiveConnection,
    StaticConnectionRouter,
)
from .secrets import (
    EnvSecretResolver,
    SecretRef,
    SecretResolver,
    UnsupportedSecretScheme,
)
from .subscription import RingBuffer, SubscriptionState, run_with_reconnect
from .provenance import ProvenanceAccumulator, ProvenanceMissingError
from .responses import ok_response
from .retry import with_retry
from .series import build_measurement_series
from .timeutil import build_time_basis, to_utc
from .units import canonical_unit_for, to_si

__version__ = "0.0.1"

__all__ = [
    "__version__",
    # authoring
    "evidence_tool", "EvidenceTool", "RawPoint", "ToolContext", "ToolConfig", "ToolDeps",
    "build_measurement_series",
    # mcp
    "build_server", "register",
    # health (aggregate/success stay in rca_connector_sdk.health — names too generic here)
    "register_health", "HealthProbe", "ProbeResult", "timed_check", "skipped_check",
    "CheckResult", "HealthReport", "TestConnectionRequest", "TestConnectionResponse",
    # ports
    "TagResolver", "CredentialBroker", "CostSink", "EventSink", "Credential", "SourceBinding",
    "InMemoryTagResolver", "StaticCredentialBroker", "NullCostSink",
    "NullEventSink", "CollectingEventSink",
    # connection routing
    "ConnectionInfo", "ConnectionRouter", "StaticConnectionRouter", "NoActiveConnection",
    # asset gateway (canonical_id -> vendor tag / source handle)
    "AssetGateway", "CanonicalSlugAssetGateway", "StaticAssetGateway",
    # secret refs
    "SecretRef", "SecretResolver", "EnvSecretResolver", "UnsupportedSecretScheme",
    # streaming primitives
    "RingBuffer", "SubscriptionState", "run_with_reconnect",
    # helpers
    "to_si", "canonical_unit_for", "to_utc", "build_time_basis", "with_retry",
    "ProvenanceAccumulator", "ProvenanceMissingError", "ok_response",
    # errors
    "ConnectorError", "SourceUnavailable", "SourceTimeout", "UnresolvedSignal",
    "PermissionDenied", "NotFound", "UnitConversionAmbiguous", "MalformedResponse",
    "map_source_error",
]
