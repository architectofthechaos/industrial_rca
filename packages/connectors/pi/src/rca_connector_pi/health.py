"""Health probe for the PI connector (Sprint 2a Task 10).

Sub-checks (gate first):
  reachability  — GET /openapi.json, harvests info.version
  auth          — skipped (no credentials configured — MVP)
  schema:af     — GET /assetdatabases
  schema:historian — GET /eventframes?startTime=...&endTime=...
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

# one-minute window for the historian schema check (cheap, matches the sim)
_AF_START = "2026-01-01T00:00:00Z"
_AF_END = "2026-01-01T00:01:00Z"

ClientFactory = Callable[[str | None, float], httpx.AsyncClient]


def _default_factory(configured_base_url: str) -> ClientFactory:
    """Return a factory that builds a fresh client from the override or the configured URL."""

    def _make(base_url_override: str | None, timeout: float) -> httpx.AsyncClient:
        url = base_url_override or configured_base_url
        return httpx.AsyncClient(base_url=url, timeout=timeout)

    return _make


class PiHealthProbe:
    """HealthProbe implementation for the PI connector."""

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
                checks.append(skipped_check("schema:af", "skipped: reachability failed"))
                checks.append(skipped_check("schema:historian", "skipped: reachability failed"))
                return checks, None

            # 2. auth — skipped (MVP: no credentials)
            checks.append(skipped_check("auth", "no credentials configured (MVP)"))

            # 3. schema:af
            async def _af() -> str | None:
                resp = await client.get("/assetdatabases")
                resp.raise_for_status()
                return None

            checks.append(await timed_check("schema:af", _af))

            # 4. schema:historian
            async def _historian() -> str | None:
                resp = await client.get(
                    f"/eventframes?startTime={_AF_START}&endTime={_AF_END}"
                )
                resp.raise_for_status()
                return None

            checks.append(await timed_check("schema:historian", _historian))

        return checks, upstream_version


__all__ = ["PiHealthProbe", "ClientFactory", "_default_factory"]
