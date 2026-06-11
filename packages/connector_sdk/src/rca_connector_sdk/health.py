"""Uniform connector health-check contract (Sprint 2a): /health route + test_connection tool.

Every live connector registers the same two ops surfaces on its FastMCP server via
``register_health``:

* MCP tool ``test_connection`` (TestConnectionRequest -> TestConnectionResponse).
  Deliberately NOT ToolResponse-wrapped: it is an ops tool for the Connections
  page, and the spec fixes its exact shape — no provenance envelope.
* ``GET /health`` custom route -> HealthReport JSON, HTTP 200 for healthy/degraded,
  503 for unhealthy. The route probes the connector's configured upstream
  (base_url=None) with a 5-second budget.

Convention — the FIRST check is the gate: probes return their checks with the
connectivity gate first (``reachability`` for HTTP sources, ``broker_connect``
for MQTT, ``endpoint_reachability`` for OPC UA). ``aggregate`` maps a failed
first check to "unhealthy", any other failure to "degraded", and pass/skip
everywhere (including no checks at all) to "healthy".
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from fastmcp import FastMCP
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse

_ROUTE_TIMEOUT_SECONDS = 5.0


class CheckResult(BaseModel):
    name: str
    status: Literal["pass", "fail", "skip"]
    latency_ms: float
    message: str | None = None


class HealthReport(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    checks: list[CheckResult]
    version: str


class TestConnectionRequest(BaseModel):
    __test__ = False                   # spec name starts with "Test" — hide from pytest collection

    base_url: str | None = None        # override the configured upstream for a one-off test
    timeout_seconds: float = 5.0


class TestConnectionResponse(BaseModel):
    __test__ = False                   # spec name starts with "Test" — hide from pytest collection

    success: bool
    checks: list[CheckResult]
    upstream_version: str | None = None
    error_summary: str | None = None


ProbeResult = tuple[list[CheckResult], str | None]   # (checks, upstream_version)


class HealthProbe(Protocol):
    """Connector-supplied probe: run the sub-checks against `base_url` (None = configured)."""

    async def run(self, base_url: str | None, timeout: float) -> ProbeResult: ...


async def timed_check(name: str,
                      coro_factory: Callable[[], Awaitable[str | None]]) -> CheckResult:
    """Run one sub-check, timing it; an exception becomes a `fail` with type+text."""
    start = time.perf_counter()
    try:
        message = await coro_factory()
    except Exception as exc:  # noqa: BLE001 — boundary: any error is this check's failure
        return CheckResult(name=name, status="fail",
                           latency_ms=(time.perf_counter() - start) * 1000.0,
                           message=f"{type(exc).__name__}: {exc}")
    return CheckResult(name=name, status="pass",
                       latency_ms=(time.perf_counter() - start) * 1000.0, message=message)


def skipped_check(name: str, message: str) -> CheckResult:
    """A check that was not attempted (no creds, gate failed, ...)."""
    return CheckResult(name=name, status="skip", latency_ms=0.0, message=message)


def aggregate(checks: list[CheckResult]) -> Literal["healthy", "degraded", "unhealthy"]:
    """First check failed -> unhealthy; any other fail -> degraded; else healthy."""
    if not any(c.status == "fail" for c in checks):
        return "healthy"
    if checks[0].status == "fail":
        return "unhealthy"
    return "degraded"


def success(checks: list[CheckResult]) -> bool:
    return all(c.status != "fail" for c in checks)


def _error_summary(checks: list[CheckResult]) -> str | None:
    failures = [f"{c.name}: {c.message}" for c in checks if c.status == "fail"]
    return "; ".join(failures) if failures else None


def register_health(mcp: FastMCP, *, version: str, probe: HealthProbe) -> None:
    """Register the `test_connection` tool and the `GET /health` route on `mcp`."""

    @mcp.tool(name="test_connection")
    async def test_connection(request: TestConnectionRequest) -> TestConnectionResponse:
        try:
            checks, upstream_version = await probe.run(request.base_url,
                                                       request.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 — ops tool: report, never raise
            return TestConnectionResponse(success=False, checks=[], error_summary=str(exc))
        return TestConnectionResponse(success=success(checks), checks=checks,
                                      upstream_version=upstream_version,
                                      error_summary=_error_summary(checks))

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        try:
            checks, _ = await probe.run(None, _ROUTE_TIMEOUT_SECONDS)
            report = HealthReport(status=aggregate(checks), checks=checks, version=version)
        except Exception as exc:  # noqa: BLE001 — a broken probe is an unhealthy connector
            failure = CheckResult(name="probe", status="fail", latency_ms=0.0,
                                  message=f"{type(exc).__name__}: {exc}")
            report = HealthReport(status="unhealthy", checks=[failure], version=version)
        status_code = 503 if report.status == "unhealthy" else 200
        return JSONResponse(report.model_dump(), status_code=status_code)


__all__ = [
    "CheckResult", "HealthReport", "TestConnectionRequest", "TestConnectionResponse",
    "ProbeResult", "HealthProbe", "timed_check", "skipped_check", "aggregate",
    "success", "register_health",
]
