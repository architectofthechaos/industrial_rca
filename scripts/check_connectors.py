"""Live connector health check (Sprint 4 WI3, demo gap D6).

For each of the 4 reference-plant connector types, build the connector's FastMCP server via
its factory and call its own ``test_connection`` MCP tool over an in-process ``fastmcp.Client``,
pointing the request's ``base_url`` at the live simulator. Asserts ``success is True`` per
connector. Mirrors ``rca_connections_api.registry`` (the /connections/{id}/test path): the
factories require a ConnectionRouter but the test_connection tool only consults base_url, so a
trivial empty ``StaticConnectionRouter([])`` satisfies the signature.

Exits 1 if any connector fails — so a sim being down (or a real connectivity regression) breaks
the live-demo gate loudly.
"""
from __future__ import annotations

import asyncio
import sys

from fastmcp import Client
from rca_connector_documents.server import make_document_mcp
from rca_connector_maximo.server import make_work_order_mcp
from rca_connector_pi.server import make_operator_log_mcp, make_tag_mcp
from rca_connector_sdk import StaticConnectionRouter
from rca_connector_sdk.health import TestConnectionResponse

# The test_connection tool never exercises routing; a trivial empty static router satisfies the
# factory signature (same as rca_connections_api.registry._NULL_ROUTER).
_NULL_ROUTER = StaticConnectionRouter([])
_TIMEOUT_SECONDS = 5.0

# (connector_type label, factory, sim base_url) — types/base_urls mirror host._static_dev_router.
CONNECTORS = [
    ("pi_historian", make_tag_mcp, "http://127.0.0.1:8001"),
    ("pi_event_frames", make_operator_log_mcp, "http://127.0.0.1:8001"),
    ("maximo", make_work_order_mcp, "http://127.0.0.1:8002"),
    ("sharepoint", make_document_mcp, "http://127.0.0.1:8004"),
]


async def _check(label: str, make_mcp, base_url: str) -> bool:
    """Build the connector FastMCP and call its test_connection tool against ``base_url``."""
    mcp = make_mcp(router=_NULL_ROUTER)
    try:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "test_connection",
                {"request": {"base_url": base_url, "timeout_seconds": _TIMEOUT_SECONDS}},
            )
        payload = (result.structured_content
                   if result.structured_content is not None else result.data)
        response = TestConnectionResponse.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 — surface any failure as a connector FAIL, not a crash
        print(f"FAIL {label} @ {base_url}: {exc}")
        return False
    if response.success:
        print(f"pass {label} @ {base_url}: success")
        return True
    print(f"FAIL {label} @ {base_url}: {response.error_summary}")
    return False


async def main() -> None:
    results = [await _check(label, make_mcp, base_url)
               for label, make_mcp, base_url in CONNECTORS]
    if not all(results):
        failed = sum(1 for r in results if not r)
        print(f"{failed}/{len(results)} connector(s) failed")
        sys.exit(1)
    print(f"all {len(results)} connectors healthy")


if __name__ == "__main__":
    asyncio.run(main())
