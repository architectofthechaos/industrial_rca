"""S13.7 MQTT/UNS connector — hermetic tests (no broker).

Drives the pure decode/ingest path with self-built Sparkplug B payloads, then
exercises the read tools through the real FastMCP boundary against the populated
cache. No broker, no rca_simulator import.
"""
import json

import pytest
from fastmcp import Client as McpClient
from rca_connector_sdk import CollectingEventSink, SubscriptionState
from rca_contracts import ToolResponse

from rca_connector_mqtt.models import NamespaceTree, RecentMessages
from rca_connector_mqtt.server import make_mqtt_mcp
from rca_connector_mqtt.sparkplug import (
    DataType,
    Metric,
    Payload,
    _encode_metric,
    _field_len,
    _field_varint,
    decode_payload,
    encode_payload,
)
from rca_connector_mqtt.uns_service import UnsService, parse_topic

GROUP = "SITE-DEMO"
NODE = "UNS-EDGE-1"
DEVICE = "P-101A"


def _dbirth_bytes() -> bytes:
    return encode_payload(Payload(timestamp_ms=1_700_000_000_000, seq=1, metrics=[
        Metric(name="discharge_pressure", alias=1, datatype=DataType.DOUBLE,
               value=14.5, timestamp_ms=1_700_000_000_000),
        Metric(name="suction_pressure", alias=2, datatype=DataType.DOUBLE,
               value=2.0, timestamp_ms=1_700_000_000_000),
    ]))


def _ddata_bytes(p1: float, p2: float, ts: int) -> bytes:
    # alias-only, like a real DDATA frame
    return encode_payload(Payload(timestamp_ms=ts, seq=2, metrics=[
        Metric(alias=1, datatype=DataType.DOUBLE, value=p1, timestamp_ms=ts),
        Metric(alias=2, datatype=DataType.DOUBLE, value=p2, timestamp_ms=ts),
    ]))


def test_sparkplug_roundtrip():
    payload = decode_payload(_dbirth_bytes())
    assert payload.seq == 1
    by_alias = {m.alias: m for m in payload.metrics}
    assert by_alias[1].name == "discharge_pressure" and by_alias[1].value == 14.5


def test_parse_topic():
    assert parse_topic(f"spBv1.0/{GROUP}/DDATA/{NODE}/{DEVICE}") == {
        "group": GROUP, "msgtype": "DDATA", "node": NODE, "device": DEVICE,
    }
    assert parse_topic(f"spBv1.0/{GROUP}/NBIRTH/{NODE}") == {
        "group": GROUP, "msgtype": "NBIRTH", "node": NODE,   # node-level: no device
    }
    assert parse_topic("not/sparkplug") is None


def test_handle_message_learns_aliases_and_resolves_ddata():
    state = SubscriptionState()
    sink = CollectingEventSink()
    svc = UnsService(broker_host="x", state=state, group_id=GROUP, event_sink=sink)

    svc.handle_message(f"spBv1.0/{GROUP}/DBIRTH/{NODE}/{DEVICE}", _dbirth_bytes())
    # BIRTH learned the alias map and emitted alias candidates (raw tags) for MAR.
    assert state.metadata["aliases"][DEVICE] == {1: "discharge_pressure", 2: "suction_pressure"}
    assert any(e["raw_tag"] == f"{DEVICE}/discharge_pressure" for e in sink.events)

    svc.handle_message(f"spBv1.0/{GROUP}/DDATA/{NODE}/{DEVICE}", _ddata_bytes(15.1, 2.1, 1_700_000_001_000))
    # alias-only DDATA resolved to names against the learned map.
    assert state.current_values[f"{DEVICE}/discharge_pressure"]["value"] == 15.1
    assert state.current_values[f"{DEVICE}/suction_pressure"]["value"] == 2.1
    assert len(state.recent) == 2  # DBIRTH + DDATA recorded


def _populated_state() -> SubscriptionState:
    state = SubscriptionState()
    svc = UnsService(broker_host="x", state=state, group_id=GROUP)
    svc.handle_message(f"spBv1.0/{GROUP}/DBIRTH/{NODE}/{DEVICE}", _dbirth_bytes())
    svc.handle_message(f"spBv1.0/{GROUP}/DDATA/{NODE}/{DEVICE}", _ddata_bytes(15.1, 2.1, 1_700_000_001_000))
    return state


async def test_browse_namespace_through_mcp():
    mcp = make_mqtt_mcp(state=_populated_state())
    async with McpClient(mcp) as client:
        res = await client.call_tool("uns.browse_namespace", {"request": {}})
        payload = res.structured_content if res.structured_content is not None else res.data
        resp = ToolResponse[NamespaceTree].model_validate_json(json.dumps(payload))
        assert resp.error is None, resp.error
        assert resp.provenance.record_count == 2
        tree = resp.data
        assert tree.group_id == GROUP and tree.node_id == NODE
        dev = next(d for d in tree.devices if d.device_id == DEVICE)
        dp = next(m for m in dev.metrics if m.name == "discharge_pressure")
        assert dp.alias == 1 and dp.value == 15.1 and dp.timestamp is not None


async def test_get_recent_messages_through_mcp():
    mcp = make_mqtt_mcp(state=_populated_state())
    async with McpClient(mcp) as client:
        res = await client.call_tool(
            "uns.get_recent_messages", {"request": {"device_id": DEVICE, "limit": 10}}
        )
        payload = res.structured_content if res.structured_content is not None else res.data
        resp = ToolResponse[RecentMessages].model_validate_json(json.dumps(payload))
        assert resp.error is None, resp.error
        assert resp.provenance.record_count == len(resp.data.messages) == 2
        last = resp.data.messages[-1]
        assert last.msgtype == "DDATA" and last.device_id == DEVICE
        assert last.timestamp.tzinfo is not None


# ---- codec robustness (adversarial-review fixes) ----

def test_truncated_frame_raises_not_corrupts():
    # A frame truncated mid-field must raise (caught upstream + dropped), never silently
    # decode partial/corrupt data.
    good = _dbirth_bytes()
    with pytest.raises(ValueError):
        decode_payload(good[:-3])          # chop the tail -> truncated field


def test_truncated_varint_raises():
    with pytest.raises(ValueError):
        decode_payload(b"\x08\x80")         # field 1 varint with continuation bit, no next byte


def test_one_bad_metric_does_not_drop_siblings():
    good = _encode_metric(Metric(name="discharge_pressure", alias=1,
                                 datatype=DataType.DOUBLE, value=1.0))
    bad = _encode_metric(Metric(name="suction_pressure", alias=2,
                                datatype=DataType.DOUBLE, value=2.0))[:-4]  # chop the double
    buf = (_field_varint(1, 1_700_000_000_000)
           + _field_len(2, good) + _field_len(2, bad)
           + _field_varint(3, 1))
    payload = decode_payload(buf)
    # the malformed metric is skipped; its valid sibling still decodes.
    assert [m.alias for m in payload.metrics] == [1]
    assert payload.metrics[0].value == 1.0


# ---- hand-wired tool invariants (adversarial-review fixes) ----

async def test_empty_cache_returns_empty_with_provenance():
    mcp = make_mqtt_mcp(state=SubscriptionState())     # nothing ingested yet
    async with McpClient(mcp) as client:
        for tool, model in (("uns.browse_namespace", NamespaceTree),
                            ("uns.get_recent_messages", RecentMessages)):
            res = await client.call_tool(tool, {"request": {}})
            payload = res.structured_content if res.structured_content is not None else res.data
            resp = ToolResponse[model].model_validate_json(json.dumps(payload))
            assert resp.error is None, resp.error      # empty is success, not error
            assert resp.provenance is not None and resp.provenance.record_count == 0


async def test_tool_exception_maps_to_toolerror():
    # A malformed cache row (missing required key) must surface as a ToolError, not a raw raise.
    state = SubscriptionState()
    state.recent.append({"device_id": DEVICE})         # missing topic/group_id/... -> KeyError
    mcp = make_mqtt_mcp(state=state)
    async with McpClient(mcp) as client:
        res = await client.call_tool("uns.get_recent_messages", {"request": {}})
        payload = res.structured_content if res.structured_content is not None else res.data
        resp = ToolResponse[RecentMessages].model_validate_json(json.dumps(payload))
        assert resp.error is not None and resp.data is None      # mapped, not leaked
