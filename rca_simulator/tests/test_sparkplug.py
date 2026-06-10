"""S2.7 — Sparkplug B payload codec tests (pure, no broker).

Field numbers follow the Eclipse Tahu sparkplug_b.proto so the bytes are
wire-compatible with a real Sparkplug B client.
"""
from rca_simulator.mqtt.sparkplug import (
    DataType,
    Metric,
    Payload,
    decode_payload,
    encode_payload,
)


def test_double_metric_round_trips_exactly():
    p = Payload(timestamp_ms=1_700_000_000_000, seq=0, metrics=[
        Metric(name="discharge_pressure", alias=1, datatype=DataType.DOUBLE, value=1449.5),
    ])
    out = decode_payload(encode_payload(p))
    assert out.timestamp_ms == p.timestamp_ms
    assert out.seq == 0
    m = out.metrics[0]
    assert m.name == "discharge_pressure"
    assert m.alias == 1
    assert m.datatype == DataType.DOUBLE
    assert m.value == 1449.5            # IEEE-754 double round-trips exactly


def test_boolean_and_string_and_long_metrics_round_trip():
    p = Payload(timestamp_ms=42, seq=7, metrics=[
        Metric(name="online", alias=None, datatype=DataType.BOOLEAN, value=True),
        Metric(name="label", alias=None, datatype=DataType.STRING, value="P-101A"),
        Metric(name="bdSeq", alias=None, datatype=DataType.INT64, value=12345),
    ])
    out = decode_payload(encode_payload(p))
    assert [(m.name, m.datatype, m.value) for m in out.metrics] == [
        ("online", DataType.BOOLEAN, True),
        ("label", DataType.STRING, "P-101A"),
        ("bdSeq", DataType.INT64, 12345),
    ]


def test_alias_only_metric_omits_name():
    # DDATA metrics carry alias but no name — the subscriber resolves via BIRTH.
    p = Payload(timestamp_ms=1, seq=3, metrics=[
        Metric(name=None, alias=9, datatype=DataType.DOUBLE, value=2.5),
    ])
    out = decode_payload(encode_payload(p))
    assert out.metrics[0].name is None
    assert out.metrics[0].alias == 9
    assert out.metrics[0].value == 2.5


def test_seq_preserved_across_range():
    for seq in (0, 1, 127, 255):
        out = decode_payload(encode_payload(Payload(timestamp_ms=0, seq=seq, metrics=[])))
        assert out.seq == seq


def test_encoding_is_deterministic():
    p = Payload(timestamp_ms=5, seq=2, metrics=[
        Metric(name="x", alias=1, datatype=DataType.DOUBLE, value=3.14),
    ])
    assert encode_payload(p) == encode_payload(p)
