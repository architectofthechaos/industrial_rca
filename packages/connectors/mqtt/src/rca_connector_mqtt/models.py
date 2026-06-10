"""Connector-local response models for the UNS read tools.

These are MQTT/UNS-shaped views (a discovered namespace tree + recent decoded
messages), not canonical evidence contracts, so they live with the connector
rather than in `rca_contracts`. Plain (non-strict) models so the parity test can
round-trip them from JSON (ISO strings -> datetime) through `ToolResponse[T]`.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MetricSnapshot(BaseModel):
    """One UNS metric and its latest value (from BIRTH alias + DDATA)."""

    name: str
    alias: int | None = None
    value: float | None = None
    timestamp: datetime | None = None


class DeviceSnapshot(BaseModel):
    device_id: str
    metrics: list[MetricSnapshot]


class NamespaceTree(BaseModel):
    """The discovered UNS namespace (group -> node -> devices -> metrics)."""

    group_id: str
    node_id: str
    devices: list[DeviceSnapshot]


class UnsMessageMetric(BaseModel):
    name: str | None = None
    alias: int | None = None
    value: float | None = None


class UnsMessage(BaseModel):
    topic: str
    group_id: str
    node_id: str
    device_id: str | None = None
    msgtype: str
    seq: int
    timestamp: datetime | None = None      # None when the source frame carried no timestamp
    metrics: list[UnsMessageMetric]


class RecentMessages(BaseModel):
    messages: list[UnsMessage]


__all__ = [
    "MetricSnapshot",
    "DeviceSnapshot",
    "NamespaceTree",
    "UnsMessageMetric",
    "UnsMessage",
    "RecentMessages",
]
