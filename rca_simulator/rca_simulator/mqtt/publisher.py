"""S2.7 — Sparkplug B publisher driven by the reference-plant fixture.

Models a UNS edge node that publishes the whole plant: one Sparkplug *device* per
asset, one *metric* per signal. On birth it declares metric names + aliases
(NBIRTH then a DBIRTH per device); thereafter DDATA messages carry alias-only
values sampled from the scenario expander at ~1 Hz, with monotonically increasing
``seq`` (wrapping at 256, per spec).

The MQTT client is injected (any object with ``publish(topic, payload: bytes)``),
so the publish logic is testable without a broker. ``run()`` wires it to a real
``paho-mqtt`` client + 1 Hz loop. Realism (drops, clock skew) is applied via the
shared S2.8 harness when an injector is supplied.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Protocol

from ..fixtures.schema import RefPlant
from ..fixtures.scenario_expander import value_at
from ..realism.inject import RealismInjector
from .sparkplug import DataType, Metric, Payload, encode_payload

_SEQ_MOD = 256


class MqttClient(Protocol):
    def publish(self, topic: str, payload: bytes, retain: bool = False) -> None: ...


class SparkplugPublisher:
    def __init__(
        self,
        rp: RefPlant,
        scenario_id: str,
        client: MqttClient,
        *,
        group_id: str = "SITE-DEMO",
        node_id: str = "UNS-EDGE-1",
        seed: int = 0,
        realism: RealismInjector | None = None,
    ) -> None:
        self.rp = rp
        self.scenario_id = scenario_id
        self.client = client
        self.group_id = group_id
        self.node_id = node_id
        self.seed = seed
        self.realism = realism
        self._seq = 0

        # devices = assets, in deterministic order; metrics = their signals.
        self.devices: dict[str, list[str]] = {}
        for key in sorted(rp.signals):
            asset = rp.signals[key].asset_ref
            self.devices.setdefault(asset, []).append(key)
        # stable role -> alias per device (unique across the node).
        self.aliases: dict[str, dict[str, int]] = {}
        alias = 1
        for asset, keys in self.devices.items():
            self.aliases[asset] = {}
            for key in keys:
                self.aliases[asset][rp.signals[key].role] = alias
                alias += 1

    # ---- topics & seq ----

    def _node_topic(self, msgtype: str) -> str:
        return f"spBv1.0/{self.group_id}/{msgtype}/{self.node_id}"

    def _device_topic(self, msgtype: str, device: str) -> str:
        return f"spBv1.0/{self.group_id}/{msgtype}/{self.node_id}/{device}"

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) % _SEQ_MOD
        return seq

    def _ts_ms(self, t: datetime) -> int:
        if self.realism is not None:
            t = self.realism.skew_timestamp(t)
        return int(t.timestamp() * 1000)

    def _emit(self, topic: str, payload: Payload, *, retain: bool = False) -> None:
        if self.realism is not None and self.realism.maybe_drop():
            return
        self.client.publish(topic, encode_payload(payload), retain=retain)

    # ---- birth ----

    def publish_birth(self, t: datetime | None = None) -> None:
        """Publish NBIRTH (seq=0) then a DBIRTH per device declaring aliases."""
        when = t if t is not None else self.rp.scenarios[self.scenario_id].t0
        self._seq = 0
        ts = self._ts_ms(when)
        # NBIRTH must use seq 0 and reset the sequence.
        nbirth = Payload(timestamp_ms=ts, seq=self._next_seq(), metrics=[
            Metric(name="bdSeq", datatype=DataType.INT64, value=0),
        ])
        # BIRTH is retained so a connector/subscriber that joins mid-stream still
        # receives metric names + aliases (needed to decode alias-only DDATA).
        self._emit(self._node_topic("NBIRTH"), nbirth, retain=True)
        for device, keys in self.devices.items():
            metrics = [
                Metric(
                    name=self.rp.signals[key].role,
                    alias=self.aliases[device][self.rp.signals[key].role],
                    datatype=DataType.DOUBLE,
                    value=value_at(self.rp, self.scenario_id, key, when, seed=self.seed),
                    timestamp_ms=ts,
                )
                for key in keys
            ]
            self._emit(
                self._device_topic("DBIRTH", device),
                Payload(timestamp_ms=ts, seq=self._next_seq(), metrics=metrics),
                retain=True,
            )

    # ---- data ----

    def publish_tick(self, t: datetime) -> None:
        """Publish one DDATA per device with alias-only metric values at ``t``."""
        ts = self._ts_ms(t)
        for device, keys in self.devices.items():
            metrics = [
                Metric(
                    alias=self.aliases[device][self.rp.signals[key].role],
                    datatype=DataType.DOUBLE,
                    value=value_at(self.rp, self.scenario_id, key, t, seed=self.seed),
                    timestamp_ms=ts,
                )
                for key in keys
            ]
            self._emit(
                self._device_topic("DDATA", device),
                Payload(timestamp_ms=ts, seq=self._next_seq(), metrics=metrics),
            )

    # ---- live loop ----

    def run(self, start: datetime, end: datetime, step_seconds: float = 1.0,
            realtime: bool = True) -> None:
        """Birth, then stream DDATA from ``start`` to ``end`` at ``step_seconds``."""
        self.publish_birth(start)
        t = start
        while t < end:
            self.publish_tick(t)
            if realtime:
                time.sleep(step_seconds)
            t += timedelta(seconds=step_seconds)


class PahoClientAdapter:
    """Thin adapter exposing ``publish(topic, payload)`` over a connected paho client.

    Untested here (needs a live broker); exercised by the connector↔simulator
    integration tests in EPIC-013 and the docker-compose smoke test.
    """

    def __init__(self, host: str, port: int = 1883, client_id: str = "rca-uns-sim") -> None:
        import paho.mqtt.client as mqtt  # lazy: keep import off the unit-test path

        self._client = mqtt.Client(client_id=client_id)
        self._client.connect(host, port)
        self._client.loop_start()

    def publish(self, topic: str, payload: bytes, retain: bool = False) -> None:
        self._client.publish(topic, payload, retain=retain)


def main() -> None:
    """CLI entrypoint used by the Docker image / docker-compose."""
    import os

    from ..fixtures.loader import load
    from ..realism.config import RealismConfig

    fixture_path = os.environ.get("FIXTURE_PATH", "fixtures/refplant")
    scenario = os.environ.get("SCENARIO", "seal_leak_progression")
    broker = os.environ.get("MQTT_BROKER", "localhost:1883")
    host, _, port = broker.partition(":")

    rp = load(fixture_path)
    client = PahoClientAdapter(host, int(port or 1883))
    pub = SparkplugPublisher(
        rp, scenario, client=client,
        realism=RealismInjector(RealismConfig.from_env()),
    )
    sc = rp.scenarios[scenario]
    end = sc.t0 + timedelta(days=sc.duration_days)
    pub.run(sc.t0, end, step_seconds=1.0, realtime=True)


if __name__ == "__main__":
    main()


__all__ = ["SparkplugPublisher", "MqttClient", "PahoClientAdapter", "main"]
