"""@evidence_tool — the hybrid orchestrator for request/response connector tools.

A connector implements `fetch()` (source call) and `translate()` (raw → the canonical
response model). The orchestrator runs everything else generically and guarantees the
universal invariants by construction: resolve signal + source binding → credentials →
fetch (retry) → translate → require+attach Provenance → record cost → map any failure
to a ToolError. The result is always a ToolResponse[T]: data+provenance on success,
error on failure, never both.

Series tools build their response with `build_measurement_series` (unit/time normalization
lives there); non-series tools build their own canonical model. Either way the orchestrator
enforces provenance + the envelope + error mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4

from rca_contracts import ToolResponse

from .context import ToolContext, ToolDeps
from .errors import map_source_error
from .provenance import ProvenanceAccumulator
from .retry import with_retry


@dataclass(frozen=True)
class EvidenceToolMeta:
    name: str
    version: str
    source: str
    request: type
    response: type
    mutating: bool = False        # marks write tools (e.g. CMMS write-back); a label only —
                                  # tier-gating / HITL will consume it later (not yet enforced here)


class EvidenceTool:
    """Wraps a connector's fetch/translate class with its metadata."""

    def __init__(self, impl_cls: type, meta: EvidenceToolMeta) -> None:
        self._impl_cls = impl_cls
        self.meta = meta

    def bind(self, deps: ToolDeps) -> Callable[[Any], Awaitable[ToolResponse]]:
        """Return an async callable `(request) -> ToolResponse[response]` ready to register."""
        impl = self._impl_cls()
        meta = self.meta

        async def run(req: Any) -> ToolResponse:
            prov = ProvenanceAccumulator()
            queried_at = datetime.now(timezone.utc)
            response_id = uuid4()
            envelope: Any = ToolResponse[meta.response]  # type: ignore[name-defined]
            try:
                # tag/signal-scoped tools carry signal_id (or entity_id); asset-scoped tools
                # (work orders, notifications) carry asset_id; query-scoped tools
                # (documents.search) carry neither. Resolve a TagDescriptor only for tag-scoped
                # requests, and a source binding only when the request names a primary entity.
                signal_id = getattr(req, "signal_id", None)
                tag_entity_id = signal_id if signal_id is not None else getattr(req, "entity_id", None)
                entity_id = tag_entity_id if tag_entity_id is not None else getattr(req, "asset_id", None)
                tag = (await deps.tag_resolver.resolve(tag_entity_id)
                       if tag_entity_id is not None else None)
                source = (await deps.tag_resolver.source_binding(entity_id, meta.source)
                          if entity_id is not None else None)
                credential = await deps.credential_broker.get(deps.config.credential_ref)
                ctx = ToolContext(request=req, config=deps.config, tag=tag, source=source,
                                  source_name=meta.source, prov=prov, credential=credential,
                                  http=deps.http_client)

                raw = await with_retry(lambda: impl.fetch(ctx, req),
                                       attempts=deps.config.retry_attempts)
                data = impl.translate(ctx, raw)          # the canonical response model

                provenance = prov.build(
                    tool_name=meta.name, tool_version=meta.version, source=meta.source,
                    queried_at=queried_at, response_id=response_id,
                )
                deps.cost_sink.record(tool=meta.name, source=meta.source,
                                      record_count=provenance.record_count)
                return envelope.ok(data, provenance)
            except Exception as exc:  # noqa: BLE001 — boundary: every failure becomes a ToolError
                return envelope.fail(map_source_error(exc))

        run.__name__ = meta.name.replace(".", "_")
        return run


def evidence_tool(*, name: str, version: str, source: str, request: type, response: type,
                  mutating: bool = False) -> Callable[[type], EvidenceTool]:
    """Class decorator turning a fetch/translate class into a registrable EvidenceTool."""
    def wrap(impl_cls: type) -> EvidenceTool:
        return EvidenceTool(impl_cls, EvidenceToolMeta(
            name=name, version=version, source=source, request=request, response=response,
            mutating=mutating,
        ))
    return wrap


__all__ = ["evidence_tool", "EvidenceTool", "EvidenceToolMeta"]
