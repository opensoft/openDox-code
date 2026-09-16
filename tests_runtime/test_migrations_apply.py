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


# ---------------------------------------------------------------------------
# the review round's own assertions (Copilot review of openDox-code#25)
# ---------------------------------------------------------------------------


def test_a_run_holds_the_advisory_lock_and_a_second_one_waits(
        postgres_dsn: str) -> None:
    """Two deploys must not both apply `0001`.

    The gate, the ledger bootstrap, the ledger read and the per-migration
    transactions are four separate statements; two runs that both saw an empty
    ledger would both start applying, and one would fail on objects the other
    had created. This holds the run's advisory lock from ANOTHER session and
    measures that `apply()` does not proceed until it is released — which is
    the serialization, not a statement about it.
    """
    import threading
    import uuid

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    finished = threading.Event()
    error: list[BaseException] = []

    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
        blocker = Database(postgres_dsn, application_name="opendox-test-blocker")
        try:
            with blocker, blocker.connection() as held:
                held.execute("select pg_advisory_lock(%s)",
                             (migrations.MIGRATION_LOCK_KEY,))

                def _run() -> None:
                    try:
                        with Database(postgres_dsn, schema=schema) as db:
                            migrations.MigrationRunner(
                                db, migrations_dir=ROOT / "migrations").apply()
                    except BaseException as exc:  # noqa: BLE001 - reported below
                        error.append(exc)
                    finally:
                        finished.set()

                worker = threading.Thread(target=_run, daemon=True)
                worker.start()
                assert not finished.wait(timeout=2.0), (
                    "the migration run completed while another session held "
                    f"advisory lock {migrations.MIGRATION_LOCK_KEY}; the run "
                    "is not serialized")
                with Database(postgres_dsn, schema=schema) as probe:
                    assert _tables_in(probe, schema) == set(), (
                        "the blocked run created objects before taking the lock")
                held.execute("select pg_advisory_unlock(%s)",
                             (migrations.MIGRATION_LOCK_KEY,))
            # The lock is released with the `with` above; the run may proceed.
            assert finished.wait(timeout=30.0), "the run never completed"
            worker.join(timeout=30.0)
            assert not worker.is_alive(), (
                "the worker outlived the wait; the schema is dropped below and "
                "a run that outlived it would create its tables in `public`")
            assert not error, error
            with Database(postgres_dsn, schema=schema) as db:
                assert _tables_in(db, schema) == (
                    set(identity.TABLES) | {migrations.LEDGER_TABLE})
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")


def test_the_lock_is_released_after_a_run(database) -> None:
    """A released lock is what makes a retry in the same process immediate."""
    migrations.MigrationRunner(
        database, migrations_dir=ROOT / "migrations").apply()
    with database.connection() as conn:
        held = conn.execute(
            "select count(*) from pg_locks where locktype = 'advisory' "
            "and ((classid::bigint << 32) | objid::bigint) = %s",
            (migrations.MIGRATION_LOCK_KEY,)).fetchone()
    assert held[0] == 0, "the run left its advisory lock held"


def test_a_duplicate_slug_race_is_a_conflict_and_not_a_raw_database_error(
        database) -> None:
    """Two transactions whose pre-checks both pass; the loser must get 409.

    `create_project` reads before it inserts, which is not atomic. This drives
    the race directly — two connections, both pre-checks answered before either
    insert — and asserts the loser sees `identity.ConflictError`, which is what
    `app.py` maps to 409. Before the unique-violation translation it saw the
    driver's raw error and the API answered 500.
    """
    from opendox.runtime.identity import ConflictError, CoordinationStore

    with database.transaction() as conn:
        owner = CoordinationStore(conn).upsert_user(
            issuer="https://broker.test/realms/opendox", subject="racer")

    with database.connection() as first, database.connection() as second:
        one = CoordinationStore(first)
        two = CoordinationStore(second)
        # Both pre-checks happen before either insert.
        assert one.list_projects() == two.list_projects()
        one.create_project(slug="raced", title="One", created_by=owner.id)
        first.commit()
        with pytest.raises(ConflictError) as caught:
            two.create_project(slug="raced", title="Two", created_by=owner.id)
        second.rollback()
    assert "raced" in str(caught.value)


def test_the_served_role_cannot_rewrite_the_ledger_after_a_run(
        postgres_dsn: str) -> None:
    """The runner's record is the runner's, not the API's.

    A served role that could INSERT, UPDATE or DELETE `opendox_schema_
    migrations` could hide an applied migration or manufacture one, after which
    the fail-closed drift check would be checking a story the API wrote. SELECT
    is kept, because `/readyz` reads the ledger.
    """
    import uuid

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    role = "t_role_" + uuid.uuid4().hex[:8]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
            conn.execute(f"create role {role}")
            conn.execute(f"grant usage on schema {schema} to {role}")
            conn.execute(
                f"alter default privileges in schema {schema} "
                f"grant select, insert, update, delete on tables to {role}")
        try:
            with Database(postgres_dsn, schema=schema) as db:
                migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations",
                    runtime_role=role).apply()
                with db.connection() as conn:
                    granted = {
                        row[0] for row in conn.execute(
                            "select privilege_type from "
                            "information_schema.table_privileges "
                            "where grantee = %s and table_name = %s",
                            (role, migrations.LEDGER_TABLE)).fetchall()}
                    on_users = {
                        row[0] for row in conn.execute(
                            "select privilege_type from "
                            "information_schema.table_privileges "
                            "where grantee = %s and table_name = 'users'",
                            (role,)).fetchall()}
            assert granted == {"SELECT"}, (
                f"the served role holds {sorted(granted)} on the ledger; only "
                "SELECT may survive a run")
            # ...and the coordination tables are untouched, which is what makes
            # this a narrowing and not a lockout.
            assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= on_users
        finally:
            with admin.transaction() as conn:
                # The default-privileges entry references the schema, so it
                # goes FIRST; dropping the schema first leaves a grant naming
                # something that no longer exists and the cleanup fails.
                conn.execute(
                    f"alter default privileges in schema {schema} "
                    f"revoke all on tables from {role}")
                conn.execute(f"revoke usage on schema {schema} from {role}")
                conn.execute(f"drop schema if exists {schema} cascade")
                conn.execute(f"drop role if exists {role}")


def test_the_ledger_narrowing_refuses_a_role_name_that_is_not_an_identifier(
        database) -> None:
    """A role name reaches a `revoke` as SYNTAX and cannot be a parameter."""
    runner = migrations.MigrationRunner(
        database, migrations_dir=ROOT / "migrations",
        runtime_role='evil"; drop table users; --')
    with pytest.raises(migrations.MigrationError) as caught:
        runner.protect_ledger()
    assert "plain SQL identifier" in str(caught.value)


def test_status_reports_a_reachable_database_and_its_applied_migrations(
        database, postgres_dsn: str, monkeypatch) -> None:
    """The defect only a live database shows.

    `status` used `runner.applied()` and `runner.plan()` after the `Database`
    context had closed its pool, so `PoolClosed` was caught by the verb's own
    except clause and a perfectly reachable database was reported unreachable.
    Every unreachable-database test passed throughout.
    """
    import io
    import json
    from contextlib import redirect_stdout

    from opendox.runtime import cli
    from opendox.runtime.config import PREFIX

    # `status` builds its OWN `Database` from the DSN, so the test's schema has
    # to travel IN the DSN — `options=-c search_path=…`, which is the same
    # libpq startup parameter `Database(schema=…)` sets for the harness.
    scoped = (f"{postgres_dsn}?options=-c%20search_path%3D{database.schema}")
    monkeypatch.setenv(PREFIX + "DATABASE_URL", scoped)
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker.test/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
    monkeypatch.setenv(PREFIX + "MIGRATIONS_DIR", str(ROOT / "migrations"))
    args = cli.build_parser().parse_args(
        ["runtime", "status", "--probe-timeout", "5"])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        args.func(args)
    report = json.loads(buffer.getvalue())
    assert report["database"] == "reachable", report
    # The fixture applied both migrations into this test's own schema; `status`
    # reads them through the same search path.
    assert report["applied_migrations"] == ["0001", "0002"], report
    assert report["pending_migrations"] == [], report
