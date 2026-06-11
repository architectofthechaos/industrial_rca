"""Connector test probes (Sprint 2b §1.3 ``POST /connections/{id}/test``).

``CONNECTOR_PROBES`` maps a ``connector_type`` to an async ``test(base_url, timeout,
extra_config) -> TestConnectionResponse``. Each probe builds the connector's FastMCP server
via its factory and calls the connector's own ``test_connection`` MCP tool through an
in-memory ``fastmcp.Client`` — this is exactly what the spec means by "calls the connector's
test_connection MCP tool". The ``base_url`` is passed as the tool request's ``base_url``
override, so the connector's health probe runs against the connection's configured upstream
rather than a wired default.

We do NOT need real upstream creds: the MVP connectors don't authenticate, so resolving a
secret_ref (done by the caller) and not exposing it is sufficient. A connector_type with no
probe (e.g. ``uns``/``mqtt``, ``opc_ua``) returns a clear ``success=False`` response rather
than raising, so the /test endpoint still persists a result.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastmcp import Client
from rca_connector_sdk import StaticConnectionRouter
from rca_connector_sdk.health import TestConnectionResponse

from rca_connector_asset_hierarchy.server import make_asset_hierarchy_mcp
from rca_connector_documents.server import make_document_mcp
from rca_connector_maximo.server import make_work_order_mcp
from rca_connector_pi.server import make_operator_log_mcp, make_tag_mcp

# A probe builds + calls the connector's test_connection tool for a given base_url.
Probe = Callable[[str, float, dict | None], Awaitable[TestConnectionResponse]]

# The connector test_connection tool only consults base_url; routing is never exercised here,
# but the factories require a ConnectionRouter — a trivial empty static router satisfies that.
_NULL_ROUTER = StaticConnectionRouter([])


async def _call_test_connection(mcp, base_url: str, timeout: float) -> TestConnectionResponse:
    """Invoke a connector server's ``test_connection`` MCP tool with a base_url override."""
    async with Client(mcp) as client:
        result = await client.call_tool(
            "test_connection", {"request": {"base_url": base_url, "timeout_seconds": timeout}})
        payload = (result.structured_content
                   if result.structured_content is not None else result.data)
        return TestConnectionResponse.model_validate(payload)


def _mcp_probe(make_mcp: Callable[..., object]) -> Probe:
    """A probe that builds a connector FastMCP via ``make_mcp`` and calls its test_connection."""

    async def probe(base_url: str, timeout: float,
                    extra_config: dict | None) -> TestConnectionResponse:
        mcp = make_mcp(router=_NULL_ROUTER)
        return await _call_test_connection(mcp, base_url, timeout)

    return probe


def _asset_hierarchy_probe() -> Probe:
    """asset_hierarchy's factory takes no router (it carries base_url per request)."""

    async def probe(base_url: str, timeout: float,
                    extra_config: dict | None) -> TestConnectionResponse:
        mcp = make_asset_hierarchy_mcp()
        return await _call_test_connection(mcp, base_url, timeout)

    return probe


def _no_probe(connector_type: str) -> Probe:
    """A connector_type without a wired test probe — report a clear failure, never raise."""

    async def probe(base_url: str, timeout: float,
                    extra_config: dict | None) -> TestConnectionResponse:
        return TestConnectionResponse(
            success=False, checks=[],
            error_summary=f"no test probe configured for connector_type {connector_type!r}")

    return probe


# connector_type -> probe. pi_historian/pi_event_frames front the PI Web API (tag /
# operator_log servers share the same TagHealthProbe); pi_af is the AF crawler.
CONNECTOR_PROBES: dict[str, Probe] = {
    "pi_historian": _mcp_probe(make_tag_mcp),
    "pi_event_frames": _mcp_probe(make_operator_log_mcp),
    "pi_af": _asset_hierarchy_probe(),
    "maximo": _mcp_probe(make_work_order_mcp),
    "sharepoint": _mcp_probe(make_document_mcp),
    # No probe wired (no FastMCP test_connection surface for these MVP transports yet):
    "uns": _no_probe("uns"),
    "mqtt": _no_probe("mqtt"),
    "opc_ua": _no_probe("opc_ua"),
}


def probe_for(connector_type: str) -> Probe:
    """Return the probe for a connector_type, or a clear no-probe failure for unknown ones."""
    return CONNECTOR_PROBES.get(connector_type) or _no_probe(connector_type)


__all__ = ["Probe", "CONNECTOR_PROBES", "probe_for"]
