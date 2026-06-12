import pytest
from fastmcp import Client
from rca_agents.host import build_entity_host, _static_dev_router
from rca_kg.assets import InMemoryAssetGraph
from rca_mar.repository import InMemoryRepository


@pytest.mark.asyncio
async def test_host_mounts_all_entity_tools():
    host = await build_entity_host(router=_static_dev_router(),
                                   mar_repo=InMemoryRepository(),
                                   asset_graph=InMemoryAssetGraph())
    async with Client(host) as c:
        names = {t.name for t in await c.list_tools()}
    for required in ["asset.get", "asset.search", "kg.get_asset_context", "kg.upsert_asset",
                     "kg.link_failure_mode", "tag.get_history", "tag.list_for_asset",
                     "work_order.list_for_asset", "document.search_for_asset",
                     "operator_log.list_for_asset"]:
        assert required in names, f"{required} not mounted; have {sorted(names)}"
