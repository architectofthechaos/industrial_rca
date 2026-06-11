"""Health probe for the document connector (SharePoint-sim-backed).

The document entity MCP routes per-request (base_url arrives from the connection router),
so the probe mirrors the pi TagHealthProbe shape: base_url is per-request, or falls back to
a configured ``default_base_url`` so ``GET /health`` (base_url=None) still probes. Sub-checks
unchanged from the old documents probe:

  reachability   — GET /openapi.json, harvests info.version
  auth           — skipped (no credentials configured — MVP)
  schema:search  — GET /search?q=health&top=1
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


class DocumentHealthProbe:
    """HealthProbe for the SharePoint-sim-backed document connector.

    base_url is per-request (entity MCPs route per connection); ``default_base_url`` feeds
    the configured upstream so ``GET /health`` (which passes base_url=None) still probes.
    """

    def __init__(
        self,
        client_factory: ClientFactory | None = None,
        *,
        default_base_url: str | None = None,
    ) -> None:
        self._factory = client_factory or _default_factory
        self._default_base_url = default_base_url

    async def run(self, base_url: str | None, timeout: float) -> ProbeResult:
        effective_url = base_url or self._default_base_url

        if not effective_url:
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
                checks.append(skipped_check("schema:search", "skipped: reachability failed"))
                return checks, None

            # 2. auth — skipped (MVP: no credentials)
            checks.append(skipped_check("auth", "no credentials configured (MVP)"))

            # 3. schema:search — minimal search probe
            async def _search() -> str | None:
                resp = await client.get("/search", params={"q": "health", "top": "1"})
                resp.raise_for_status()
                return None

            checks.append(await timed_check("schema:search", _search))

        return checks, upstream_version


__all__ = ["DocumentHealthProbe", "ClientFactory", "_default_factory"]
