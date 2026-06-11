"""StaticConnectionRouter: explicit id wins; single active; zero/ambiguous -> error."""
import pytest

from rca_connector_sdk import ConnectionInfo, NoActiveConnection, StaticConnectionRouter


def _conn(connection_id: str, plant_id: str = "refinery-gc", category: str = "historian") -> ConnectionInfo:
    return ConnectionInfo(
        connection_id=connection_id, plant_id=plant_id, category=category,
        connector_type="pi", base_url="http://pi", extra_config={},
    )


async def test_returns_single_active_for_scope():
    router = StaticConnectionRouter([_conn("pi-main")])
    conn = await router.active("refinery-gc", "historian")
    assert conn.connection_id == "pi-main"


async def test_explicit_connection_id_overrides():
    router = StaticConnectionRouter([
        _conn("pi-main"),
        _conn("pi-backup"),
    ])
    conn = await router.active("refinery-gc", "historian", connection_id="pi-backup")
    assert conn.connection_id == "pi-backup"


async def test_no_active_connection_raises():
    router = StaticConnectionRouter([_conn("pi-main", plant_id="other-plant")])
    with pytest.raises(NoActiveConnection):
        await router.active("refinery-gc", "historian")


async def test_ambiguous_without_id_raises():
    router = StaticConnectionRouter([_conn("pi-main"), _conn("pi-backup")])
    with pytest.raises(NoActiveConnection):
        await router.active("refinery-gc", "historian")


async def test_explicit_id_not_found_raises():
    router = StaticConnectionRouter([_conn("pi-main")])
    with pytest.raises(NoActiveConnection):
        await router.active("refinery-gc", "historian", connection_id="nope")


async def test_explicit_id_wrong_scope_raises():
    router = StaticConnectionRouter([_conn("pi-main")])
    with pytest.raises(NoActiveConnection):
        await router.active("other-plant", "historian", connection_id="pi-main")
