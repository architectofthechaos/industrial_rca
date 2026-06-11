"""Health probe for the Maximo connector (Sprint 2a Task 10).

Sub-checks (gate first):
  reachability       — GET /openapi.json, harvests info.version
  auth               — skipped (no credentials configured — MVP)
  schema:workorders  — GET /maxrest/oslc/os/mxwo?oslc.pageSize=1
"""
from __future__ import annotations

from collections.abc import Callable

import httpx
from rca_connector_sdk.health import (
    CheckResult,
    ProbeResult,
    skipped_check,
    timed_check,
)

ClientFactory = Callable[[str | None, float], httpx.AsyncClient]


def _default_factory(configured_base_url: str) -> ClientFactory:
    """Return a factory that builds a fresh client from the override or the configured URL."""

    def _make(base_url_override: str | None, timeout: float) -> httpx.AsyncClient:
        url = base_url_override or configured_base_url
        return httpx.AsyncClient(base_url=url, timeout=timeout)

    return _make


class MaximoHealthProbe:
    """HealthProbe implementation for the Maximo connector."""

    def __init__(self, client_factory: ClientFactory) -> None:
        self._factory = client_factory

    async def run(self, base_url: str | None, timeout: float) -> ProbeResult:
        upstream_version: str | None = None
        checks: list[CheckResult] = []

        async with self._factory(base_url, timeout) as client:
            # 1. reachability gate — harvest upstream_version
            async def _reach() -> str | None:
                nonlocal upstream_version
                resp = await client.get("/openapi.json")
                resp.raise_for_status()
                upstream_version = resp.json().get("info", {}).get("version")
                return upstream_version

            gate = await timed_check("reachability", _reach)
            checks.append(gate)

            if gate.status == "fail":
                checks.append(skipped_check("auth", "skipped: reachability failed"))
                checks.append(skipped_check("schema:workorders", "skipped: reachability failed"))
                return checks, None

            # 2. auth — skipped (MVP: no credentials)
            checks.append(skipped_check("auth", "no credentials configured (MVP)"))

            # 3. schema:workorders — minimal read
            async def _workorders() -> str | None:
                resp = await client.get(
                    "/maxrest/oslc/os/mxwo",
                    params={"oslc.pageSize": "1"},
                )
                resp.raise_for_status()
                return None

            checks.append(await timed_check("schema:workorders", _workorders))

        return checks, upstream_version


__all__ = ["MaximoHealthProbe", "ClientFactory", "_default_factory"]
