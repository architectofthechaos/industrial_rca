"""Ports for services the SDK depends on but that aren't built yet.

Each is a Protocol with a trivial default implementation, so connectors are
buildable before the real MAR / onboarding / credential-broker / cost services exist.

The TagResolver stands in for the onboarding registry: it canonicalizes an entity into
a TagDescriptor AND provides the per-source binding (the source-side handle + the raw
unit the source emits), which is the alias information onboarding will eventually own
(ADR-0001).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from uuid import UUID

from rca_contracts import TagDescriptor

from .errors import UnresolvedSignal


@dataclass(frozen=True)
class Credential:
    endpoint: str | None = None
    secret: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceBinding:
    """How a canonical entity maps onto one source: its handle + the unit it emits."""

    handle: str          # PI WebID / OPC UA NodeId / Maximo location / SAP EQUNR / ...
    raw_unit: str        # the unit the source emits this entity's values in


@runtime_checkable
class TagResolver(Protocol):
    async def resolve(self, entity_id: UUID) -> TagDescriptor: ...
    # entity_id is a tag/signal id (signal-scoped tools) or an asset_id (asset-scoped tools)
    async def source_binding(self, entity_id: UUID, source: str) -> SourceBinding: ...


@runtime_checkable
class CredentialBroker(Protocol):
    async def get(self, ref: str | None) -> Credential: ...


@runtime_checkable
class CostSink(Protocol):
    def record(self, *, tool: str, source: str, record_count: int) -> None: ...


@runtime_checkable
class EventSink(Protocol):
    """Discovery/ingestion events a streaming connector emits (e.g. MQTT BIRTH alias
    candidates the onboarding workflow later consumes)."""
    def emit(self, event: dict) -> None: ...


# ---- default implementations (dev / echo) ----

class InMemoryTagResolver:
    def __init__(
        self,
        tags: dict[UUID, TagDescriptor],
        bindings: dict[tuple[UUID, str], SourceBinding] | None = None,
    ) -> None:
        self._tags = dict(tags)
        self._bindings = dict(bindings or {})

    async def resolve(self, entity_id: UUID) -> TagDescriptor:
        try:
            return self._tags[entity_id]
        except KeyError:
            raise UnresolvedSignal(f"tag {entity_id} not found in resolver") from None

    async def source_binding(self, entity_id: UUID, source: str) -> SourceBinding:
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
    """In-memory sink for dev/tests; stands in for the onboarding alias-candidate intake."""
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event: dict) -> None:
        self.events.append(event)


__all__ = [
    "Credential", "SourceBinding", "TagResolver", "CredentialBroker", "CostSink", "EventSink",
    "InMemoryTagResolver", "StaticCredentialBroker", "NullCostSink",
    "NullEventSink", "CollectingEventSink",
]
