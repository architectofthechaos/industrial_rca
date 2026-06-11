"""Shared onboarding test helpers (uniquely named to avoid the cross-package `conftest`
module-name collision: two bare `conftest` modules can't coexist under pytest's prepend
import mode, so the importable constants/functions live here and tests import them from
``onb_helpers`` rather than ``conftest``). The fixtures stay in conftest.py for autodiscovery.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import FastAPI

from rca_mar.repository import ConnectionRow

# Reuse the asset_hierarchy connector's fake AF app (mirrors the real simulator field-for-field).
# parents[2] == packages/ (tests -> onboarding -> packages).
_FAKE_AF_DIR = (Path(__file__).resolve().parents[2]
                / "connectors" / "asset_hierarchy" / "tests")
if str(_FAKE_AF_DIR) not in sys.path:
    sys.path.insert(0, str(_FAKE_AF_DIR))
import fake_af  # noqa: E402
from fake_af import make_fake_af_app  # noqa: E402

TENANT = UUID("0190d3c9-0000-7000-8000-0000000000ff")
PLANT_ID = "refinery-gc"
DB_NAME = "Refinery-GC"
HIERARCHY_CONNECTION_ID = "refinery-gc.hierarchy.pi-af-default"
CMMS_CONNECTION_ID = "refinery-gc.cmms.maximo-default"
AF_BASE_URL = "http://fake-af"


def make_fake_af_app_without_p103a() -> FastAPI:
    """A fake AF app whose tree drops AREA-200/UNIT-201/P-103A — for the decommission test.

    Builds the standard tree, then prunes the AREA-200 subtree (which holds only UNIT-201 ->
    P-103A), so a second crawl no longer reports P-103A as a seen vendor id.
    """
    tree = fake_af._hierarchy(include_mystery=False, include_nested_child=False)
    tree = {**tree, "children": [c for c in tree["children"] if c["name"] != "AREA-200"]}
    # Reuse the module's app builder by temporarily swapping its tree source.
    original = fake_af._hierarchy
    fake_af._hierarchy = lambda *a, **k: tree  # type: ignore[assignment]
    try:
        return make_fake_af_app()
    finally:
        fake_af._hierarchy = original  # type: ignore[assignment]


def hierarchy_connection() -> ConnectionRow:
    return ConnectionRow(
        connection_id=HIERARCHY_CONNECTION_ID, plant_id=PLANT_ID, category="hierarchy",
        connector_type="pi_af", display_name="PI AF (default)", base_url=AF_BASE_URL,
        auth_config={"type": "none", "secret_ref": None}, status="active",
        extra_config={"database_name": DB_NAME})


def cmms_connection() -> ConnectionRow:
    return ConnectionRow(
        connection_id=CMMS_CONNECTION_ID, plant_id=PLANT_ID, category="cmms",
        connector_type="maximo", display_name="Maximo (default)",
        base_url="http://maximo-unreachable", auth_config={"type": "none", "secret_ref": None},
        status="active", extra_config=None)


def make_http_factory(app: FastAPI):
    """An http_factory that routes ANY base_url to the given fake AF ASGI app."""

    def factory(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)

    return factory
