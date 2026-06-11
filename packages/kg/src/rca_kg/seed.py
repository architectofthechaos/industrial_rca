"""Idempotent KG seed runner (Sprint 2a Task 4).

Applies the two seed files (ISO 14224 BB1 ontology + Refinery GC hierarchy) statement by
statement. Every statement is a MERGE, so re-running is safe at any time — unlike the
migration runner this does NOT consult the `_migrations` ledger (migrations 0002/0003
`@include` the same files so a fresh `task kg:migrate` seeds too; `task kg:seed` re-seeds
a dev DB at will, e.g. after hand-edits).

Run: `uv run python -m rca_kg.seed` (or `task kg:seed`).
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from neo4j import Driver

from rca_kg import config
from rca_kg.migrate import read_statements

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
SEED_FILES = ("iso14224_bb1.cypher", "refplant_hierarchy.cypher")


def run(driver: Driver, database: str, *, log: Callable[[str], object] = print) -> int:
    """Apply both seed files; return the number of statements run."""
    total = 0
    with driver.session(database=database) as session:
        for name in SEED_FILES:
            statements = read_statements(SEED_DIR / name)
            for stmt in statements:
                session.execute_write(lambda tx, s=stmt: tx.run(s).consume())  # type: ignore[misc]
            log(f"seeded {name} ({len(statements)} statements)")
            total += len(statements)
    return total


def main() -> int:
    with config.make_driver() as driver:
        run(driver, config.kg_database())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
