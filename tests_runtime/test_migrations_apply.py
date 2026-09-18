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


def test_drift_sees_what_plan_cannot(database, tmp_path: Path) -> None:
    """`plan()` compares VERSIONS. A changed or deleted file is invisible to it
    and is refused by `apply()`, so readiness that trusted `plan()` alone
    called a database healthy that the runner would not migrate."""
    for name in ("0001_identity_and_coordination.sql",
                 "0002_migration_state.sql"):
        shutil.copyfile(ROOT / "migrations" / name, tmp_path / name)
    runner = migrations.MigrationRunner(database, migrations_dir=tmp_path)
    assert runner.plan() == []
    assert runner.drift() == []

    edited = tmp_path / "0002_migration_state.sql"
    edited.write_text(edited.read_text(encoding="utf-8") + "\n-- edited\n",
                      encoding="utf-8")
    assert runner.plan() == [], "plan() should still see nothing pending"
    assert runner.drift() == ["0002:changed"]

    edited.unlink()
    assert runner.plan() == []
    assert runner.drift() == ["0002:missing"]


def test_a_run_refuses_when_the_ledger_names_a_file_the_tree_lacks(
        database, tmp_path: Path) -> None:
    """A deleted migration must not be indistinguishable from a valid no-op."""
    shutil.copyfile(ROOT / "migrations" / "0001_identity_and_coordination.sql",
                    tmp_path / "0001_identity_and_coordination.sql")
    runner = migrations.MigrationRunner(database, migrations_dir=tmp_path)
    with pytest.raises(migrations.MigrationError) as caught:
        runner.apply()
    assert "0002" in str(caught.value)
    assert "does not contain" in str(caught.value)


def test_the_ledger_is_resolved_in_this_schema_and_not_through_public(
        postgres_dsn: str) -> None:
    """`search_path` is `<schema>,public`.

    An unqualified `to_regclass` therefore found a ledger in `public` when the
    selected schema had none, and a FRESH schema was reported fully migrated.
    """
    import uuid

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
            # A ledger in `public`, which is what the old lookup would find.
            conn.execute("create table if not exists public."
                         f"{migrations.LEDGER_TABLE} (version text primary key, "
                         "name text not null, checksum text not null, "
                         "reversible boolean not null default false, "
                         "applied_at timestamptz not null default now())")
            conn.execute(
                f"insert into public.{migrations.LEDGER_TABLE} "
                "(version, name, checksum) values ('0001','x','y'), "
                "('0002','x','y') on conflict do nothing")
        try:
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations")
                assert runner.applied() == [], (
                    "the ledger was read through `public`; a fresh schema "
                    "would be reported fully migrated")
                assert [m.version for m in runner.plan()] == ["0001", "0002"]
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")
                conn.execute(
                    f"drop table if exists public.{migrations.LEDGER_TABLE}")


def test_a_run_does_its_whole_work_on_the_connection_that_holds_the_lock(
        postgres_dsn: str) -> None:
    """A POOL OF ONE, which the old shape could not finish at all.

    `apply()` takes `MIGRATION_LOCK_KEY` on a connection and then used to do
    the bootstrap, the ledger read and every migration through
    `Database.transaction()`, which checks out a DIFFERENT connection. A
    session-level advisory lock protects only the session that took it, so two
    runners could each hold their own lock session and race through the same
    schema work (Copilot review of openDox-code#25).

    The regression is measurable WITHOUT a race: with `max_size=1` the lock
    holds the only connection in the pool, so the old shape blocked on its own
    checkout until `checkout_timeout` and raised. A run that completes here is
    a run whose every statement went through the lock's own session.
    """
    import uuid

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
        try:
            with Database(postgres_dsn, schema=schema, min_size=1, max_size=1,
                          checkout_timeout=5.0) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations")
                applied = runner.apply()
                assert applied == [m.version for m in runner.discover()]
                assert runner.plan() == []
                assert (set(identity.TABLES) | {migrations.LEDGER_TABLE}
                        <= _tables_in(db))
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")


def test_a_ledger_that_cannot_be_protected_applies_no_migration_at_all(
        postgres_dsn: str) -> None:
    """The narrowing is a PRECONDITION of the run, not its last step.

    When `protect_ledger()` ran after the loop, a `runtime_role` the database
    does not have failed the run only once every migration and its ledger
    INSERT had committed — and `/readyz` asks about schema and drift, never
    about grants, so the install could go on serving with the SERVED role still
    able to rewrite the runner's tamper-evident record (Copilot review of
    openDox-code#25). Now the run refuses before it applies anything, which is
    the state an operator can act on.
    """
    import uuid

    import psycopg

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    absent_role = "t_absent_" + uuid.uuid4().hex[:8]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
        try:
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations",
                    runtime_role=absent_role)
                with pytest.raises(psycopg.errors.UndefinedObject):
                    runner.apply()
                # The ledger exists (it is bootstrapped before the narrowing is
                # attempted) and records NOTHING, and no coordination table was
                # created.
                assert runner.applied() == []
                assert _tables_in(db) == {migrations.LEDGER_TABLE}
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")


def test_reset_drops_in_this_schema_only_and_never_through_public(
        postgres_dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`runtime reset` promises "this schema's coordination state, and nothing
    else" — and an UNQUALIFIED drop cannot keep that promise.

    `search_path` is `<schema>,public`, so `drop table if exists users` in a
    schema that has no `users` resolved through the fallback and dropped
    `public.users`: a confirmed reset of one tenant's schema silently dropping
    another's table (Copilot review of openDox-code#25, round 5). The same
    fallback `MigrationRunner.applied` is qualified against, one verb over.

    MEASURED THE WAY THE DEFECT WOULD APPEAR: a table named `users` in
    `public`, a fresh schema that has none of the coordination tables but one,
    and a reset whose DSN selects that schema.
    """
    import io
    import json
    import uuid
    from contextlib import redirect_stdout

    from opendox.runtime import cli
    from opendox.runtime.config import PREFIX
    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    canary = "public_users_" + uuid.uuid4().hex[:8]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
            # The table the search-path fallback would reach. Its own column
            # name is unique to this test, so nothing here can be confused
            # with a real `users` table if one is ever left behind.
            conn.execute(f"create table public.users ({canary} text)")
            # And ONE coordination table that really is in the schema, so the
            # run has something of its own to drop and the assertion below is
            # about WHERE the drop landed, not whether it ran.
            conn.execute(f"create table {schema}.projects (id text)")
        try:
            separator = "&" if "?" in postgres_dsn else "?"
            # libpq percent-decodes a URI's query, so `%3D` is `=` and `%2C`
            # is `,`: `options=-csearch_path=<schema>,public`. This is the
            # shape a tenant-scoped install's DSN has, which is the only way
            # the fallback is reachable at all.
            monkeypatch.setenv(
                PREFIX + "MIGRATION_DATABASE_URL",
                f"{postgres_dsn}{separator}"
                f"options=-csearch_path%3D{schema}%2Cpublic")
            args = cli.build_parser().parse_args(
                ["runtime", "reset", "--confirm", cli.RESET_CONFIRMATION])
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = args.func(args)
            evidence = json.loads(buffer.getvalue())
            assert code == 0, evidence
            assert evidence["schema"] == schema, (
                "the evidence must say WHICH schema was dropped from")

            with admin.connection() as conn:
                surviving = conn.execute(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'users'"
                ).fetchall()
                assert [row[0] for row in surviving] == [canary], (
                    "`public.users` was dropped by a reset of another schema")
                own = conn.execute(
                    "select table_name from information_schema.tables "
                    "where table_schema = %s", (schema,)).fetchall()
                assert own == [], (
                    f"the reset left {[r[0] for r in own]} in its own schema")
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")
                conn.execute("drop table if exists public.users")


def test_a_narrowing_that_changes_nothing_fails_the_run(
        postgres_dsn: str) -> None:
    """`revoke` succeeds and changes nothing for the ledger's OWNER.

    Point both DSNs at the migration identity — the accident this separation
    exists to survive — and the run used to report a narrowed ledger that the
    served identity could still rewrite, because a role cannot be revoked out
    of privileges it holds by ownership (the same is true of a superuser, and
    of a role holding the write through another grant). The run now ASKS
    Postgres whether the narrowing took effect and fails when it did not
    (Copilot review of openDox-code#25, round 6).
    """
    import uuid

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
            owner_row = conn.execute("select current_user").fetchone()
        owner = owner_row[0]
        try:
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations",
                    runtime_role=owner)
                with pytest.raises(
                        migrations.LedgerNarrowingIneffectiveError) as caught:
                    runner.apply()
                assert "INSERT" in str(caught.value)
                assert owner in str(caught.value)
                # The narrowing is a PRECONDITION of the run, so nothing was
                # applied: the ledger is bootstrapped and empty, and no
                # coordination table exists.
                assert runner.applied() == []
                assert _tables_in(db) == {migrations.LEDGER_TABLE}
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")


def test_a_role_whose_name_is_not_lower_case_is_narrowed_as_itself(
        postgres_dsn: str) -> None:
    """Postgres FOLDS an unquoted identifier and the bootstrap quotes one.

    `_ROLE_NAME` and `_PLAIN_IDENTIFIER` both accept upper case, so a
    configured `MyRole` had its revoke and grant aimed at `myrole` — a
    different role, or none at all, with the ledger narrowing silently missing
    its subject (Copilot review of openDox-code#25, round 7).
    """
    import uuid

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    role = "OpenDoxRuntime" + uuid.uuid4().hex[:6]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
            # Created QUOTED, exactly as the compose and Kubernetes bootstrap
            # scripts create it (`%I`), so the role really carries upper case.
            # A literal password: `create role` takes no parameters (it is
            # not a plannable statement), and this role is dropped below.
            conn.execute(
                f'create role "{role}" login password ' "'throwaway-local'")
            # AND GRANTED, because `verify_runtime_access` is now the last act
            # of a run: a served role that cannot use the schema the run
            # applied fails the run (Copilot review of openDox-code#25, round
            # 12). This test is about the case of the NAME, so it grants the
            # rights a real install grants and keeps its own subject.
            conn.execute(f'grant usage on schema {schema} to "{role}"')
            conn.execute(
                f"alter default privileges in schema {schema} "
                f'grant select, insert, update, delete on tables to "{role}"')
        try:
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations", runtime_role=role)
                runner.apply()
                with db.connection() as conn:
                    for privilege, expected in (("INSERT", False),
                                                ("SELECT", True)):
                        answer = conn.execute(
                            "select has_table_privilege(%s, %s, %s)",
                            (role, migrations.LEDGER_TABLE,
                             privilege)).fetchone()
                        assert answer and answer[0] is expected, privilege
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")
                conn.execute(f'drop role if exists "{role}"')


def test_status_calls_an_unmigrated_database_unhealthy_and_blames_the_tree(
        postgres_dsn: str, monkeypatch, tmp_path) -> None:
    """Two findings of one round, both about `status` telling the truth.

    A reachable but UNMIGRATED database exited 0 with `ok: true` while
    `/readyz` on the same install refuses traffic — two answers to one
    question, and the CLI's was the comforting one. And a `MigrationError`
    (a missing or malformed migrations directory) was reported as
    `database: unreachable`, although `select 1` had already succeeded: the
    operator was pointed at the wrong dependency entirely (Copilot review of
    openDox-code#25, round 7, suppressed).
    """
    import io
    import json
    import uuid
    from contextlib import redirect_stdout

    from opendox.runtime import cli
    from opendox.runtime.config import PREFIX
    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    separator = "&" if "?" in postgres_dsn else "?"
    scoped = (f"{postgres_dsn}{separator}"
              f"options=-csearch_path%3D{schema}%2Cpublic")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
        try:
            monkeypatch.setenv(PREFIX + "DATABASE_URL", scoped)
            monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
            monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
            monkeypatch.setenv(PREFIX + "MIGRATIONS_DIR", str(ROOT / "migrations"))

            def _status() -> tuple[int, dict]:
                buffer = io.StringIO()
                args = cli.build_parser().parse_args(
                    ["runtime", "status", "--probe-timeout", "2"])
                with redirect_stdout(buffer):
                    code = args.func(args)
                return code, json.loads(buffer.getvalue())

            code, report = _status()
            assert report["database"] == "reachable"
            assert report["pending_migrations"] == ["0001", "0002"]
            assert report["ok"] is False and code == 1, report

            # And a tree the runner cannot read blames the TREE.
            empty = tmp_path / "no-migrations"
            empty.mkdir()
            monkeypatch.setenv(PREFIX + "MIGRATIONS_DIR", str(empty))
            code, report = _status()
            assert report["database"] == "reachable", report
            assert report["migrations"].startswith("unreadable: "), report
            assert report["ok"] is False and code == 1
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")


# -- Copilot's twelfth round on #25 -------------------------------------------


def test_a_run_whose_served_role_was_never_granted_fails_instead_of_serving(
        postgres_dsn: str) -> None:
    """A skipped prerequisite used to surface as the first request, not the run.

    `alter default privileges` belongs to the role that CREATES the table, and
    the bundled bootstrap runs as `$POSTGRES_USER`; the migration DSN is
    configured separately. Point it at another owner — or run a managed
    database whose operator skipped the documented prerequisite — and the run
    created the six tables with no privilege for the served role at all: the
    Job succeeded, `/readyz` reported a reachable database and an applied
    schema, and every API query failed `permission denied for table …` (Copilot
    review of openDox-code#25, round 12). The run asks Postgres instead.
    """
    import uuid

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    role = "t_ungranted_" + uuid.uuid4().hex[:8]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
            # The role EXISTS and can reach the ledger, so `protect_ledger`
            # succeeds: what is missing is exactly the grant the bootstrap
            # would have made on the tables this run creates.
            conn.execute(f"create role {role}")
            conn.execute(f"grant usage on schema {schema} to {role}")
        try:
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations", runtime_role=role)
                # A `MigrationError` FIRST, which exists in both shapes: what
                # fails against the old one is that the run SUCCEEDS, not that
                # a name is missing.
                with pytest.raises(migrations.MigrationError) as caught:
                    runner.apply()
            assert isinstance(caught.value, migrations.RuntimeAccessMissingError)
            message = str(caught.value)
            assert role in message
            for expected in ("users:SELECT", "users:INSERT", "sessions:UPDATE",
                             "drafts:DELETE"):
                assert expected in message, (expected, message)
            # The LEDGER is not among them: `protect_ledger` has just taken
            # three of those four away from it on purpose.
            assert f"{migrations.LEDGER_TABLE}:" not in message, message
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")
                conn.execute(f"drop role if exists {role}")


def test_a_migrations_directory_rewritten_mid_run_runs_the_bytes_it_gated(
        postgres_dsn: str, tmp_path: Path) -> None:
    """The gate's "nothing at all" used to mean "the ledger and its grants".

    `verify_canonical_digest()` hashed `0001`; `bootstrap_ledger()` and
    `protect_ledger()` then COMMITTED; and only the loop's re-read raised
    `CanonicalDigestMismatchError`. A directory that changes under the process
    — which this runner supports by design — therefore left the ledger table
    and its privilege changes behind on a run that refused (Copilot review of
    openDox-code#25, round 12). `snapshot_run()` reads every file and runs the
    gate BEFORE the first commit, so a rewrite from that moment on is not part
    of this run at all: it completes on the bytes it gated, and the ledger
    records their digest — the pin.

    Measured both ways before it was written: against the old shape this raises
    `CanonicalDigestMismatchError` and leaves `opendox_schema_migrations`
    behind as the only table in the schema.
    """
    import uuid

    from opendox.runtime.db import Database

    for name in ("0001_identity_and_coordination.sql",
                 "0002_migration_state.sql"):
        shutil.copyfile(ROOT / "migrations" / name, tmp_path / name)
    canonical = tmp_path / "0001_identity_and_coordination.sql"

    schema = "t_" + uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
        try:
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(db, migrations_dir=tmp_path)
                bootstrap = runner.bootstrap_ledger

                def _rewrite_then_bootstrap(conn=None):
                    canonical.write_bytes(b"create table intruder ();\n")
                    return bootstrap(conn)

                runner.bootstrap_ledger = _rewrite_then_bootstrap  # type: ignore[method-assign]
                applied = runner.apply()

                assert applied == ["0001", "0002"], applied
                assert canonical.read_bytes() == b"create table intruder ();\n", (
                    "the rewrite did not happen, so this test measured nothing")
                present = _tables_in(db, schema)
                assert "intruder" not in present, (
                    "the rewritten bytes were executed")
                assert set(identity.TABLES) | {migrations.LEDGER_TABLE} <= present
                recorded = {row.version: row.checksum for row in runner.applied()}
                assert (recorded["0001"]
                        == migrations.CANONICAL_MIGRATION_SHA256), (
                    "the ledger recorded the digest of bytes that did not run")
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")


def test_a_selected_schema_that_does_not_exist_is_refused_not_answered(
        postgres_dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`current_schema()` IS the fallback this qualification was defending against.

    It answers the first EXISTING schema on the path, never the first
    configured one — so a DSN selecting a `tenant` that was dropped, renamed or
    never created qualified every statement as `public.*`: `applied()` reported
    another schema's ledger as this one's, and `reset`, whose whole promise is
    "this schema's coordination state and nothing else", dropped `public`'s
    coordination tables (Copilot review of openDox-code#25, round 14, reported
    in both places).

    MEASURED THE WAY THE DEFECT WOULD APPEAR: a `users` table in `public`, a
    schema that is never created, and a DSN that selects it.
    """
    import io
    import json
    import uuid
    from contextlib import redirect_stdout

    from opendox.runtime import cli
    from opendox.runtime.config import PREFIX
    from opendox.runtime.db import Database

    missing = "t_" + uuid.uuid4().hex[:12]          # never created
    canary = "public_users_" + uuid.uuid4().hex[:8]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create table public.users ({canary} text)")
        try:
            # THE RUN REFUSES BEFORE IT WRITES ANYTHING. `bootstrap_ledger`'s
            # `create table` is unqualified — which is right, it must land
            # where the path selects — so on a connection whose selected schema
            # is gone it created the ledger in `public` and COMMITTED, and the
            # guard in `applied()` ran afterwards: a fail-closed run that had
            # already mutated another schema (Copilot review of
            # openDox-code#25, round 15).
            before = _tables_in(admin, "public")
            with Database(postgres_dsn, schema=missing) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations")
                with pytest.raises(migrations.MigrationError):
                    runner.apply()
            assert _tables_in(admin, "public") == before, (
                "the refused run created tables in `public`")
            assert migrations.LEDGER_TABLE not in _tables_in(admin, "public")

            # The reader refuses rather than reading `public`'s ledger.
            with Database(postgres_dsn, schema=missing) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations")
                with pytest.raises(migrations.MigrationError) as caught:
                    runner.applied()
            assert missing in str(caught.value)
            assert "public" in str(caught.value)

            # And the verb that DROPS refuses before it drops anything.
            separator = "&" if "?" in postgres_dsn else "?"
            monkeypatch.setenv(
                PREFIX + "MIGRATION_DATABASE_URL",
                f"{postgres_dsn}{separator}"
                f"options=-csearch_path%3D{missing}%2Cpublic")
            args = cli.build_parser().parse_args(
                ["runtime", "reset", "--confirm", cli.RESET_CONFIRMATION])
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = args.func(args)
            evidence = json.loads(buffer.getvalue())
            assert code != 0, evidence
            assert evidence["refusal"] == "MigrationError", evidence
            assert missing in evidence["message"]

            with admin.connection() as conn:
                surviving = conn.execute(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'users'"
                ).fetchall()
                assert [row[0] for row in surviving] == [canary], (
                    "`public.users` was dropped by a reset whose own schema "
                    "does not exist")
        finally:
            with admin.transaction() as conn:
                conn.execute("drop table if exists public.users")


def test_the_access_preflight_asks_about_this_runtimes_tables_and_the_schema(
        postgres_dsn: str) -> None:
    """Two findings in one check, and they pull in opposite directions.

    It scanned EVERY ordinary table in the selected schema, so a table that has
    nothing to do with this runtime — another application sharing the schema,
    an operator's scratch table — failed the migration run for a privilege the
    served role was never meant to hold. And it asked `has_table_privilege`
    alone, which no amount of table grants makes sufficient: without `usage` on
    the SCHEMA a role cannot name those tables at all, so a run could pass this
    check and every API query still fail `permission denied for schema`
    (Copilot review of openDox-code#25, round 15, suppressed).

    Measured both ways in one schema: a stranger's table the served role cannot
    touch, and the same role with and without `usage`.
    """
    import uuid

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    role = "t_scoped_" + uuid.uuid4().hex[:8]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
            conn.execute(f"create role {role}")
            conn.execute(f"grant usage on schema {schema} to {role}")
            # A STRANGER'S TABLE, created BEFORE the default privileges so the
            # served role holds nothing on it — which is the whole point: it is
            # not this runtime's table.
            conn.execute(f"create table {schema}.somebody_elses (id text)")
            conn.execute(
                f"alter default privileges in schema {schema} "
                f"grant select, insert, update, delete on tables to {role}")
        try:
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations", runtime_role=role)
                # It applies: the stranger's table is not this runtime's to
                # have rights on. Against the previous head this raised
                # `RuntimeAccessMissingError` naming `somebody_elses`.
                assert runner.apply() == ["0001", "0002"]

            # AND THE SCHEMA'S OWN `usage` IS ASKED. Take it away and the same
            # run refuses, naming the schema — against the previous head it
            # passed, because every table privilege was still held.
            with admin.transaction() as conn:
                conn.execute(f"revoke usage on schema {schema} from {role}")
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations", runtime_role=role)
                with pytest.raises(migrations.RuntimeAccessMissingError) as caught:
                    runner.verify_runtime_access()
            assert "USAGE" in str(caught.value)
            assert schema in str(caught.value)
            assert role in str(caught.value)

            # AND A TABLE THAT IS NOT THERE IS REPORTED MISSING. The query is
            # driven by `pg_class`, so a dropped coordination table produced no
            # row and was never added to `missing` — a rerun after `users` was
            # removed reported success and the API failed on the relation later
            # (Copilot review of openDox-code#25, round 16, suppressed).
            # Restricting the scan to the coordination tables in the same round
            # is what made the gap reachable.
            with admin.transaction() as conn:
                conn.execute(f"grant usage on schema {schema} to {role}")
                conn.execute(f"drop table {schema}.users cascade")
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations", runtime_role=role)
                with pytest.raises(migrations.RuntimeAccessMissingError) as gone:
                    runner.verify_runtime_access()
            assert "missing users" in str(gone.value), str(gone.value)
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")
                conn.execute(f"drop owned by {role}")
                conn.execute(f"drop role if exists {role}")


def test_a_selected_schema_this_role_may_not_use_is_refused_not_answered(
        postgres_dsn: str) -> None:
    """"Exists" is not the question PostgreSQL asks of a `search_path` entry.

    Round 16 made the walk cover the whole configured path and probed the
    skipped entries against `pg_namespace`. That probe proves the schema is
    THERE; `search_path` resolution asks whether THIS ROLE may use it, and
    PostgreSQL skips an entry without `usage` exactly as it skips an absent
    one. So an existing but unauthorized `tenant` left `missing` empty, the
    fallback `public` was accepted, and every statement of the run went to
    `public` — which in a multi-tenant install is the isolation failure the
    grant exists to prevent (Copilot review of openDox-code#25, round 19).

    Driven against a real server, because the claim is about the server: a
    schema that exists, a role that holds no grant on it, and the DSN that
    selects it.

    AGAINST THE PREVIOUS HEAD THIS RUN DOES NOT REFUSE. It accepts `public`
    and proceeds, and what stops it is `psycopg.errors.InsufficientPrivilege:
    permission denied for schema public` — an ACCIDENT of this role's grants,
    from a run that was already writing into the wrong schema. A role that does
    hold `public` (the default on a plain install, where `public` is world-
    writable before PG15 and often re-granted after it) gets no error at all:
    the coordination tables land in `public` and the run reports success.
    """
    import uuid

    from psycopg.conninfo import make_conninfo

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    role = "r_" + uuid.uuid4().hex[:12]
    secret = uuid.uuid4().hex
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.connection() as conn:
            database = conn.execute("select current_database()").fetchone()[0]
        with admin.transaction() as conn:
            # Every identifier here is generated above from a uuid or read back
            # from the server; none of it is input.
            conn.execute(f"create schema {schema}")
            conn.execute(f"create role {role} login password '{secret}'")
            conn.execute(f"grant connect on database {database} to {role}")
            conn.execute(f"revoke all on schema {schema} from public")
        try:
            as_role = make_conninfo(postgres_dsn, user=role, password=secret)

            # THE PREMISE, MEASURED FIRST: the schema is there, this role may
            # not use it, and PostgreSQL therefore answers `public`.
            with Database(as_role, schema=schema) as db, db.connection() as c:
                assert c.execute("select current_schema()").fetchone()[0] == \
                    "public"
                assert c.execute(
                    "select count(*) from pg_catalog.pg_namespace where "
                    "nspname = %s", (schema,)).fetchone()[0] == 1
                assert c.execute(
                    "select has_schema_privilege(current_user, %s, 'usage')",
                    (schema,)).fetchone()[0] is False

            before = _tables_in(admin, "public")
            with Database(as_role, schema=schema) as db:
                runner = migrations.MigrationRunner(
                    db, migrations_dir=ROOT / "migrations")
                with pytest.raises(migrations.MigrationError) as caught:
                    runner.apply()
            message = str(caught.value)
            assert schema in message and "public" in message
            assert "may not USE" in message, message
            assert _tables_in(admin, "public") == before, (
                "the refused run wrote into `public`, which is the schema the "
                "fallback chose and not the one the DSN selected")

            # THE OTHER SIDE OF THE RULE: the grant is what was missing, and
            # with it the same connection is answered rather than refused.
            with admin.transaction() as conn:
                conn.execute(f"grant usage on schema {schema} to {role}")
            with Database(as_role, schema=schema) as db, db.connection() as c:
                assert migrations.selected_schema(c) == schema
                assert c.execute("select current_schema()").fetchone()[0] == \
                    schema
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")
                conn.execute(f"drop owned by {role}")
                conn.execute(f"drop role if exists {role}")


def test_the_draft_page_budget_does_not_read_the_bodies_it_sizes(
        postgres_dsn: str) -> None:
    """ANSWERED BY MEASUREMENT, twice reported, and no change.

    The review holds that `octet_length(d.body)` forces PostgreSQL to
    detoast every candidate body before the window can compute `bytes_before`,
    so a page of 500 one-megabyte drafts still makes the database process ~500
    MB and only the client transfer is bounded (Copilot review of
    openDox-code#25, round 19 and again at the head before it).

    It does not. `textoctetlen` takes the raw length out of the varlena header
    — `toast_raw_datum_size`, which reads a TOAST POINTER and not the chunks it
    points at. MEASURED on postgres 16.15 over 200 rows of 1 MiB of
    incompressible ASCII, a 208 MB relation, best of three:

        sum(octet_length(body))                  0.3 ms
        count(*)                                 0.3 ms
        this act's windowed inner query          0.7 ms
        sum(length(body))     (counts CHARS)   463.5 ms
        max(md5(body))        (reads bytes)    381.9 ms

    Sizing is the cost of counting; reading is three orders of magnitude more.

    This case drives the same shapes at a size a test can afford and asserts
    the RATIO, which is what the claim is about — with enough headroom (the
    measured ratio at this size is ~36x and the bar is 4x) that it fails on a
    real regression and not on a slow runner.
    """
    import secrets
    import time
    import uuid

    from opendox.runtime.db import Database

    schema = "t_" + uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
            conn.execute(f"create table {schema}.drafts "
                         "(id text primary key, body text not null)")
        try:
            body = secrets.token_hex(128 * 1024)      # 256 KiB, incompressible
            with admin.transaction() as conn:
                for index in range(40):
                    conn.execute(
                        f"insert into {schema}.drafts values (%s, %s)",
                        (f"{index:04d}", body))
                conn.execute(f"analyze {schema}.drafts")

            def best_of_three(sql: str) -> float:
                timings = []
                for _ in range(3):
                    with admin.connection() as conn:
                        started = time.monotonic()
                        conn.execute(sql).fetchall()
                        timings.append(time.monotonic() - started)
                return min(timings)

            sized = best_of_three(
                f"select d.id, coalesce(sum(octet_length(d.body)) over "
                "(order by d.id rows between unbounded preceding and 1 "
                f"preceding), 0) from {schema}.drafts d order by d.id "
                "limit 500")
            detoasted = best_of_three(
                f"select max(md5(d.body)) from {schema}.drafts d")

            assert detoasted > sized * 4, (
                f"sizing {sized*1000:.2f} ms vs reading {detoasted*1000:.2f} "
                "ms: `octet_length` is reading the bodies, so the page "
                "budget bounds the fetch and not the database's work")

            # THE PREMISE, so this is not measuring an empty table: the bodies
            # really are out of line, which is when detoasting costs anything.
            with admin.connection() as conn:
                assert conn.execute(
                    "select pg_total_relation_size(%s)",
                    (f"{schema}.drafts",)).fetchone()[0] > 8 * 1024 * 1024
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")


def test_a_public_ledger_does_not_capture_a_tenant_schema_run(
        postgres_dsn: str) -> None:
    """An existing `public` ledger does not divert a tenant's bootstrap.

    THE FINDING, IN ITS OWN TERMS (Copilot review of openDox-code#25, round
    26): `LEDGER_DDL` is unqualified, so a selected schema with no ledger
    "can reuse a later `public.opendox_schema_migrations`: `CREATE TABLE IF
    NOT EXISTS` sees the public relation and skips creation in the selected
    schema", after which the unqualified insert records this tenant's run in
    `public` while `applied()` reads the selected schema and reports the
    migration as still pending.

    MEASURED FALSE, on postgres 16.15, and this test is the measurement kept
    executable. `IF NOT EXISTS` is tested against the relation the statement
    WOULD CREATE — the first schema in `search_path` the role can create in —
    and not against what the name resolves to for a read. A `public` ledger
    is therefore visible to the lookup and irrelevant to the creation.

    Which makes the test's own shape the point: it is a regression test only
    because the decoy in `public` is created FIRST and holds a row this run
    must not touch. Against the shape the finding describes — a bootstrap
    that skipped creation and wrote through the search path — `public` would
    hold two rows, the tenant schema would hold no ledger at all, and
    `applied()` would come back empty. All three are asserted.
    """
    import uuid as _uuid

    from opendox.runtime.db import Database

    schema = "t_" + _uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    decoy_was_ours = False
    with admin:
        with admin.transaction() as conn:
            existing = conn.execute(
                "select to_regclass('public.opendox_schema_migrations')"
            ).fetchone()[0]
            if existing is None:
                # THE DECOY, BUILT FROM THE RUNNER'S OWN DDL so it cannot
                # drift into a shape the run would reject for some reason
                # other than the one under test: under the finding, the
                # tenant's rows land in THIS table, and they can only do that
                # if its columns are the ledger's columns. Created only when
                # `public` is genuinely clean, and dropped below only in that
                # case, so this test never removes a ledger a real install
                # keeps in `public`.
                conn.execute(migrations.LEDGER_DDL.replace(
                    "if not exists ", "if not exists public.", 1))
                conn.execute(
                    "insert into public.opendox_schema_migrations "
                    "(version, name, checksum) values ('0000', 'decoy', 'x')")
                decoy_was_ours = True
            conn.execute(f"create schema {schema}")
        try:
            if not decoy_was_ours:
                pytest.skip("public already holds a ledger; the decoy this "
                            "test needs would not be ours to create or drop")
            with Database(postgres_dsn, schema=schema) as db:
                runner = migrations.MigrationRunner(db,
                                                    migrations_dir="migrations")
                applied = runner.apply()
                assert applied, "the run applied nothing; the rest is vacuous"

                with db.connection() as conn:
                    # WHERE THE LEDGER LANDED, by oid and not by name: an
                    # unqualified `to_regclass` would answer through the same
                    # search path the finding says was followed.
                    landed = conn.execute(
                        "select n.nspname from pg_class c "
                        "join pg_namespace n on n.oid = c.relnamespace "
                        "where c.relname = %s and n.nspname in (%s, 'public') "
                        "order by n.nspname",
                        (migrations.LEDGER_TABLE, schema)).fetchall()
                    assert {row[0] for row in landed} == {schema, "public"}, (
                        f"the ledger is not in both {schema} and public: "
                        f"{landed}; under the finding's shape the tenant "
                        f"schema would have none")

                    rows = conn.execute(
                        f"select version from {schema}.opendox_schema_migrations"
                        " order by version").fetchall()
                    assert [row[0] for row in rows] == sorted(applied), (
                        "the tenant ledger does not record this run")

                    decoy = conn.execute(
                        "select version from public.opendox_schema_migrations "
                        "order by version").fetchall()
                    assert [row[0] for row in decoy] == ["0000"], (
                        f"the run wrote into the public ledger: {decoy}")

                # AND THE READ AGREES WITH THE WRITE: `applied()` resolves
                # through `selected_schema()`, which is the half of the finding
                # that would have reported a pending migration forever.
                assert [row.version for row in runner.applied()] == sorted(applied)
                assert runner.plan() == []
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")
                if decoy_was_ours:
                    conn.execute(
                        "drop table if exists public.opendox_schema_migrations")


def test_a_comma_in_the_schema_name_is_a_real_connection_and_not_a_refusal(
        postgres_dsn: str) -> None:
    """The finding's case against a real server, not a double.

    `"tenant,blue"` is a legal schema name and PostgreSQL quotes it in
    `search_path`, so the old `path.split(",")` turned one entry into two and
    `selected_schema` refused a connection whose `current_schema()` was
    exactly the schema it had asked for — naming `'"tenant'` as the thing that
    did not exist (Copilot review of openDox-code#25, round 26, suppressed).

    The path is set ON THE CONNECTION here rather than through
    `Database(schema=…)`, which interpolates the name into a libpq `options`
    string and is documented as taking an install-generated identifier. That
    is the operator's route to a path this guard reads, and it is the one the
    finding is about.

    Against the previous head this fails at the first assertion.
    """
    from opendox.runtime.db import Database

    name = 'tenant,blue'
    quoted = '"' + name.replace('"', '""') + '"'
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"drop schema if exists {quoted} cascade")
            conn.execute(f"create schema {quoted}")
        try:
            with Database(postgres_dsn) as db:
                runner = migrations.MigrationRunner(db,
                                                    migrations_dir="migrations")
                with db.connection() as conn:
                    conn.execute(f"set search_path = {quoted}, public")
                    assert conn.execute(
                        "select current_schema()").fetchone()[0] == name
                    assert migrations.selected_schema(conn) == name

                    runner.bootstrap_ledger(conn)
                    landed = conn.execute(
                        "select n.nspname from pg_class c "
                        "join pg_namespace n on n.oid = c.relnamespace "
                        "where c.relname = %s and n.nspname = %s",
                        (migrations.LEDGER_TABLE, name)).fetchall()
                    assert [row[0] for row in landed] == [name], (
                        f"the ledger did not land in {name!r}: {landed}")
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {quoted} cascade")
