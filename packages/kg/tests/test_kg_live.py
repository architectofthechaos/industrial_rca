"""Live KG seed test against a real Neo4j (Sprint 2a Task 4).

Skips when the bolt port from `rca_kg.config.kg_uri()` is unreachable (run `task
kg:db:up`). Does NOT wipe the database — counts by the specific seed labels only.
The seed holds 122 ontology nodes (see test_seed_content.py); we assert the sprint
plan budget of >=120 here since a shared dev DB may hold extras.
"""
from __future__ import annotations

import socket
from urllib.parse import urlparse

import pytest

from rca_kg import seed
from rca_kg.migrate import DEFAULT_MIGRATIONS_DIR, apply_all

ONTOLOGY_COUNT_QUERY = (
    "MATCH (n) WHERE n:EquipmentClass OR n:FailureMode OR n:FailureMechanism "
    "OR n:MaintenanceActivity OR n:Subunit OR n:Component RETURN count(n) AS c"
)
HIERARCHY_COUNT_QUERY = "MATCH (n) WHERE n:Site OR n:Area OR n:Unit RETURN count(n) AS c"
PATH_QUERY = (
    "MATCH (s:Site {id: 'site:refinery-gc'})-[:CONTAINS]->(:Area)"
    "-[:CONTAINS]->(u:Unit {id: 'unit:refinery-gc:unit-101'}) RETURN count(*) AS c"
)


def _kg_reachable() -> bool:
    from rca_kg.config import kg_uri

    try:
        u = urlparse(kg_uri())
        with socket.create_connection((u.hostname or "127.0.0.1", u.port or 7687), timeout=1):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _kg_reachable(),
                                reason="Neo4j not reachable (run `task kg:db:up`)")


def _count(session, query: str) -> int:
    return session.execute_read(lambda tx: tx.run(query).single(strict=True)["c"])


def test_migrate_and_seed_populate_ontology_and_hierarchy_idempotently() -> None:
    from rca_kg.config import kg_database, make_driver

    with make_driver() as driver:
        db = kg_database()
        apply_all(driver, db, DEFAULT_MIGRATIONS_DIR, log=lambda _msg: None)
        seed.run(driver, db, log=lambda _msg: None)

        with driver.session(database=db) as session:
            ontology = _count(session, ONTOLOGY_COUNT_QUERY)
            assert ontology >= 120  # sprint plan budget; dev DB may hold extras
            assert _count(session, HIERARCHY_COUNT_QUERY) == 6  # 1 site + 2 areas + 3 units
            assert _count(session, PATH_QUERY) >= 1  # site -> area-100 -> unit-101 path exists
            total_before = _count(session, "MATCH (n) RETURN count(n) AS c")

        seed.run(driver, db, log=lambda _msg: None)  # re-seeding adds zero nodes

        with driver.session(database=db) as session:
            assert _count(session, "MATCH (n) RETURN count(n) AS c") == total_before
