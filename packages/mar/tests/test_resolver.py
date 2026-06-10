from pathlib import Path
from uuid import UUID, uuid4

import pytest
from rca_connector_sdk import SignalResolver, SourceBinding
from rca_connector_sdk.errors import UnresolvedSignal

from rca_mar.repository import InMemoryRepository
from rca_mar.resolver import MarResolver
from rca_mar.seed import seed_from_register

REGISTER = Path(__file__).resolve().parents[1] / "seed_data" / "refplant_assets.yaml"
TENANT = UUID("0190d3c9-0000-7000-8000-0000000000ff")
P101A = UUID("0190d3c9-0000-7000-8000-000000000001")


async def _resolver() -> MarResolver:
    repo = InMemoryRepository()
    await seed_from_register(repo, REGISTER)
    return MarResolver(repo=repo, tenant_id=TENANT)


async def test_satisfies_port():
    assert isinstance(await _resolver(), SignalResolver)


async def test_source_binding_returns_external_handle():
    r = await _resolver()
    b = await r.source_binding(P101A, "maximo")
    assert isinstance(b, SourceBinding) and b.handle == "CRDU-P101A" and b.raw_unit == "n/a"


async def test_unknown_binding_raises():
    r = await _resolver()
    with pytest.raises(UnresolvedSignal):
        await r.source_binding(uuid4(), "maximo")


async def test_resolve_signal_is_trs_domain():
    r = await _resolver()
    with pytest.raises(UnresolvedSignal):
        await r.resolve(uuid4())
