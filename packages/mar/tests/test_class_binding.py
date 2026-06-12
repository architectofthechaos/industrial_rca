import pytest

from rca_mar.class_binding import kg_class_for


def test_dotted_maps_to_kg_id():
    assert kg_class_for("pump.centrifugal") == "equipment-class:bb1"


def test_unknown_dotted_returns_none():
    assert kg_class_for("turbine.gas") is None


@pytest.mark.asyncio
async def test_inmemory_register_persists_kg_class():
    from pathlib import Path
    from uuid import UUID

    import yaml

    from rca_mar.repository import InMemoryRepository
    from rca_mar.seed import seed_from_register

    repo = InMemoryRepository()
    reg = Path(__file__).resolve().parents[1] / "seed_data" / "refplant_assets.yaml"
    tenant = UUID(str(yaml.safe_load(reg.read_text())["tenant_id"]))
    await seed_from_register(repo, reg)
    hits = await repo.search_assets(tenant, iso14224_class="pump.centrifugal")
    assert hits and all(h.iso14224_class_kg == "equipment-class:bb1" for h in hits)
