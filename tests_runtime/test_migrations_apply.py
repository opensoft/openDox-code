"""The runner against a real Postgres: order, the ledger, and the two refusals.

DB-BACKED — runs in the `runtime` CI job. Skipped, with the reason printed,
where no `OPENDOX_TEST_DATABASE_URL` is reachable (see `conftest.py`).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from opendox.runtime import identity, migrations

ROOT = Path(__file__).resolve().parents[1]


def _tables_in(database, schema: str | None = None) -> set[str]:
    with database.connection() as conn:
        rows = conn.execute(
            "select table_name from information_schema.tables "
            "where table_schema = coalesce(%s, current_schema())",
            (schema,)).fetchall()
    return {row[0] for row in rows}


def test_applying_creates_exactly_the_six_tables_and_the_ledger(database) -> None:
    present = _tables_in(database)
    assert set(identity.TABLES) | {migrations.LEDGER_TABLE} == present, (
        "the applied schema and RULING Q1's list disagree; the `database` "
        "fixture applies every migration in `migrations/`")


def test_the_ledger_records_every_applied_migration_with_its_checksum(
        database) -> None:
    runner = migrations.MigrationRunner(database, migrations_dir=ROOT / "migrations")
    applied = {row.version: row for row in runner.applied()}
    discovered = {m.version: m for m in runner.discover()}
    assert set(applied) == set(discovered)
    for version, row in applied.items():
        assert row.checksum == discovered[version].checksum()
        assert row.name == discovered[version].name
        assert row.reversible == discovered[version].reversible


def test_applying_twice_is_a_no_op(database) -> None:
    runner = migrations.MigrationRunner(database, migrations_dir=ROOT / "migrations")
    assert runner.plan() == []
    assert runner.apply() == []


def test_the_plan_is_empty_after_apply_and_full_before_it(
        postgres_dsn: str) -> None:
    """A fresh schema plans every migration and then none."""
    import uuid

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
        try:
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations")
                assert [m.version for m in runner.plan()] == ["0001", "0002"]
                assert runner.apply() == ["0001", "0002"]
                assert runner.plan() == []
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")


def test_a_tampered_canonical_migration_applies_nothing_at_all(
        postgres_dsn: str, tmp_path: Path) -> None:
    """The gate runs BEFORE the first mutation, measured rather than asserted."""
    import uuid

    from opendox.runtime.db import Database

    for name in ("0001_identity_and_coordination.sql",
                 "0002_migration_state.sql"):
        shutil.copyfile(ROOT / "migrations" / name, tmp_path / name)
    tampered = tmp_path / "0001_identity_and_coordination.sql"
    tampered.write_text(tampered.read_text(encoding="utf-8") + "\n-- edited\n",
                        encoding="utf-8")

    schema = "t_" + uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
        try:
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(db, migrations_dir=tmp_path)
                with pytest.raises(migrations.CanonicalDigestMismatchError):
                    runner.apply()
                # Not even the ledger: the gate is before `bootstrap_ledger`.
                assert _tables_in(db, schema) == set()
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")


def test_editing_an_applied_migration_refuses_rather_than_reapplying(
        database, tmp_path: Path) -> None:
    """Drift between the tree and the database is reported, not papered over."""
    for name in ("0001_identity_and_coordination.sql",
                 "0002_migration_state.sql"):
        shutil.copyfile(ROOT / "migrations" / name, tmp_path / name)
    edited = tmp_path / "0002_migration_state.sql"
    edited.write_text(edited.read_text(encoding="utf-8") + "\n-- edited\n",
                      encoding="utf-8")
    runner = migrations.MigrationRunner(database, migrations_dir=tmp_path)
    with pytest.raises(migrations.MigrationChecksumDriftError) as caught:
        runner.apply()
    assert "0002" in str(caught.value)


def test_a_later_migration_is_applied_in_numeric_order(
        database, tmp_path: Path) -> None:
    """`0010` after `0002`, which is the whole point of numeric discovery."""
    for name in ("0001_identity_and_coordination.sql",
                 "0002_migration_state.sql"):
        shutil.copyfile(ROOT / "migrations" / name, tmp_path / name)
    (tmp_path / "0010_additive_probe.sql").write_text(
        "alter table projects add column probe text;\n", encoding="utf-8")
    runner = migrations.MigrationRunner(database, migrations_dir=tmp_path)
    assert runner.apply() == ["0010"]
    with database.connection() as conn:
        columns = conn.execute(
            "select column_name from information_schema.columns "
            "where table_schema = current_schema() and table_name = 'projects'"
        ).fetchall()
    assert "probe" in {row[0] for row in columns}
