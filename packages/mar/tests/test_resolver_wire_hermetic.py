"""MarResolver injected into the Maximo connector factory resolves the source handle end-to-end,
against an in-process Maximo OSLC fake (no DB, no live sim, no rca_simulator import)."""
import json
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import FastAPI, Request
from fastmcp import Client
from rca_contracts import ToolResponse, WorkOrder

from rca_connector_maximo.server import make_maximo_mcp
from rca_mar.repository import InMemoryRepository
from rca_mar.resolver import MarResolver
from rca_mar.seed import seed_from_register

REGISTER = Path(__file__).resolve().parents[1] / "seed_data" / "refplant_assets.yaml"
TENANT = UUID("0190d3c9-0000-7000-8000-0000000000ff")
P101A = UUID("0190d3c9-0000-7000-8000-000000000001")


def _maximo_fake() -> FastAPI:
    app = FastAPI()

    @app.get("/maxrest/oslc/os/mxwo")
    def workorders(request: Request):
        return {"member": [{"wonum": "WO-1", "location": "CRDU-P101A", "status": "COMP",
                            "wopriority": 3, "description": "seal check", "reportdate": "2026-01-02T00:00:00"}]}

    return app


def _parse(result):
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[list[WorkOrder]].model_validate_json(json.dumps(payload))


async def test_maximo_uses_mar_resolved_handle():
    repo = InMemoryRepository()
    await seed_from_register(repo, REGISTER)
    resolver = MarResolver(repo=repo, tenant_id=TENANT)

    transport = httpx.ASGITransport(app=_maximo_fake())
    async with httpx.AsyncClient(transport=transport, base_url="http://maximo") as http:
        mcp = make_maximo_mcp(http_client=http, bindings={}, tag_resolver=resolver)
        async with Client(mcp) as client:
            res = _parse(await client.call_tool(
                "maximo.get_workorders", {"request": {"asset_id": str(P101A)}}))
            assert res.error is None and len(res.data) == 1
            assert res.data[0].source_system == "maximo"
