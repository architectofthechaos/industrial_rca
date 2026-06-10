"""S2.3 — minimal Maximo OSLC query surface: oslc.where / oslc.select / paging.

Supports the subset the connector uses: equality and ordered comparisons joined
by ``and``, field projection, and page slicing. Values are compared as strings
(works for ISO dates and Maximo identifiers).
"""
from __future__ import annotations

import re
from typing import Any

Condition = tuple[str, str, str]

_TERM = re.compile(r'\s*(\w+)\s*(>=|<=|!=|>|<|=)\s*"?([^"]*)"?\s*')
_OPS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
}


def parse_where(expr: str | None) -> list[Condition]:
    if not expr:
        return []
    conditions: list[Condition] = []
    for term in re.split(r"\s+and\s+", expr, flags=re.IGNORECASE):
        m = _TERM.fullmatch(term)
        if not m:
            continue
        field, op, value = m.group(1), m.group(2), m.group(3)
        conditions.append((field, op, value))
    return conditions


def apply_where(records: list[dict[str, Any]], conditions: list[Condition]) -> list[dict[str, Any]]:
    out = []
    for rec in records:
        if all(
            field in rec and _OPS[op](str(rec[field]), value)
            for field, op, value in conditions
        ):
            out.append(rec)
    return out


def apply_select(records: list[dict[str, Any]], select: str | None) -> list[dict[str, Any]]:
    if not select:
        return records
    fields = [f.strip() for f in select.split(",") if f.strip()]
    return [{k: rec[k] for k in fields if k in rec} for rec in records]


def paginate(
    records: list[dict[str, Any]], page_size: int | None, page: int = 1
) -> tuple[list[dict[str, Any]], int]:
    total = len(records)
    if not page_size:
        return records, total
    start = max(page - 1, 0) * page_size
    return records[start:start + page_size], total


__all__ = ["Condition", "parse_where", "apply_where", "apply_select", "paginate"]
