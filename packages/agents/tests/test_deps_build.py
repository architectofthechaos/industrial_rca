import pytest
from fastmcp import Client
from rca_agents.activities import ProbeActivityDeps
from rca_agents.deps import build_probe_deps
from rca_agents.host import build_entity_host, _static_dev_router
from rca_agents.mcp_toolbox import McpToolBox
from rca_kg.assets import InMemoryAssetGraph
from rca_mar.repository import InMemoryRepository


@pytest.mark.asyncio
async def test_build_probe_deps_assembles_nine_fields(monkeypatch):
    # transports may resolve API keys at construction; provide dummies (never called here)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")
    monkeypatch.setenv("VOYAGE_API_KEY", "test-dummy-key")
    host = await build_entity_host(router=_static_dev_router(), mar_repo=InMemoryRepository(),
                                   asset_graph=InMemoryAssetGraph())
    async with Client(host) as client:
        deps = build_probe_deps(toolbox=McpToolBox(client), asset_graph=InMemoryAssetGraph(),
                                wo_client=client, use_postgres=False)
        assert isinstance(deps, ProbeActivityDeps)
        for f in ["llm", "toolbox", "asset_graph", "wo_creator", "runs", "memory",
                  "evidence", "conclusions", "agent_factories"]:
            assert getattr(deps, f) is not None
        assert set(deps.agent_factories) == {"planning", "gather", "rca"}
