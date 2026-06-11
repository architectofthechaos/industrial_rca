"""Tests for the forward-only Cypher migration runner (Sprint 2a Task 3).

Hermetic tests cover statement splitting, `// @include` resolution (including cycle
detection), and migration discovery. The live test skips via the shared conftest
reachability marker (run `task kg:db:up` first).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from conftest import requires_kg

from rca_kg.migrate import apply_all, discover, read_statements

# --------------------------------------------------------------------------- hermetic


def test_read_statements_splits_on_semicolon_at_eol(tmp_path: Path) -> None:
    f = tmp_path / "0001_two.cypher"
    f.write_text(
        "// a comment line\n"
        "MERGE (a:Thing {id: 'x'})\n"
        "SET a.name = 'semi; not a terminator';\n"
        "\n"
        "// another comment\n"
        "MERGE (b:Thing {id: 'y'});\n"
        ";\n",  # blank statement is dropped
        encoding="utf-8",
    )
    stmts = read_statements(f)
    assert len(stmts) == 2
    assert stmts[0].startswith("MERGE (a:Thing")
    assert "semi; not a terminator" in stmts[0]  # mid-line ';' must not split
    assert stmts[1] == "MERGE (b:Thing {id: 'y'})"
    assert all("//" not in s for s in stmts)


def test_read_statements_resolves_include_relative_to_file(tmp_path: Path) -> None:
    (tmp_path / "seed").mkdir()
    (tmp_path / "migrations").mkdir()
    (tmp_path / "seed" / "x.cypher").write_text(
        "MERGE (s:Seeded {id: 'one'});\nMERGE (s:Seeded {id: 'two'});\n", encoding="utf-8"
    )
    mig = tmp_path / "migrations" / "0002_seed.cypher"
    mig.write_text("// header comment\n// @include ../seed/x.cypher\n", encoding="utf-8")
    stmts = read_statements(mig)
    assert stmts == ["MERGE (s:Seeded {id: 'one'})", "MERGE (s:Seeded {id: 'two'})"]


def test_read_statements_detects_include_cycles(tmp_path: Path) -> None:
    (tmp_path / "0001_a.cypher").write_text(
        "// @include 0002_b.cypher\nRETURN 1;\n", encoding="utf-8"
    )
    (tmp_path / "0002_b.cypher").write_text(
        "// @include 0001_a.cypher\nRETURN 2;\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="include cycle via"):
        read_statements(tmp_path / "0001_a.cypher")


def test_read_statements_allows_diamond_includes(tmp_path: Path) -> None:
    # 0001 includes b and c, both include shared: a diamond, NOT a cycle
    (tmp_path / "shared.cypher").write_text("MERGE (s:Shared {id: 'x'});\n", encoding="utf-8")
    (tmp_path / "b.cypher").write_text("// @include shared.cypher\n", encoding="utf-8")
    (tmp_path / "c.cypher").write_text("// @include shared.cypher\n", encoding="utf-8")
    (tmp_path / "0001_diamond.cypher").write_text(
        "// @include b.cypher\n// @include c.cypher\n", encoding="utf-8"
    )
    assert read_statements(tmp_path / "0001_diamond.cypher") == [
        "MERGE (s:Shared {id: 'x'})", "MERGE (s:Shared {id: 'x'})"]


def test_discover_sorts_by_leading_number_and_ignores_nonmatching(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "0002_b.cypher").write_text("RETURN 2;", encoding="utf-8")
    (tmp_path / "0001_a.cypher").write_text("RETURN 1;", encoding="utf-8")
    (tmp_path / "README.md").write_text("not a migration", encoding="utf-8")
    (tmp_path / "notes.cypher").write_text("RETURN 0;", encoding="utf-8")  # no NNNN_ prefix
    migrations = discover(tmp_path)
    assert [m.id for m in migrations] == ["0001_a", "0002_b"]
    assert [m.number for m in migrations] == [1, 2]
    assert [m.path.name for m in migrations] == ["0001_a.cypher", "0002_b.cypher"]
    err = capsys.readouterr().err  # misnamed .cypher warns; README.md stays silent
    assert "notes.cypher" in err and "README.md" not in err


# ------------------------------------------------------------------------------- live


@requires_kg
def test_apply_all_is_idempotent_and_records_applied_ids(tmp_path: Path) -> None:
    from rca_kg.config import kg_database, make_driver

    tok = uuid.uuid4().hex[:8]
    (tmp_path / f"0001_scratch_a_{tok}.cypher").write_text(
        f"MERGE (n:_KgMigrateScratch {{id: 'a-{tok}'}});\n", encoding="utf-8"
    )
    (tmp_path / f"0002_scratch_b_{tok}.cypher").write_text(
        f"MERGE (n:_KgMigrateScratch {{id: 'b-{tok}'}});\n", encoding="utf-8"
    )
    expected_ids = [f"0001_scratch_a_{tok}", f"0002_scratch_b_{tok}"]

    with make_driver() as driver:
        db = kg_database()
        try:
            first = apply_all(driver, db, tmp_path, log=lambda _msg: None)
            assert first == expected_ids
            second = apply_all(driver, db, tmp_path, log=lambda _msg: None)
            assert second == []  # second run applies zero

            with driver.session(database=db) as session:
                applied = session.execute_read(
                    lambda tx: tx.run(
                        "MATCH (m:_migrations {id: 'singleton'}) RETURN m.applied AS applied"
                    ).single()["applied"]
                )
                assert set(expected_ids) <= set(applied)
                count = session.execute_read(
                    lambda tx: tx.run(
                        "MATCH (n:_KgMigrateScratch) WHERE n.id ENDS WITH $tok "
                        "RETURN count(n) AS c",
                        tok=tok,
                    ).single()["c"]
                )
                assert count == 2
        finally:  # clean up the scratch namespace and our entries in the applied list
            with driver.session(database=db) as session:
                session.execute_write(
                    lambda tx: tx.run(
                        "MATCH (n:_KgMigrateScratch) WHERE n.id ENDS WITH $tok DETACH DELETE n",
                        tok=tok,
                    ).consume()
                )
                session.execute_write(
                    lambda tx: tx.run(
                        "MATCH (m:_migrations {id: 'singleton'}) "
                        "SET m.applied = [x IN m.applied WHERE NOT x ENDS WITH $tok]",
                        tok=tok,
                    ).consume()
                )
