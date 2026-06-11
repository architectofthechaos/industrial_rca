"""Per-call context, per-tool config, and dependency bundle for the orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from rca_contracts import Quality, TagDescriptor

from .ports import (
    CostSink,
    Credential,
    CredentialBroker,
    NullCostSink,
    SourceBinding,
    StaticCredentialBroker,
    TagResolver,
)
from .provenance import ProvenanceAccumulator


@dataclass(frozen=True)
class RawPoint:
    """A single source-native sample before unit/time normalization."""

    timestamp: datetime
    value: float
    quality: Quality = "good"
    is_interpolated: bool = False


@dataclass(frozen=True)
class ToolConfig:
    """Per-deployment config (source-side wiring, not the MCP contract).

    Note: the source raw unit is per-tag and comes from the resolver's
    SourceBinding, not from here.
    """

    source_timezone: str = "UTC"
    endpoint: str | None = None
    credential_ref: str | None = None
    retry_attempts: int = 3
    extra: dict[str, str] = field(default_factory=dict)   # connector-specific config (e.g. ns URI)


@dataclass
class ToolDeps:
    """Everything the SDK needs to run a tool, injected at server-build time."""

    tag_resolver: TagResolver
    config: ToolConfig
    credential_broker: CredentialBroker = field(default_factory=StaticCredentialBroker)
    cost_sink: CostSink = field(default_factory=NullCostSink)
    http_client: httpx.AsyncClient | None = None


@dataclass
class ToolContext:
    """Passed to a connector's fetch()/translate(); carries resolved deps + the prov accumulator."""

    request: Any
    config: ToolConfig
    tag: TagDescriptor | None                   # None for asset-scoped / query-scoped tools
    source: SourceBinding | None                # None for query-scoped tools (e.g. documents.search)
    source_name: str                            # source system id, e.g. "pi", "sap_pm"
    prov: ProvenanceAccumulator
    credential: Credential
    http: httpx.AsyncClient | None = None


__all__ = ["RawPoint", "ToolConfig", "ToolDeps", "ToolContext"]
