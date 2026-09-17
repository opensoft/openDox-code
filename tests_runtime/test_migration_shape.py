"""The ordered SQL, measured: order, the pin, and the ledger's two copies.

HERMETIC BY CONSTRUCTION — this module imports the standard library,
`pytest` and `opendox.runtime.migrations`, and nothing else, so it runs in
the leg's REQUIRED `validate` job, which installs `.[test]` and not
`.[runtime]`. (`pytest` was not named until Copilot's tenth review of
openDox-code#25 pointed out that a hermeticity claim which omits the runner
is not a claim a reader can check.) Everything it asserts is a property of
the files on disk or of a double defined here; nothing needs a database.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from opendox.runtime import migrations

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"


def test_the_migrations_directory_is_at_the_root_of_this_leg() -> None:
    """§ 3.5's own placement sentence, asserted rather than assumed.

    "`migrations/` … `deploy/compose/` and `deploy/kubernetes/` — ALL AT THE
    ROOT OF `openDox-code`, not of the assembly root". The root of THIS leg is
    the directory that carries `src/opendox` and `pyproject.toml`; asserting
    all three together is what distinguishes it from the assembly root, which
    carries neither.
    """
    assert MIGRATIONS.is_dir(), f"expected the ordered SQL at {MIGRATIONS}"
    assert (ROOT / "src" / "opendox").is_dir(), (
        f"{ROOT} does not look like the code leg's root: no src/opendox")
    assert (ROOT / "pyproject.toml").is_file()
    assert (ROOT / "deploy" / "compose").is_dir()
    assert (ROOT / "deploy" / "kubernetes").is_dir()


def test_every_migration_filename_is_the_declared_form() -> None:
    for entry in sorted(MIGRATIONS.iterdir()):
        if not entry.is_file() or not entry.name.endswith(".sql"):
            continue
        # THE RUNNER'S OWN REGEX, not a looser restatement of it. This
        # accepted `0005_trailing_.sql` and `0005__name.sql`, which
        # `migrations._MIGRATION_FILENAME_RE` does not discover — so a future
        # migration could pass the required shape suite and never be applied
        # (Copilot review of openDox-code#25, round 7, suppressed). The
        # `.down.sql` sidecar is checked against the same grammar with the
        # suffix removed, because the runner never discovers a sidecar.
        from opendox.runtime.migrations import _MIGRATION_FILENAME_RE

        name = entry.name
        if name.endswith(".down.sql"):
            name = name[: -len(".down.sql")] + ".sql"
        assert _MIGRATION_FILENAME_RE.fullmatch(name), (
            f"{entry.name} is not `NNNN_lower_snake.sql` (or its `.down.sql` "
            "sidecar) by the RUNNER's own grammar, so the runner discovers it "
            "never and it is silently never applied")


def test_migrations_are_discovered_in_numeric_order() -> None:
    found = migrations.discover_migrations(MIGRATIONS)
    versions = [m.version for m in found]
    assert versions == sorted(versions, key=int), (
        "discovery must order NUMERICALLY: `0010` sorts before `0002` as text, "
        "so a lexicographic runner is correct for exactly nine migrations and "
        "then quietly wrong")
    assert versions[0] == migrations.CANONICAL_MIGRATION_VERSION
    assert len(set(versions)) == len(versions), "two migrations share a version"


def test_the_canonical_migration_is_pinned_to_its_declared_digest() -> None:
    canonical = migrations.canonical_migration(MIGRATIONS)
    actual = hashlib.sha256(canonical.path.read_bytes()).hexdigest()
    assert actual == migrations.CANONICAL_MIGRATION_SHA256, (
        f"{canonical.path.name} hashes to {actual} but "
        "`migrations.CANONICAL_MIGRATION_SHA256` declares "
        f"{migrations.CANONICAL_MIGRATION_SHA256}. The canonical schema is "
        "IMMUTABLE: add a 0002+ migration instead. If the pin is genuinely "
        "being moved, move both — that two-file act is the whole mechanism.")
    # And the free function agrees with the constant, since the CLI and the
    # runner both call it rather than hashing the file themselves.
    assert migrations.verify_canonical_digest(MIGRATIONS) == actual


def test_a_tampered_canonical_migration_refuses_before_any_mutation(
        tmp_path: Path) -> None:
    for name in ("0001_identity_and_coordination.sql", "0002_migration_state.sql"):
        (tmp_path / name).write_bytes((MIGRATIONS / name).read_bytes())
    tampered = tmp_path / "0001_identity_and_coordination.sql"
    tampered.write_text(tampered.read_text(encoding="utf-8") + "\n-- edited\n",
                        encoding="utf-8")
    with pytest.raises(migrations.CanonicalDigestMismatchError) as caught:
        migrations.verify_canonical_digest(tmp_path)
    assert migrations.CANONICAL_MIGRATION_SHA256 in str(caught.value)


def test_the_ledger_ddl_matches_the_migration_that_declares_it() -> None:
    """The bootstrap copy and the reviewable copy are the same text.

    The runner creates the ledger with `create table if not exists` BEFORE it
    can record anything, so the DDL exists twice; this is what stops the
    bootstrap drifting into a shape no migration declares.
    """
    lines = (MIGRATIONS / "0002_migration_state.sql").read_text(
        encoding="utf-8").splitlines()
    starts = [n for n, line in enumerate(lines)
              if line.startswith("create table if not exists")]
    assert len(starts) == 1, (
        "expected exactly one `create table if not exists` STATEMENT at the "
        "start of a line in 0002 (a mention inside a comment does not start a "
        "line)")
    start = starts[0]
    end = next(n for n, line in enumerate(lines[start:], start)
               if line.rstrip() == ");")
    block = "\n".join(lines[start:end + 1])
    assert block == migrations.LEDGER_DDL, (
        "migrations/0002_migration_state.sql and "
        "`opendox.runtime.migrations.LEDGER_DDL` have drifted apart")
    assert migrations.LEDGER_TABLE in block


def test_the_ledger_table_is_prefixed_so_it_is_not_read_as_a_seventh_table() -> None:
    # RULING Q1's list is six; the ledger is infrastructure. The prefix is what
    # keeps `test_schema_shape.py`'s closed reading of 0001 honest.
    assert migrations.LEDGER_TABLE.startswith("opendox_")


def test_migrations_after_the_canonical_one_are_additive_only() -> None:
    """No `drop`/`alter … drop column` in a later migration.

    ADDITIVE is what makes `0001` pinnable: a later file that dropped a
    canonical table would make the pin a statement about a schema that no
    longer exists.
    """
    forbidden = re.compile(r"^\s*(drop\s+table|drop\s+schema|truncate)\b"
                           r"|drop\s+column\b", re.IGNORECASE | re.MULTILINE)
    for migration in migrations.discover_migrations(MIGRATIONS):
        if migration.is_canonical:
            continue
        body = "\n".join(line for line in migration.read_sql().splitlines()
                         if not line.lstrip().startswith("--"))
        assert not forbidden.search(body), (
            f"{migration.path.name} removes schema; migrations after the "
            "canonical one are additive (see the header of 0001)")


def test_reversibility_is_computed_from_the_sidecar_and_not_assumed() -> None:
    for migration in migrations.discover_migrations(MIGRATIONS):
        assert migration.reversible == migration.down_path.is_file()


def test_discovery_accepts_only_the_filename_shape_this_repository_declares(
        tmp_path) -> None:
    """The regex was `\\d+_.+`, which is broader than the contract above.

    A configured directory could therefore hold `1_custom.sql` or
    `0001_Custom Name.sql` — files this repository's own rule forbids — and the
    runner would apply them, ordered by a version that is not the pinned
    four-digit form (Copilot review of openDox-code#25, round 6, suppressed).
    """
    from opendox.runtime.migrations import discover_migrations

    for name in ("0001_identity.sql", "0002_migration_state.sql",
                 "1_custom.sql", "0003_Custom Name.sql", "0004_UPPER.sql",
                 "0005_trailing_.sql", "00006_too_many.sql",
                 "0007-dashed.sql"):
        (tmp_path / name).write_text("select 1;\n", encoding="utf-8")
    discovered = [f"{m.version}_{m.name}" for m in discover_migrations(tmp_path)]
    assert discovered == ["0001_identity", "0002_migration_state"], discovered


def test_two_files_claiming_one_version_are_refused_before_any_mutation(
        tmp_path) -> None:
    """The shape test holds THIS TREE; an image is not this tree.

    Two `0002_*.sql` files in a configured directory made `apply()` run and
    COMMIT the first and then fail on the ledger's primary key for the second
    — a partially applied run, which is the one state the runner exists to
    prevent (Copilot review of openDox-code#25, round 7).
    """
    import pytest

    from opendox.runtime.migrations import MigrationError, discover_migrations

    for name in ("0001_identity.sql", "0002_first.sql", "0002_second.sql"):
        (tmp_path / name).write_text("select 1;\n", encoding="utf-8")
    with pytest.raises(MigrationError) as caught:
        discover_migrations(tmp_path)
    message = str(caught.value)
    assert "0002" in message
    assert "0002_first.sql" in message and "0002_second.sql" in message


def test_a_version_below_the_canonical_one_is_not_a_migration(tmp_path) -> None:
    """`0000_*.sql` would have run BEFORE the pinned `0001`.

    The filename shape accepts it and discovery only ordered and de-duplicated,
    so such a file mutated the database after the canonical digest gate had
    passed and before the schema that digest pins existed — against the act's
    own `0001`-canonical / `0002`-and-up-additive contract (Copilot review of
    openDox-code#25, round 8).
    """
    import pytest

    from opendox.runtime.migrations import MigrationError, discover_migrations

    for name in ("0000_before_everything.sql", "0001_identity.sql"):
        (tmp_path / name).write_text("select 1;\n", encoding="utf-8")
    with pytest.raises(MigrationError) as caught:
        discover_migrations(tmp_path)
    assert "0000_before_everything.sql" in str(caught.value)
    assert "0001" in str(caught.value)


# -- Copilot's tenth round on #25: the documented connection contract ---------
#
# The module docstring promised `.execute(...)` alone and the runner also calls
# `.transaction()`, `.commit()` and `.rollback()`, so a double or an
# alternative driver written to the documented contract failed with
# `AttributeError`. The docstring now states four members; these two tests are
# what keep it the same list the code uses — one proves the four are ENOUGH,
# the other proves the shorter list was not.


class _Cursor:
    """What `.execute()` returns: `fetchone()` and `fetchall()` and no more."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple]:
        return list(self._rows)


class _DocumentedConnection:
    """EXACTLY the connection members the docstring documents, and nothing else.

    No `__getattr__`, deliberately: anything the runner reaches for that is not
    on this class is an `AttributeError`, which is what makes this a contract
    test rather than a mock that agrees with whatever it is asked.
    """

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self._ledger_exists = False

    def execute(self, sql: str, params: tuple | None = None) -> _Cursor:
        text = " ".join(sql.split())
        self.log.append(text)
        if text.startswith("select current_schema()"):
            # TWO COLUMNS, because `selected_schema` asks for two: the schema
            # PostgreSQL resolved and the `search_path` that was configured.
            # A fake that answers only the first would let the comparison
            # between them pass vacuously here.
            return _Cursor([("public", "public")])
        if "to_regclass" in text:
            return _Cursor([(self._ledger_exists,)])
        if text.startswith("select version, name, checksum, reversible"):
            return _Cursor([])
        if "create table if not exists" in text.lower():
            self._ledger_exists = True
        return _Cursor([])

    @contextmanager
    def transaction(self) -> Iterator[_DocumentedConnection]:
        self.log.append("<begin>")
        yield self
        self.log.append("<end>")

    def commit(self) -> None:
        self.log.append("<commit>")

    def rollback(self) -> None:
        self.log.append("<rollback>")


class _DocumentedDatabase:
    """`connection()` and `transaction()`, the two the docstring names."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.conn = _DocumentedConnection(self.log)

    @contextmanager
    def connection(self) -> Iterator[_DocumentedConnection]:
        yield self.conn

    @contextmanager
    def transaction(self) -> Iterator[_DocumentedConnection]:
        with self.conn.transaction() as conn:
            yield conn


class _ExecuteOnlyConnection:
    """The contract as it USED to be written: one method."""

    def execute(self, sql: str, params: tuple | None = None) -> _Cursor:
        if " ".join(sql.split()).startswith("select current_schema()"):
            return _Cursor([("public", "public")])
        return _Cursor([])


class _ExecuteOnlyDatabase:
    def __init__(self) -> None:
        self.conn = _ExecuteOnlyConnection()

    @contextmanager
    def connection(self) -> Iterator[_ExecuteOnlyConnection]:
        yield self.conn

    @contextmanager
    def transaction(self) -> Iterator[_ExecuteOnlyConnection]:
        yield self.conn


def test_a_double_implementing_the_documented_contract_drives_a_whole_apply(
) -> None:
    """The four documented members are ENOUGH to run `apply()` end to end.

    Which is the property the docstring is FOR: `opendox.runtime.db.Database`
    is one implementation, and anything else that keeps this contract — a test
    double here, an alternative driver — is another (Copilot review of
    openDox-code#25, round 10).
    """
    db = _DocumentedDatabase()
    runner = migrations.MigrationRunner(db, migrations_dir=MIGRATIONS)
    applied = runner.apply()

    assert applied == [m.version for m in runner.discover()], db.log
    ledger_ddl = next(i for i, line in enumerate(db.log)
                      if "create table if not exists" in line.lower())
    first_migration = next(i for i, line in enumerate(db.log)
                           if "create table users" in line.lower())
    assert ledger_ddl < first_migration, (
        "the ledger has to exist before a migration can be recorded in it")
    # The three members the shorter docstring left out are all REACHED.
    assert "<begin>" in db.log and "<commit>" in db.log


def test_a_double_with_only_execute_cannot_drive_the_runner() -> None:
    """And the shorter contract was NOT enough — which is why it is longer now.

    This is the failure a reader of the old docstring met: they wrote the
    object it described and the runner asked it for a member the paragraph
    never mentioned.
    """
    runner = migrations.MigrationRunner(_ExecuteOnlyDatabase(),
                                        migrations_dir=MIGRATIONS)
    with pytest.raises(AttributeError) as raised:
        runner.apply()
    assert any(member in str(raised.value)
               for member in ("transaction", "commit", "rollback")), (
        f"expected the missing member to be one the docstring now names: "
        f"{raised.value}")


def test_a_canonical_migration_swapped_after_the_gate_never_runs(
        tmp_path) -> None:
    """The byte pin has to cover the bytes that EXECUTE, not an earlier read.

    `apply()` verified `0001`'s digest, then `discover()` found the file again
    and `read_sql()` read it a third time to execute it. A migrations directory
    that can change under the process — a mounted volume, a deploy that
    rewrites it — could therefore pass the pin and run something else, and the
    ledger would record the digest of the bytes that did NOT run (Copilot
    review of openDox-code#25, round 11).

    ROUND 12 MOVED THE ANSWER EARLIER, AND THIS TEST WITH IT. Round 11 read
    each file once inside the loop and re-checked the pin there, so the swap
    below raised — but only AFTER `bootstrap_ledger()` and `protect_ledger()`
    had committed, which made "a tree carrying the wrong `0001` changes nothing
    at all" false by two changes. `snapshot_run()` now takes every file's bytes
    and runs the gate BEFORE the first commit, so a directory rewritten from
    here on cannot reach the run at all: the swap is simply not part of it, the
    run completes on the bytes it gated, and the replacement never executes.
    That last line is the property both rounds are about, and it is the one
    assertion this test kept.

    The swap is made deterministic by performing it while the runner is
    bootstrapping the ledger — after the gate, before the loop.
    """
    directory = tmp_path / "migrations"
    directory.mkdir()
    canonical = MIGRATIONS / f"{migrations.CANONICAL_MIGRATION_VERSION}_identity_and_coordination.sql"
    target = directory / canonical.name
    target.write_bytes(canonical.read_bytes())

    db = _DocumentedDatabase()
    real_execute = db.conn.execute
    replacement = b"create table replaced_by_somebody_else ();\n"

    def _swap_on_the_ledger_ddl(sql: str, params: tuple | None = None):
        if "create table if not exists" in sql.lower():
            target.write_bytes(replacement)
        return real_execute(sql, params)

    db.conn.execute = _swap_on_the_ledger_ddl              # type: ignore[method-assign]
    runner = migrations.MigrationRunner(db, migrations_dir=directory)
    assert runner.apply() == [migrations.CANONICAL_MIGRATION_VERSION]
    assert target.read_bytes() == replacement, (
        "the swap did not happen, so this test measured nothing")
    assert not any(replacement.decode() in line for line in db.log), (
        "the replacement bytes were executed after the gate had passed")
    assert any("create table users" in line.lower() for line in db.log), (
        "the bytes the gate verified were not the bytes that ran")


def test_the_whole_run_is_read_before_the_ledger_is_bootstrapped(
        tmp_path) -> None:
    """The gate's promise is "nothing at all", and it used to mean "two things".

    `verify_canonical_digest()` hashed the file; `bootstrap_ledger()` and
    `protect_ledger()` then COMMITTED the ledger table and its privilege
    changes; only then did the loop re-read the bytes and raise
    `CanonicalDigestMismatchError`. A migrations directory that changes under
    the process therefore left the database mutated by a run that refused
    (Copilot review of openDox-code#25, round 12). Every read now happens
    before the first statement.

    NOT ROUND 12'S REGRESSION, AND IT SAYS SO: a tree already wrong when
    `apply()` is called was refused at the gate in BOTH shapes, so this passes
    against either. The regression is its sibling
    `test_a_canonical_migration_swapped_after_the_gate_never_runs`, which
    rewrites the directory mid-run and does fail against the old shape. What
    THIS pins is the other half of the promise — that a refusal's whole
    footprint is the advisory lock — so no later round can satisfy the sibling
    by moving a mutation earlier instead of moving the reads.
    """
    directory = tmp_path / "migrations"
    directory.mkdir()
    canonical = MIGRATIONS / f"{migrations.CANONICAL_MIGRATION_VERSION}_identity_and_coordination.sql"
    (directory / canonical.name).write_bytes(
        canonical.read_bytes() + b"\n-- edited\n")

    db = _DocumentedDatabase()
    runner = migrations.MigrationRunner(db, migrations_dir=directory)
    with pytest.raises(migrations.CanonicalDigestMismatchError):
        runner.apply()
    # NOTHING THAT CHANGES THE DATABASE. The advisory lock and its
    # commit/rollback markers are the run's whole footprint; the ledger DDL,
    # the grant and the revoke are all past the gate now.
    mutating = [line for line in db.log
                if any(verb in line.lower()
                       for verb in ("create table", "grant ", "revoke ",
                                    "insert into", "alter "))]
    assert mutating == [], (
        f"a refused run reached the database: {mutating}")
    assert any("pg_advisory_lock" in line.lower() for line in db.log), (
        "the run did not even take its lock, so this test measured nothing")


class _SearchPath:
    """A connection that answers `selected_schema`'s two questions.

    The second is the USABILITY probe: `selected_schema` walks the whole
    configured path and asks Postgres which of the entries it would have
    skipped this connection could actually have used, so a fake that answered
    only the first question would let the walk pass vacuously (Copilot review
    of openDox-code#25, round 16). It returns TWO columns because round 19
    found that "exists" is the wrong question — `denied` is the set that exists
    and carries no `usage` for this role, which PostgreSQL skips exactly as it
    skips an absent one.
    """

    def __init__(self, schema: str | None, search_path: str,
                 present: tuple[str, ...] = (), user: str = "svc",
                 denied: tuple[str, ...] = ()) -> None:
        self._row = (schema, search_path, user)
        self._present = present
        self._denied = denied
        assert set(denied) <= set(present), (
            "a schema that does not exist cannot be the one this connection "
            "may not use; that is the other case")

    def execute(self, sql: str, params: tuple | None = None) -> _Cursor:
        text = " ".join(sql.split())
        if text.startswith("select current_schema()"):
            return _Cursor([self._row])
        assert "pg_catalog.pg_namespace" in text, sql
        assert "has_schema_privilege" in text, (
            "the probe asks only whether the schema EXISTS, which PostgreSQL "
            "does not treat as the question: " + sql)
        asked = (params or ([],))[0]
        return _Cursor([(name, name not in self._denied)
                        for name in asked if name in self._present])


def test_a_schema_resolved_by_search_path_fallback_is_refused() -> None:
    """`current_schema()` is the first EXISTING schema, not the configured one.

    MEASURED on postgres 16.15 with no `tenant` schema:

        set search_path = tenant, public;
        select current_schema();        -- public
        select current_schemas(false);  -- {public}
        show search_path;               -- tenant, public

    Every statement in this module qualifies with that answer PRECISELY so it
    cannot fall through — and the answer itself was the fallback, so
    `applied()` read another schema's ledger and `runtime reset` dropped
    another schema's tables (Copilot review of openDox-code#25, round 14, in
    both places).
    """
    with pytest.raises(migrations.MigrationError) as caught:
        migrations.selected_schema(
            _SearchPath("public", "tenant, public", present=("public",)))
    assert "tenant" in str(caught.value)
    assert "public" in str(caught.value)

    # AND THE WHOLE PATH IS WALKED, not only its head: `"$user"` first, with
    # neither the role's schema nor `tenant` present, used to stop the walk at
    # the exempt entry and accept `public` (round 16).
    with pytest.raises(migrations.MigrationError) as caught:
        migrations.selected_schema(
            _SearchPath("public", '"$user", tenant, public',
                        present=("public",)))
    assert "tenant" in str(caught.value)


def test_the_configured_schema_is_answered_and_the_default_path_is_not_refused(
) -> None:
    """The other side of the same rule, and the one that must not over-refuse.

    `"$user"` is not a schema NAME — it is the first entry of PostgreSQL's own
    DEFAULT `search_path`, where an absent user schema is skipped BY DESIGN. A
    plain install is not refused for having one; a connection that NAMES a
    schema gets that name, or a refusal.
    """
    assert migrations.selected_schema(
        _SearchPath("tenant", "tenant, public",
                    present=("tenant", "public"))) == "tenant"
    assert migrations.selected_schema(
        _SearchPath("public", '"$user", public', present=("public",))) == \
        "public"
    assert migrations.selected_schema(
        _SearchPath("odd name", '"odd name", public',
                    present=("odd name", "public"))) == "odd name"
    # A session answered by its OWN schema stops the walk there, which is what
    # `"$user"` means: `tenant` after it is not something this connection was
    # refused, it is something it never reached.
    assert migrations.selected_schema(
        _SearchPath("svc", '"$user", tenant, public', present=("svc",),
                    user="svc")) == "svc"
    # No schema at all is still refused, and says why.
    with pytest.raises(migrations.MigrationError) as caught:
        migrations.selected_schema(_SearchPath(None, "tenant"))
    assert "no current schema" in str(caught.value)


def test_a_selected_schema_this_connection_may_not_use_is_refused() -> None:
    """PostgreSQL skips an unauthorized entry exactly as it skips an absent one.

    The existence probe proved the wrong thing: `pg_namespace` answers "this
    schema is here", and `search_path` resolution asks "can THIS ROLE use it".
    So an existing `tenant` with no `usage` grant left `missing` empty and the
    fallback `public` was accepted and returned — the outcome this whole
    function exists to refuse, one privilege along, and the one that matters in
    a multi-tenant install, where the grant is the isolation (Copilot review of
    openDox-code#25, round 19).

    MEASURED on postgres 16.15 as a role holding no grant on a schema that
    exists — the case `test_migrations_apply.py` drives against a real server:

        set search_path = m_probe, public;
        select current_schema();                                     -- public
        select count(*) from pg_namespace where nspname = 'm_probe';  -- 1
        select has_schema_privilege(current_user, 'm_probe', 'usage'); -- f
    """
    with pytest.raises(migrations.MigrationError) as caught:
        migrations.selected_schema(
            _SearchPath("public", "tenant, public",
                        present=("tenant", "public"), denied=("tenant",)))
    message = str(caught.value)
    assert "tenant" in message and "public" in message
    # The refusal says WHICH of the two it is, because the remedies differ.
    assert "may not USE" in message, message
    assert "Grant usage" in message, message
    assert "does not exist" not in message, message

    # The other side, unchanged: absent still reads as absent.
    with pytest.raises(migrations.MigrationError) as caught:
        migrations.selected_schema(
            _SearchPath("public", "tenant, public", present=("public",)))
    assert "does not exist" in str(caught.value)

    # And a grant that IS held is not a refusal.
    assert migrations.selected_schema(
        _SearchPath("tenant", "tenant, public",
                    present=("tenant", "public"))) == "tenant"
