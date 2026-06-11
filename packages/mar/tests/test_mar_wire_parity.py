"""End-to-end wire-in: MAR (seeded, in-memory repo) -> MarResolver -> Maximo connector -> REAL sim.
Proves the static binding is replaced by registry resolution. Skips when the sim is down.
Run with: `task parity:mar-wire`."""
import json
import os
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastmcp import Client
from rca_contracts import ToolResponse, WorkOrder

from rca_connector_maximo.server import make_maximo_mcp
from rca_mar.repository import InMemoryRepository
from rca_mar.resolver import MarResolver
from rca_mar.seed import seed_from_register

REGISTER = Path(__file__).resolve().parents[1] / "seed_data" / "refplant_assets.yaml"
MAXIMO_SIM_URL = os.environ.get("MAXIMO_SIM_URL", "http://127.0.0.1:8002")
TENANT = UUID("0190d3c9-0000-7000-8000-0000000000ff")
P101A = UUID("0190d3c9-0000-7000-8000-000000000001")


def _sim_reachable() -> bool:
    try:
        return httpx.get(f"{MAXIMO_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _sim_reachable(),
                                reason=f"Maximo sim not reachable at {MAXIMO_SIM_URL} (run `task parity:mar-wire`)")


def _parse(result):
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[list[WorkOrder]].model_validate_json(json.dumps(payload))


async def test_mar_resolved_handle_fetches_real_workorders():
    repo = InMemoryRepository()
    await seed_from_register(repo, REGISTER)
    resolver = MarResolver(repo=repo, tenant_id=TENANT)
    async with httpx.AsyncClient(base_url=MAXIMO_SIM_URL) as http:
        mcp = make_maximo_mcp(http_client=http, tag_resolver=resolver)   # no static bindings!
        async with Client(mcp) as client:
            res = _parse(await client.call_tool(
                "maximo.get_workorders", {"request": {"asset_id": str(P101A)}}))
            assert res.error is None and len(res.data) > 0
            assert {"WO-50012345", "WO-50012402"} <= {w.work_order_id for w in res.data}
            assert all(w.source_system == "maximo" for w in res.data)
