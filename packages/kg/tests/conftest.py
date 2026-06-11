"""Shared KG test helpers: Neo4j reachability probe + skip marker (Sprint 2a).

Live tests decorate with `requires_kg` (or set `pytestmark`); they skip unless the
bolt port from `rca_kg.config.kg_uri()` answers (run `task kg:db:up` first).
"""
from __future__ import annotations

import socket
from urllib.parse import urlparse

import pytest

KG_SKIP_REASON = "Neo4j not reachable (run `task kg:db:up`)"


def kg_reachable() -> bool:
    from rca_kg.config import kg_uri

    try:
        u = urlparse(kg_uri())
        with socket.create_connection((u.hostname or "127.0.0.1", u.port or 7687), timeout=1):
            return True
    except Exception:
        return False


requires_kg = pytest.mark.skipif(not kg_reachable(), reason=KG_SKIP_REASON)
