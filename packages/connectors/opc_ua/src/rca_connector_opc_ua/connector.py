"""OPC UA connector tool (S13.5): opc_ua.get_current_values (on-demand read)."""
from __future__ import annotations

from datetime import datetime, timezone

from asyncua import Client, ua
from pydantic import BaseModel
from rca_connector_sdk import SourceBinding, SourceUnavailable, evidence_tool, to_si
from rca_contracts import Measurement, SignalDescriptor, SignalID


class GetCurrentValueRequest(BaseModel):
    signal_id: SignalID


def to_measurement(signal: SignalDescriptor, source: SourceBinding, raw: float) -> Measurement:
    """Map a raw OPC UA value to a canonical Measurement (unit-normalized). Module-level
    so it's unit-testable without standing up a server."""
    return Measurement(
        signal_id=signal.signal_id,
        timestamp=datetime.now(timezone.utc),    # current-value read time
        value=to_si(raw, source.raw_unit, signal.qudt_unit, signal.pressure_reference),
        quality="good",
        is_interpolated=False,
    )


@evidence_tool(name="opc_ua.get_current_values", version="0.1.0", source="opc_ua",
               request=GetCurrentValueRequest, response=Measurement)
class OpcUaCurrentValue:
    async def fetch(self, ctx, req: GetCurrentValueRequest):
        endpoint = ctx.config.endpoint
        ns_uri = ctx.config.extra.get("namespace_uri", "")
        handle = ctx.source.handle               # NodeId string identifier (= signal key)
        try:
            async with Client(endpoint) as client:
                idx = await client.get_namespace_index(ns_uri)
                node = client.get_node(ua.NodeId(handle, idx))  # type: ignore[arg-type]
                value = await node.read_value()
        except Exception as exc:                  # asyncua / socket errors -> retryable source error
            raise SourceUnavailable(f"OPC UA read failed for {handle}: {exc}") from exc
        ctx.prov.record(source_query=f"opc.tcp read {handle}", raw_tags=[handle], record_count=1)
        return float(value)

    def translate(self, ctx, raw) -> Measurement:
        return to_measurement(ctx.signal, ctx.source, raw)


__all__ = ["GetCurrentValueRequest", "OpcUaCurrentValue", "to_measurement"]
