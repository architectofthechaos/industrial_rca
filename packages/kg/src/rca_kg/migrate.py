"""Forward-only Cypher migration runner for the KG Neo4j database (Sprint 2a).

Migrations are `NNNN_name.cypher` files in `packages/kg/migrations/`. A migration file
may pull in shared cypher with a `// @include <relpath>` line (resolved relative to the
containing file). Applied migration ids are recorded on a `_migrations` singleton node,
so re-running is a no-op. Forward-only: there are no down migrations; statements are run
one transaction each (Neo4j forbids mixing schema and data writes in one transaction),
so every statement must be idempotent (`IF NOT EXISTS` / `MERGE`).

Run: `uv run python -m rca_kg.migrate [migrations_dir]` (or `task kg:migrate`).
"""
from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from neo4j import Driver, ManagedTransaction

from rca_kg import config

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

_MIGRATION_FILE_RE = re.compile(r"^(\d{4})_(\w+)\.cypher$")
_INCLUDE_RE = re.compile(r"^\s*//\s*@include\s+(\S+)\s*$")

_ENSURE_SINGLETON = (
    "MERGE (m:_migrations {id: 'singleton'}) ON CREATE SET m.applied = [] "
    "RETURN m.applied AS applied"
)
_RECORD_APPLIED = "MATCH (m:_migrations {id: 'singleton'}) SET m.applied = m.applied + $id"


@dataclass(frozen=True)
class Migration:
    number: int
    id: str
    path: Path


def discover(migrations_dir: Path) -> list[Migration]:
    """List migrations in `migrations_dir`, sorted by leading number.

    Only files named `NNNN_name.cypher` count; anything else (README, seed fragments,
    editor droppings) is silently ignored rather than rejected.
    """
    migrations = []
    for path in migrations_dir.iterdir():
        m = _MIGRATION_FILE_RE.match(path.name)
        if m:
            migrations.append(Migration(number=int(m.group(1)), id=path.stem, path=path))
    return sorted(migrations, key=lambda mig: (mig.number, mig.id))  # id tie-breaks duplicates


def _resolve_text(path: Path) -> str:
    """Read `path`, replacing each `// @include <relpath>` line with that file's content."""
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        include = _INCLUDE_RE.match(line)
        if include:
            lines.append(_resolve_text((path.parent / include.group(1)).resolve()))
        else:
            lines.append(line)
    return "\n".join(lines)


def read_statements(path: Path) -> list[str]:
    """Statements in `path`: includes resolved, `//` comment lines stripped, split on
    `;` at end-of-line (mid-line semicolons are preserved), empties dropped."""
    statements: list[str] = []
    current: list[str] = []

    def flush() -> None:
        stmt = "\n".join(current).strip().rstrip(";").strip()
        if stmt:
            statements.append(stmt)
        current.clear()

    for line in _resolve_text(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            flush()
    flush()  # tolerate a final statement with no trailing ';'
    return statements


def apply_all(
    driver: Driver,
    database: str,
    migrations_dir: Path,
    *,
    log: Callable[[str], object] = print,
) -> list[str]:
    """Apply every not-yet-applied migration in order; return the newly-applied ids."""
    def ensure_singleton(tx: ManagedTransaction) -> list[str]:
        record = tx.run(_ENSURE_SINGLETON).single(strict=True)  # MERGE+RETURN: exactly one row
        return list(record["applied"])

    newly_applied: list[str] = []
    with driver.session(database=database) as session:
        applied: set[str] = set(session.execute_write(ensure_singleton))
        for migration in discover(migrations_dir):
            if migration.id in applied:
                continue
            statements = read_statements(migration.path)
            for stmt in statements:
                session.execute_write(lambda tx, s=stmt: tx.run(s).consume())  # type: ignore[misc]
            session.execute_write(
                lambda tx, mig_id=migration.id: tx.run(_RECORD_APPLIED, id=mig_id).consume()  # type: ignore[misc]
            )
            log(f"applied {migration.id} ({len(statements)} statements)")
            newly_applied.append(migration.id)
    return newly_applied


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    migrations_dir = Path(args[0]).resolve() if args else DEFAULT_MIGRATIONS_DIR
    with config.make_driver() as driver:
        applied = apply_all(driver, config.kg_database(), migrations_dir)
    print(f"{len(applied)} migration(s) newly applied from {migrations_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
