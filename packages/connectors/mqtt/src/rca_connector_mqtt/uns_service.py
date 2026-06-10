"""Background UNS ingest: a paho Sparkplug B subscriber that fills SubscriptionState.

This is the streaming half of the connector (the background-ingest + read-tools shape
locked for the run). A long-lived paho client subscribes to the Sparkplug B namespace;
on each message it decodes the payload and updates shared `SubscriptionState`:

  * (N|D)BIRTH declares metric ``name`` <-> ``alias`` -> recorded in ``state.metadata``
    so subsequent alias-only DDATA can be resolved. BIRTH is retained by the publisher,
    so a subscriber that joins mid-stream still learns the aliases (survives restart).
  * DDATA carries alias-only values -> resolved to names, written to
    ``state.current_values`` (latest per metric) and appended to ``state.recent``.

The wire/decode work is in ``handle_message`` — a pure function of (topic, bytes) that
mutates the injected state — so the whole decode + namespace-building logic is testable
without a broker. paho's own auto-reconnect keeps the subscription alive across drops;
retained BIRTH re-delivers the aliases on reconnect.

Assumes a single group/node (matches the reference-plant UNS edge); the namespace tree
is keyed by device. Product code never imports rca_simulator (ADR-0012).

Known limitations (deliberate for the MVP; reviewed, accepted):
- Only *device*-scoped metric aliases (DBIRTH) are tracked. Node-level metric declarations
  (NBIRTH with named metrics) are not stored, so node-scoped NDATA would not alias-resolve.
  The reference UNS edge publishes metrics via DBIRTH, so this path is unused here.
- Alias-only DDATA that arrives *before* its DBIRTH cannot be resolved (name unknown yet), so
  it lands in `recent` with name=None and is not written to current_values. Retained BIRTH
  makes this rare in practice (a late subscriber still receives the retained DBIRTH first).
- Only numeric (INT/FLOAT/DOUBLE) metric values are surfaced as floats; boolean/string metrics
  decode but carry value=None (the UNS metrics of interest are numeric).
- Sparkplug `seq` is recorded but not validated for gaps/ordering (no reordering or loss detection).
"""
from __future__ import annotations

import logging
from typing import Any

from rca_connector_sdk import EventSink, NullEventSink, SubscriptionState

from .sparkplug import decode_payload

_log = logging.getLogger("rca_connector_mqtt.uns")


def parse_topic(topic: str) -> dict[str, str] | None:
    """Parse a Sparkplug B topic ``spBv1.0/{group}/{msgtype}/{node}[/{device}]``.

    Returns None for anything that isn't a Sparkplug B topic of the expected shape.
    """
    parts = topic.split("/")
    if len(parts) < 4 or parts[0] != "spBv1.0":
        return None
    out = {"group": parts[1], "msgtype": parts[2], "node": parts[3]}
    if len(parts) >= 5:
        out["device"] = parts[4]
    return out


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):           # bool is an int subclass — exclude it
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class UnsService:
    def __init__(
        self,
        *,
        broker_host: str,
        broker_port: int = 1883,
        state: SubscriptionState,
        group_id: str = "SITE-DEMO",
        event_sink: EventSink | None = None,
        client_id: str = "rca-uns-connector",
        recent_msgtypes: tuple[str, ...] = ("DDATA", "DBIRTH"),
    ) -> None:
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.state = state
        self.group_id = group_id
        self.event_sink = event_sink or NullEventSink()
        self.client_id = client_id
        self.recent_msgtypes = recent_msgtypes
        self.topic_filter = f"spBv1.0/{group_id}/#"
        self._client: Any = None

    # ---- pure decode/ingest (no broker; unit-testable) ----

    def handle_message(self, topic: str, payload_bytes: bytes) -> None:
        info = parse_topic(topic)
        if info is None:
            return
        payload = decode_payload(payload_bytes)
        group, node, msgtype = info["group"], info["node"], info.get("msgtype", "")
        device = info.get("device")
        state = self.state
        state.metadata["group_id"] = group
        state.metadata["node_id"] = node

        # device-scoped alias map: {device: {alias: name}}
        alias_maps: dict[str, dict[int, str]] = state.metadata.setdefault("aliases", {})
        aliases = alias_maps.setdefault(device, {}) if device is not None else {}

        msg_metrics: list[dict[str, Any]] = []
        for m in payload.metrics:
            # BIRTH declares name+alias; learn the mapping and surface an alias candidate.
            if m.name is not None and m.alias is not None and device is not None:
                aliases[m.alias] = m.name
                self.event_sink.emit(
                    {"source": "mqtt", "raw_tag": f"{device}/{m.name}", "alias": m.alias}
                )
            name = m.name if m.name is not None else aliases.get(m.alias) if m.alias is not None else None
            value = _as_float(m.value)
            ts_ms = m.timestamp_ms if m.timestamp_ms is not None else payload.timestamp_ms
            if name is not None and device is not None and msgtype in ("DDATA", "DBIRTH"):
                state.current_values[f"{device}/{name}"] = {
                    "value": value, "alias": m.alias, "timestamp_ms": ts_ms,
                }
            msg_metrics.append({"name": name, "alias": m.alias, "value": value})

        if msgtype in self.recent_msgtypes:
            state.recent.append({
                "topic": topic, "group_id": group, "node_id": node, "device_id": device,
                "msgtype": msgtype, "seq": payload.seq, "timestamp_ms": payload.timestamp_ms,
                "metrics": msg_metrics,
            })

    # ---- paho wiring (live broker) ----

    def _on_connect(self, client: Any, userdata: Any, flags: Any,
                    reason_code: Any, properties: Any = None) -> None:
        client.subscribe(self.topic_filter)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            self.handle_message(msg.topic, msg.payload)
        except Exception as exc:  # noqa: BLE001 — one bad frame must not kill the subscription
            _log.warning("dropping unparseable UNS message on %s (%s: %s)",
                         msg.topic, type(exc).__name__, exc)

    def start(self) -> None:
        """Connect to the broker and begin filling state in a background thread."""
        if self._client is not None:                # guard: don't leak the first client/loop
            raise RuntimeError("UnsService already started")
        import paho.mqtt.client as mqtt

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id, clean_session=True,
        )
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)   # auto-reconnect on drop
        try:
            client.connect(self.broker_host, self.broker_port)
            client.loop_start()
        except Exception:                           # connect/loop failed -> release the socket+thread
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:  # noqa: BLE001 — best-effort cleanup; re-raise the original error
                pass
            raise
        self._client = client

    def stop(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None


__all__ = ["UnsService", "parse_topic"]
