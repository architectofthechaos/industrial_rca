"""Connector-local Sparkplug B codec (Eclipse Tahu wire format).

This is the connector's OWN protobuf (de)serializer for the subset of
``sparkplug_b.proto`` the UNS edge publishes. It is intentionally self-contained:
product connectors never import ``rca_simulator`` (ADR-0012), so the wire format
lives here too. Field numbers match Tahu, so these bytes are interoperable with any
real Sparkplug B publisher — not just our simulator.

Tahu reference (field numbers):
    Payload:  timestamp=1, metrics=2 (repeated Metric), seq=3
    Metric:   name=1, alias=2, timestamp=3, datatype=4,
              int_value=10, long_value=11, float_value=12, double_value=13,
              boolean_value=14, string_value=15
"""
from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class DataType(IntEnum):
    """Subset of Sparkplug B metric data types (Tahu enum values)."""

    INT64 = 4
    FLOAT = 9
    DOUBLE = 10
    BOOLEAN = 11
    STRING = 12


# protobuf wire types
_WIRE_VARINT = 0
_WIRE_64BIT = 1
_WIRE_LEN = 2
_WIRE_32BIT = 5


@dataclass
class Metric:
    datatype: DataType
    value: Any
    name: str | None = None
    alias: int | None = None
    timestamp_ms: int | None = None


@dataclass
class Payload:
    timestamp_ms: int
    seq: int
    metrics: list[Metric] = field(default_factory=list)


# ---------- low-level encoders (used by tests to build payloads) ----------

def _varint(n: int) -> bytes:
    if n < 0:
        n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _tag(field_no: int, wire: int) -> bytes:
    return _varint((field_no << 3) | wire)


def _field_varint(field_no: int, value: int) -> bytes:
    return _tag(field_no, _WIRE_VARINT) + _varint(value)


def _field_len(field_no: int, raw: bytes) -> bytes:
    return _tag(field_no, _WIRE_LEN) + _varint(len(raw)) + raw


def _encode_metric_value(m: Metric) -> bytes:
    if m.datatype == DataType.DOUBLE:
        return _tag(13, _WIRE_64BIT) + struct.pack("<d", float(m.value))
    if m.datatype == DataType.FLOAT:
        return _tag(12, _WIRE_32BIT) + struct.pack("<f", float(m.value))
    if m.datatype == DataType.BOOLEAN:
        return _field_varint(14, 1 if m.value else 0)
    if m.datatype == DataType.STRING:
        return _field_len(15, str(m.value).encode("utf-8"))
    if m.datatype == DataType.INT64:
        return _field_varint(11, int(m.value))
    raise ValueError(f"unsupported datatype: {m.datatype!r}")


def _encode_metric(m: Metric) -> bytes:
    out = bytearray()
    if m.name is not None:
        out += _field_len(1, m.name.encode("utf-8"))
    if m.alias is not None:
        out += _field_varint(2, m.alias)
    if m.timestamp_ms is not None:
        out += _field_varint(3, m.timestamp_ms)
    out += _field_varint(4, int(m.datatype))
    out += _encode_metric_value(m)
    return bytes(out)


def encode_payload(payload: Payload) -> bytes:
    out = bytearray()
    out += _field_varint(1, payload.timestamp_ms)
    for m in payload.metrics:
        out += _field_len(2, _encode_metric(m))
    out += _field_varint(3, payload.seq)
    return bytes(out)


# ---------- low-level decoders (the connector's read path) ----------

def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    n = len(buf)
    while True:
        if pos >= n:                       # continuation bit set but no next byte
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7
        if shift > 63:                     # malformed: varint exceeds 64 bits
            raise ValueError("varint too long")


def _iter_fields(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    pos = 0
    n = len(buf)
    val: Any
    while pos < n:
        key, pos = _read_varint(buf, pos)
        field_no, wire = key >> 3, key & 0x07
        if wire == _WIRE_VARINT:
            val, pos = _read_varint(buf, pos)
        elif wire == _WIRE_64BIT:
            if pos + 8 > n:                 # bounds-check: never silently return partial bytes
                raise ValueError("truncated 64-bit field")
            val, pos = buf[pos:pos + 8], pos + 8
        elif wire == _WIRE_32BIT:
            if pos + 4 > n:
                raise ValueError("truncated 32-bit field")
            val, pos = buf[pos:pos + 4], pos + 4
        elif wire == _WIRE_LEN:
            length, pos = _read_varint(buf, pos)
            if pos + length > n:            # else a truncated string/name decodes as corrupt partial data
                raise ValueError("truncated length-delimited field")
            val, pos = buf[pos:pos + length], pos + length
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield field_no, wire, val


def _decode_metric(buf: bytes) -> Metric:
    name: str | None = None
    alias: int | None = None
    ts: int | None = None
    datatype = DataType.DOUBLE
    value: Any = None
    for field_no, _wire, val in _iter_fields(buf):
        if field_no == 1:
            name = val.decode("utf-8")
        elif field_no == 2:
            alias = val
        elif field_no == 3:
            ts = val
        elif field_no == 4:
            datatype = DataType(val)
        elif field_no == 11:           # long_value
            value = val
        elif field_no == 12:           # float_value
            value = struct.unpack("<f", val)[0]
        elif field_no == 13:           # double_value
            value = struct.unpack("<d", val)[0]
        elif field_no == 14:           # boolean_value
            value = bool(val)
        elif field_no == 15:           # string_value
            value = val.decode("utf-8")
    return Metric(datatype=datatype, value=value, name=name, alias=alias, timestamp_ms=ts)


def decode_payload(buf: bytes) -> Payload:
    timestamp_ms = 0
    seq = 0
    metrics: list[Metric] = []
    for field_no, _wire, val in _iter_fields(buf):
        if field_no == 1:
            timestamp_ms = val
        elif field_no == 2:
            # Per-metric resilience: a single malformed metric (bad UTF-8, wrong float
            # width, unknown datatype) is skipped so its valid siblings still decode.
            # Top-level framing errors still propagate (the frame can't be trusted).
            try:
                metrics.append(_decode_metric(val))
            except (ValueError, UnicodeDecodeError, struct.error):
                continue
        elif field_no == 3:
            seq = val
    return Payload(timestamp_ms=timestamp_ms, seq=seq, metrics=metrics)


__all__ = ["DataType", "Metric", "Payload", "encode_payload", "decode_payload"]
