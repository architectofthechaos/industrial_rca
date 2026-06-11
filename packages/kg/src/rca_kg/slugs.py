"""Lowercased, hyphen-separated canonical-id segments (e.g. 'P-101A' -> 'p-101a').

Single source of truth shared by MAR seed and KG seed (Sprint 2a acceptance #9).
"""
from __future__ import annotations

import re


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


__all__ = ["slug"]
