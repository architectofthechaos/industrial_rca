"""Health contract (Sprint 2a Task 9): aggregation, timed_check, register_health.

Covers the aggregation table (first check is the gate), the timed_check helper's
pass/fail paths, and `register_health` end-to-end with fake probes: the
`test_connection` MCP tool (success / failing checks / raising probe) and the
`/health` custom route (200 healthy/degraded, 503 unhealthy) over the FastMCP
ASGI app.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastmcp import Client

from rca_connector_sdk import build_server
from rca_connector_sdk.health import (
    CheckResult,
    ProbeResult,
    TestConnectionResponse,
    aggregate,
    register_health,
    skipped_check,
    success,
    timed_check,
)


def _check(name: str, status: str) -> CheckResult:
    return CheckResult(name=name, status=status, latency_ms=1.0)  # type: ignore[arg-type]


# ---- aggregation ----

@pytest.mark.parametrize(("statuses", "expected"), [
    ([], "healthy"),                                  # vacuous: nothing to fail
    (["pass"], "healthy"),
    (["pass", "pass", "pass"], "healthy"),
    (["pass", "skip", "pass"], "healthy"),            # skips never degrade
    (["fail"], "unhealthy"),                          # the first check is the gate
    (["fail", "pass"], "unhealthy"),
    (["fail", "fail"], "unhealthy"),
    (["pass", "fail"], "degraded"),                   # non-gate failure only degrades
    (["pass", "skip", "fail", "pass"], "degraded"),
    (["skip", "fail"], "degraded"),                   # gate skipped, later fail
])
def test_aggregate_first_check_is_the_gate(statuses, expected):
    checks = [_check(f"c{i}", s) for i, s in enumerate(statuses)]
    assert aggregate(checks) == expected


def test_success_is_no_fail_anywhere():
    assert success([]) is True
    assert success([_check("a", "pass"), _check("b", "skip")]) is True
    assert success([_check("a", "pass"), _check("b", "fail")]) is False


# ---- timed_check / skipped_check ----

async def test_timed_check_pass_measures_latency_and_keeps_message():
    async def probe() -> str | None:
        await asyncio.sleep(0.01)
        return "looking good"

    result = await timed_check("reachability", probe)
    assert result.name == "reachability"
    assert result.status == "pass"
    assert result.message == "looking good"
    assert result.latency_ms > 0


async def test_timed_check_fail_captures_exception_type_and_text():
    async def probe() -> str | None:
        raise ValueError("boom")

    result = await timed_check("reachability", probe)
    assert result.status == "fail"
    assert result.message == "ValueError: boom"
    assert result.latency_ms >= 0


def test_skipped_check_has_zero_latency():
    result = skipped_check("auth", "no credentials configured (MVP)")
    assert result.status == "skip"
    assert result.latency_ms == 0.0
    assert result.message == "no credentials configured (MVP)"


# ---- register_health: fake probes ----

class GoodProbe:
    """All checks pass; records the (base_url, timeout) it was called with."""

    def __init__(self) -> None:
        self.calls: list[tuple[str | None, float]] = []

    async def run(self, base_url: str | None, timeout: float) -> ProbeResult:
        self.calls.append((base_url, timeout))
        return [_check("reachability", "pass"),
                skipped_check("auth", "no credentials configured (MVP)")], "9.9.9"


class GateFailProbe:
    async def run(self, base_url: str | None, timeout: float) -> ProbeResult:
        return [CheckResult(name="reachability", status="fail", latency_ms=2.0,
                            message="ConnectError: down"),
                skipped_check("schema", "skipped: reachability failed")], None


class DegradedProbe:
    async def run(self, base_url: str | None, timeout: float) -> ProbeResult:
        return [_check("reachability", "pass"),
                CheckResult(name="schema", status="fail", latency_ms=2.0,
                            message="HTTPStatusError: 500")], "9.9.9"


class BoomProbe:
    async def run(self, base_url: str | None, timeout: float) -> ProbeResult:
        raise RuntimeError("probe exploded")


def _server(probe) -> "FastMCP":  # noqa: F821 — annotation for readability only
    mcp = build_server("health-under-test")
    register_health(mcp, version="0.1.0", probe=probe)
    return mcp


async def _call(mcp, body: dict) -> TestConnectionResponse:
    async with Client(mcp) as client:
        result = await client.call_tool("test_connection", {"request": body})
    payload = result.structured_content if result.structured_content is not None else result.data
    return TestConnectionResponse.model_validate(payload)


async def test_tool_is_registered_and_succeeds_with_upstream_version():
    probe = GoodProbe()
    mcp = _server(probe)
    async with Client(mcp) as client:
        assert "test_connection" in {t.name for t in await client.list_tools()}
    resp = await _call(mcp, {})
    assert resp.success is True
    assert [c.name for c in resp.checks] == ["reachability", "auth"]
    assert resp.upstream_version == "9.9.9"
    assert resp.error_summary is None
    assert probe.calls == [(None, 5.0)]               # request defaults forwarded


async def test_tool_forwards_base_url_and_timeout_overrides():
    probe = GoodProbe()
    resp = await _call(_server(probe), {"base_url": "http://override:9", "timeout_seconds": 2.5})
    assert resp.success is True
    assert probe.calls == [("http://override:9", 2.5)]


async def test_tool_reports_failing_checks_with_summary():
    resp = await _call(_server(GateFailProbe()), {})
    assert resp.success is False
    assert resp.checks[0].status == "fail"
    assert resp.error_summary == "reachability: ConnectError: down"


async def test_tool_with_raising_probe_returns_graceful_failure():
    resp = await _call(_server(BoomProbe()), {})
    assert resp.success is False
    assert resp.checks == []
    assert resp.error_summary == "probe exploded"


# ---- register_health: /health route over the ASGI app ----

async def _get_health(mcp) -> httpx.Response:
    transport = httpx.ASGITransport(app=mcp.http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://health") as client:
        return await client.get("/health")


async def test_health_route_healthy_returns_200_report():
    probe = GoodProbe()
    resp = await _get_health(_server(probe))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["version"] == "0.1.0"
    assert [c["name"] for c in body["checks"]] == ["reachability", "auth"]
    assert probe.calls == [(None, 5.0)]               # route probes the configured upstream


async def test_health_route_degraded_is_still_200():
    resp = await _get_health(_server(DegradedProbe()))
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"


async def test_health_route_unhealthy_returns_503():
    resp = await _get_health(_server(GateFailProbe()))
    assert resp.status_code == 503
    assert resp.json()["status"] == "unhealthy"


async def test_health_route_raising_probe_returns_503_with_probe_check():
    resp = await _get_health(_server(BoomProbe()))
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["checks"][0]["name"] == "probe"
    assert "RuntimeError: probe exploded" in body["checks"][0]["message"]
