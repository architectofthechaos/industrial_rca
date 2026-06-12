import pytest
from rca_mar._safety import assert_test_database, NonTestDatabaseError


def test_guard_allows_test_database():
    assert_test_database("postgresql+asyncpg://rca:rca@127.0.0.1:5432/test_rca_mar")  # no raise


def test_guard_rejects_live_database():
    with pytest.raises(NonTestDatabaseError):
        assert_test_database("postgresql+asyncpg://rca:rca@127.0.0.1:5432/rca_mar")


def test_guard_rejects_prod_like_names():
    for db in ("rca_mar", "rca", "production", "rca_mar_prod"):
        with pytest.raises(NonTestDatabaseError):
            assert_test_database(f"postgresql+asyncpg://rca:rca@h:5432/{db}")
