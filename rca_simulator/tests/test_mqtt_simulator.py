"""S2.7 — Sparkplug B publisher tests (no broker; client is injected).

Verifies BIRTH-before-DATA, seq sequencing/wrap, alias declaration in BIRTH and
alias-only DATA, scenario tracking, and realism integration (drops).
"""
from datetime import timedelta
from pathlib import Path

from rca_simulator.fixtures.loader import load
from rca_simulator.fixtures.scenario_expander import value_at
from rca_simulator.mqtt.sparkplug import decode_payload
from rca_simulator.mqtt.publisher import SparkplugPublisher
from rca_simulator.realism.config import RealismConfig
from rca_simulator.realism.inject import RealismInjector

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"
SCENARIO = "seal_leak_progression"


class FakeClient:
    def __init__(self):
        self.messages: list[tuple[str, bytes]] = []
        self.retained: list[str] = []

    def publish(self, topic: str, payload: bytes, retain: bool = False) -> None:
        self.messages.append((topic, payload))
        if retain:
            self.retained.append(topic)


def make():
    rp = load(REFPLANT)
    client = FakeClient()
    pub = SparkplugPublisher(rp, SCENARIO, client=client,
                             group_id="SITE-DEMO", node_id="UNS-EDGE-1")
    return rp, client, pub


def msgtype(topic: str) -> str:
    return topic.split("/")[2]


def test_birth_publishes_nbirth_then_one_dbirth_per_asset():
    rp, client, pub = make()
    pub.publish_birth()
    types = [msgtype(t) for t, _ in client.messages]
    assert types[0] == "NBIRTH"
    assert types.count("DBIRTH") == len(rp.assets)
    assert client.messages[0][0] == "spBv1.0/SITE-DEMO/NBIRTH/UNS-EDGE-1"


def test_nbirth_seq_zero_then_monotonic():
    _, client, pub = make()
    pub.publish_birth()
    seqs = [decode_payload(p).seq for _, p in client.messages]
    assert seqs[0] == 0
    assert seqs == list(range(len(seqs)))   # 0,1,2,... across births


def test_dbirth_declares_named_aliased_metrics():
    rp, client, pub = make()
    pub.publish_birth()
    dbirth = next(p for t, p in client.messages
                  if t == "spBv1.0/SITE-DEMO/DBIRTH/UNS-EDGE-1/P-101A")
    metrics = decode_payload(dbirth).metrics
    roles = {m.name for m in metrics}
    assert "discharge_pressure" in roles and "seal_flush_flow" in roles
    assert all(m.alias is not None for m in metrics)   # BIRTH declares aliases


def test_ddata_uses_alias_only_and_subscriber_resolves_via_birth():
    rp, client, pub = make()
    pub.publish_birth()
    dbirth = next(p for t, p in client.messages
                  if t.endswith("/DBIRTH/UNS-EDGE-1/P-101A"))
    alias_to_role = {m.alias: m.name for m in decode_payload(dbirth).metrics}

    client.messages.clear()
    t = rp.scenarios[SCENARIO].t0 + timedelta(days=20)
    pub.publish_tick(t)

    ddata = next(p for top, p in client.messages
                 if top == "spBv1.0/SITE-DEMO/DDATA/UNS-EDGE-1/P-101A")
    metrics = decode_payload(ddata).metrics
    assert all(m.name is None for m in metrics)         # DATA carries alias, not name
    by_role = {alias_to_role[m.alias]: m.value for m in metrics}
    assert by_role["discharge_pressure"] == value_at(rp, SCENARIO, "P-101A.discharge_pressure", t)


def test_seq_continues_across_ticks_and_wraps_at_256():
    rp, client, pub = make()
    pub.publish_birth()
    t0 = rp.scenarios[SCENARIO].t0
    for i in range(120):                                  # many ticks -> seq wraps
        pub.publish_tick(t0 + timedelta(seconds=i))
    seqs = [decode_payload(p).seq for _, p in client.messages]
    assert all(0 <= s <= 255 for s in seqs)
    assert 0 in seqs[1:]                                  # wrapped back through 0


def test_birth_is_retained_so_late_subscribers_get_aliases():
    rp, client, pub = make()
    pub.publish_birth()
    birth_topics = [t for t, _ in client.messages]
    assert birth_topics                                  # NBIRTH + DBIRTHs
    assert all(t in client.retained for t in birth_topics)   # all births retained

    client.messages.clear()
    client.retained.clear()
    pub.publish_tick(rp.scenarios[SCENARIO].t0)
    assert client.retained == []                         # DATA must NOT be retained


def test_realism_drop_rate_one_suppresses_data():
    rp, _, _ = make()
    client = FakeClient()
    drop_all = RealismInjector(RealismConfig(drop_rate=1.0), seed=1)
    pub = SparkplugPublisher(rp, SCENARIO, client=client, realism=drop_all)
    pub.publish_tick(rp.scenarios[SCENARIO].t0)
    assert client.messages == []                         # everything dropped
