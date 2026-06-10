"""Ports for services the SDK depends on but that aren't built yet.

Each is a Protocol with a trivial default implementation, so connectors are
buildable before the real TRS / MAR / credential-broker / cost services exist.

The SignalResolver stands in for TRS: it canonicalizes a signal AND provides the
per-source binding (the source-side handle + the raw unit the source emits), which
is the alias information TRS will eventually own (ADR-0001).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from rca_contracts import AssetID, SignalDescriptor, SignalID

from .errors import UnresolvedSignal


@dataclass(frozen=True)
class Credential:
    endpoint: str | None = None
    secret: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceBinding:
    """How a canonical signal maps onto one source: its handle + the unit it emits."""

    handle: str          # PI WebID / OPC UA NodeId / Maximo location / SAP EQUNR / ...
    raw_unit: str        # the unit the source emits this signal's values in


@runtime_checkable
class SignalResolver(Protocol):
    async def resolve(self, signal_id: SignalID) -> SignalDescriptor: ...
    # entity_id is a signal_id (signal-scoped tools) or an asset_id (asset-scoped tools)
    async def source_binding(self, entity_id: SignalID | AssetID, source: str) -> SourceBinding: ...


@runtime_checkable
class CredentialBroker(Protocol):
    async def get(self, ref: str | None) -> Credential: ...


@runtime_checkable
class CostSink(Protocol):
    def record(self, *, tool: str, source: str, record_count: int) -> None: ...


@runtime_checkable
class EventSink(Protocol):
    """Discovery/ingestion events a streaming connector emits (e.g. MQTT BIRTH alias
    candidates the TRS onboarding workflow later consumes)."""
    def emit(self, event: dict) -> None: ...


# ---- default implementations (dev / echo) ----

class InMemorySignalResolver:
    def __init__(
        self,
        signals: dict[SignalID, SignalDescriptor],
        bindings: dict[tuple[SignalID, str], SourceBinding] | None = None,
    ) -> None:
        self._signals = dict(signals)
        self._bindings = dict(bindings or {})

    async def resolve(self, signal_id: SignalID) -> SignalDescriptor:
        try:
            return self._signals[signal_id]
        except KeyError:
            raise UnresolvedSignal(f"signal {signal_id} not found in resolver") from None

    async def source_binding(self, entity_id: SignalID | AssetID, source: str) -> SourceBinding:
        try:
            return self._bindings[(entity_id, source)]
        except KeyError:
            raise UnresolvedSignal(
                f"no source binding for entity {entity_id} on source {source!r}"
            ) from None


class StaticCredentialBroker:
    def __init__(self, credential: Credential | None = None) -> None:
        self._credential = credential or Credential()

    async def get(self, ref: str | None) -> Credential:
        return self._credential


class NullCostSink:
    def record(self, *, tool: str, source: str, record_count: int) -> None:
        return None


class NullEventSink:
    def emit(self, event: dict) -> None:
        return None


class CollectingEventSink:
    """In-memory sink for dev/tests; stands in for the TRS alias-candidate intake."""
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event: dict) -> None:
        self.events.append(event)


__all__ = [
    "Credential", "SourceBinding", "SignalResolver", "CredentialBroker", "CostSink", "EventSink",
    "InMemorySignalResolver", "StaticCredentialBroker", "NullCostSink",
    "NullEventSink", "CollectingEventSink",
]
