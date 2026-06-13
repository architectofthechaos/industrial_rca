"""Test-safety guard: a destructive op (downgrade/DELETE/DROP) must only ever run against a
throwaway database whose name starts with ``test_`` (WI3). Importing/using this in production code
paths is harmless; it only raises for destructive *test* helpers pointed at a non-test DB."""
from __future__ import annotations

from urllib.parse import urlsplit


class NonTestDatabaseError(RuntimeError):
    pass


def database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def is_test_database(url: str) -> bool:
    return database_name(url).startswith("test_")


def assert_test_database(url: str) -> None:
    name = database_name(url)
    if not name.startswith("test_"):
        raise NonTestDatabaseError(
            f"refusing destructive DB op against non-test database {name!r} "
            f"(name must start with 'test_'); set DATABASE_URL to a throwaway DB")
