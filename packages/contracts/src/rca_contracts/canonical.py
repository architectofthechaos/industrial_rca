"""Canonical-id parsing — the human-readable `asset:{plant}:{unit}:{name}` key (Phase 1 §2.1).

Every asset carries a canonical_id of that exact shape (lowercase slugs). This module
parses one into its parts, refusing anything that doesn't match the grammar so callers
never silently accept a malformed key.
"""
from __future__ import annotations

import re

from ._base import StrictModel

_CANONICAL_RE = re.compile(r"^asset:([a-z0-9-]+):([a-z0-9-]+):([a-z0-9-]+)$")


class CanonicalParts(StrictModel):
    plant_id: str
    unit_slug: str
    name_slug: str


def parse_canonical_id(canonical_id: str) -> CanonicalParts:
    """Parse `asset:{plant}:{unit}:{name}` into its parts; raise ValueError if malformed."""
    match = _CANONICAL_RE.match(canonical_id)
    if match is None:
        raise ValueError(
            f"invalid canonical_id {canonical_id!r}; "
            f"expected 'asset:{{plant}}:{{unit}}:{{name}}' with lowercase [a-z0-9-] slugs"
        )
    plant_id, unit_slug, name_slug = match.groups()
    return CanonicalParts(plant_id=plant_id, unit_slug=unit_slug, name_slug=name_slug)


__all__ = ["CanonicalParts", "parse_canonical_id"]
