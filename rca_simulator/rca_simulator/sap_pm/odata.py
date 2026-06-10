"""S2.4 — minimal SAP OData v2 query surface + metadata.

Supports the ``$filter`` / ``$select`` subset the connector uses and serializes
responses in the OData v2 envelope (``{"d": {"results": [...]}}``). ``$metadata``
returns a small EDMX document with a namespaced Notification entity type.
"""
from __future__ import annotations

import re
from typing import Any

Condition = tuple[str, str, str]

_TERM = re.compile(r"\s*(\w+)\s+(eq|ne|gt|lt|ge|le)\s+'?([^']*)'?\s*")
_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "ge": lambda a, b: a >= b,
    "le": lambda a, b: a <= b,
}

NAMESPACE = "RCA.PM"


def parse_filter(expr: str | None) -> list[Condition]:
    if not expr:
        return []
    conds: list[Condition] = []
    for term in re.split(r"\s+and\s+", expr, flags=re.IGNORECASE):
        m = _TERM.fullmatch(term)
        if m:
            conds.append((m.group(1), m.group(2), m.group(3)))
    return conds


def apply_filter(records: list[dict[str, Any]], conds: list[Condition]) -> list[dict[str, Any]]:
    return [
        rec for rec in records
        if all(field in rec and _OPS[op](str(rec[field]), value)
               for field, op, value in conds)
    ]


def apply_select(records: list[dict[str, Any]], select: str | None) -> list[dict[str, Any]]:
    if not select:
        return records
    fields = [f.strip() for f in select.split(",") if f.strip()]
    return [{k: rec[k] for k in fields if k in rec} for rec in records]


def odata_collection(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"d": {"results": records}}


def odata_entity(record: dict[str, Any]) -> dict[str, Any]:
    return {"d": record}


_PROPERTIES = [
    ("QMNUM", "Edm.String"), ("EQUNR", "Edm.String"), ("QMTXT", "Edm.String"),
    ("QMART", "Edm.String"), ("PRIOK", "Edm.String"), ("FECOD", "Edm.String"),
    ("AUSVN", "Edm.String"),
]


def metadata_xml() -> str:
    props = "\n".join(
        f'        <Property Name="{name}" Type="{typ}"/>' for name, typ in _PROPERTIES
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
    <Schema Namespace="{NAMESPACE}" xmlns="http://schemas.microsoft.com/ado/2008/09/edm">
      <EntityType Name="Notification">
        <Key><PropertyRef Name="QMNUM"/></Key>
{props}
      </EntityType>
      <EntityContainer Name="PM_NOTIFICATION_SRV" m:IsDefaultEntityContainer="true">
        <EntitySet Name="NotificationSet" EntityType="{NAMESPACE}.Notification"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""


__all__ = [
    "Condition", "NAMESPACE", "parse_filter", "apply_filter", "apply_select",
    "odata_collection", "odata_entity", "metadata_xml",
]
