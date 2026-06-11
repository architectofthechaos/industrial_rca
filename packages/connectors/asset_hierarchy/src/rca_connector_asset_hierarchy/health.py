"""Health probe for the asset_hierarchy connector (Sprint 2a Task 10).

The asset_hierarchy connector is unusual: base_url is a per-request parameter (there
is no globally configured upstream).  The probe accepts an optional ``default_base_url``
so that callers can supply a default; when neither the request nor the default provides
one, the probe returns a single fail check describing the gap.

Sub-checks when a base_url is available (gate first):
  reachability          — GET /openapi.json, harvests info.version
  auth                  — skipped (no credentials configured — MVP)
  schema:assetdatabases — GET /assetdatabases
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

ClientFactory = Callable[[str, float], httpx.AsyncClient]


def _default_factory(base_url: str, timeout: float) -> httpx.AsyncClient:
    """Default factory: fresh client for the given URL + timeout."""
    return httpx.AsyncClient(base_url=base_url, timeout=timeout)


class AssetHierarchyHealthProbe:
    """HealthProbe implementation for the asset_hierarchy connector."""

    def __init__(
        self,
        client_factory: ClientFactory,
        *,
        default_base_url: str | None = None,
    ) -> None:
        self._factory = client_factory
        self._default_base_url = default_base_url

    async def run(self, base_url: str | None, timeout: float) -> ProbeResult:
        effective_url = base_url or self._default_base_url

        if not effective_url:
            # No URL available — report a meaningful failure (no timeout spent)
            fail = CheckResult(
                name="reachability",
                status="fail",
                latency_ms=0.0,
                message="no base_url configured; pass base_url",
            )
            return [fail], None

        upstream_version: str | None = None
        checks: list[CheckResult] = []

        async with self._factory(effective_url, timeout) as client:
            # 1. reachability gate
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
                checks.append(skipped_check("schema:assetdatabases", "skipped: reachability failed"))
                return checks, None

            # 2. auth — skipped (MVP: no credentials)
            checks.append(skipped_check("auth", "no credentials configured (MVP)"))

            # 3. schema:assetdatabases
            async def _assetdbs() -> str | None:
                resp = await client.get("/assetdatabases")
                resp.raise_for_status()
                return None

            checks.append(await timed_check("schema:assetdatabases", _assetdbs))

        return checks, upstream_version


__all__ = ["AssetHierarchyHealthProbe", "ClientFactory", "_default_factory"]
