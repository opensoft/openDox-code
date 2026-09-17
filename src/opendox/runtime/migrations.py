"""The ordered-SQL migration runner: `0001` pinned canonical, `0002+` additive.

THE SHAPE IS `xFactory-Hermes-Install`'s, taken deliberately (RULING Q2,
opensoft/openxFactory#656 comment 5542792997 — "reuse the Hermes install
pattern"). Its `src/hermes_install/persistence/migrations.py` is the file this
one is modelled on, and the four properties taken are the four that make a
schema auditable rather than merely applied:

  * **The ledger bootstraps itself.** Recording that `0001` was applied needs
    the ledger to exist, so the runner creates it with `create table if not
    exists` before applying anything; `migrations/0002_migration_state.sql`
    holds the reviewable copy of that DDL and a test asserts the two are
    textually identical.
  * **`0001` is byte-pinned and the gate runs BEFORE any mutation.** A `0001`
    whose bytes hash to anything but `CANONICAL_MIGRATION_SHA256` aborts the
    run without applying a single statement.
  * **Drift on an already-applied migration is fatal.** A file edited after it
    was applied refuses; the database and the tree disagreeing is a fact the
    runner reports rather than a difference it papers over.
  * **Each migration commits with its ledger row, atomically**, so a run that
    dies half way leaves a ledger that is true.

WHAT IS DELIBERATELY NOT TAKEN from the Hermes install, recorded because an
omission that is a decision should say so: its `PINNED_CANONICAL_MIGRATION_
DIGESTS` map (a second, later provider migration applied byte-identically),
because openDox has no provider schema — `0001` is openDox's own and the map
would have exactly one entry that is already `CANONICAL_MIGRATION_SHA256`; and
its `execute_migration` session-setting containment (`reset role`, restored
`search_path`), because that exists for provider SQL that sets its own role,
and no migration in this repository does. Both are re-derivable from this
paragraph the day openDox pins somebody else's schema.

THIS MODULE IMPORTS NO DATABASE DRIVER. It is handed a `Database`-shaped
object, and the WHOLE contract is four members and no more:

  * `db.connection()` and `db.transaction()`, both context managers, each
    yielding a connection;
  * on that connection: `.execute(sql, params=None)` returning a cursor
    (`.fetchone()` / `.fetchall()`), `.transaction()` — a context manager of
    its own, which `bootstrap_ledger`, `protect_ledger` and every
    per-migration write use — and `.commit()` / `.rollback()`, which `apply()`
    needs to hold the advisory lock across transactions.

That list is stated because a shorter one was: this docstring promised
`.execute(...)` alone while the runner also called `.transaction()`,
`.commit()` and `.rollback()`, so a test double or an alternative driver
written to the documented contract failed with `AttributeError` (Copilot
review of openDox-code#25, round 10). `tests_runtime/test_migration_shape.py`
drives a whole `apply()` through a double that implements exactly the four,
which is what keeps the paragraph and the code the same thing.

So discovery, checksums, the ledger DDL and the plan can all be read under the
leg's `validate` check, which installs `.[test]` and not `.[runtime]`. `opendox.runtime.db` supplies the real
one. That is the package's import-weight contract, stated in
`opendox/runtime/__init__.py` and asserted by
`tests_runtime/test_runtime_surface.py`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opendox.runtime.identity import TABLES as COORDINATION_TABLES

#: Repository-root-relative default location of the ordered SQL migrations.
DEFAULT_MIGRATIONS_DIR = Path("migrations")

#: The version prefix of the pinned canonical schema migration.
CANONICAL_MIGRATION_VERSION = "0001"

#: THE PIN. Lowercase hex SHA-256 of `migrations/0001_identity_and_coordination
#: .sql`'s raw bytes. Changing the canonical schema is therefore a TWO-FILE act
#: somebody has to mean — the SQL and this constant — and
#: `tests_runtime/test_migration_shape.py` hashes the file against it on every
#: `validate` run, so an edit to either alone is red before it is deployed.
#: The additive path (`0002_…`, `0003_…`) needs neither edit, which is the
#: point: the immutable file is the one the whole install is pinned to.
CANONICAL_MIGRATION_SHA256 = (
    "6db4710578b012a3318fed36c3e1c22a3efaf4c129296f9d6d4143f4f84dbab3"
)

#: The ledger table. Prefixed, like the Hermes install's
#: `hermes_schema_migrations`, because it is infrastructure rather than one of
#: RULING Q1's six coordination tables — and `tests_runtime/
#: test_schema_shape.py` reads the closed six against `0001` alone, so the
#: prefix is also what keeps the ledger from reading as a seventh.
LEDGER_TABLE = "opendox_schema_migrations"

#: THE ADVISORY LOCK KEY the whole run is serialized on. A fixed bigint, so two
#: processes agree on it without a table to agree through — which matters
#: because the thing being protected is the creation of the tables.
#:
#: WHY THE RUN NEEDS ONE AT ALL (Copilot review of openDox-code#25, critical,
#: and correct): the gate, the ledger bootstrap, the ledger read and the
#: per-migration transactions are four separate statements. Two deploys, or a
#: Kubernetes Job retry overlapping its predecessor, can both read an EMPTY
#: ledger and both start applying `0001`; one then fails on objects the other
#: created, and the failure looks like a broken migration rather than a race.
#: `pg_advisory_lock` is session-scoped, so it spans every one of those
#: statements on the holder's connection while costing nothing on a run with no
#: contention.
#:
#: The value is arbitrary and only has to be stable and unlikely to collide
#: with another application's lock on the same database: `0x0D0C` for "dox"
#: followed by `0001` for the canonical schema this run applies.
MIGRATION_LOCK_KEY = 0x0D0C0001

#: Canonical DDL for the ledger. MUST stay textually identical to the
#: `create table if not exists` block in `migrations/0002_migration_state.sql`
#: (asserted by `tests_runtime/test_migration_shape.py`).
LEDGER_DDL = """\
create table if not exists opendox_schema_migrations (
  version text primary key,
  name text not null,
  checksum text not null,
  reversible boolean not null default false,
  applied_at timestamptz not null default now()
);"""

#: THE SAME SHAPE `tests_runtime/test_migration_shape.py` HOLDS THE TREE TO:
#: four digits, then lower_snake_case. It used to be `\d+_.+`, which is
#: broader than the contract — `1_custom.sql`, `0001_Custom Name.sql` — so a
#: configured directory could hold a file the repository's own rule forbids and
#: the runner would apply it, ordered by a version that is not the pinned form
#: (Copilot review of openDox-code#25, round 6). A file outside the shape is
#: now not a migration at all, which is the same answer `discover_migrations`
#: already gives anything that is not `NNNN_name.sql`.
_MIGRATION_FILENAME_RE = re.compile(
    r"^(?P<version>\d{4})_(?P<name>[a-z0-9]+(?:_[a-z0-9]+)*)\.sql$")

#: See `MigrationRunner.protect_ledger`. Mirrors `config._ROLE_NAME`, and is
#: duplicated rather than imported for the same reason every other closure in
#: this package is: `migrations` must import under `.[test]` alone, and it
#: imports `config` nowhere.
_PLAIN_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class MigrationError(Exception):
    """Base class for runner failures. Carries no secret material."""


class CanonicalDigestMismatchError(MigrationError):
    """`0001`'s bytes are not the bytes this install is pinned to."""

    def __init__(self, *, expected: str, actual: str,
                 version: str = CANONICAL_MIGRATION_VERSION) -> None:
        super().__init__(
            f"canonical migration {version} digest mismatch: expected "
            f"{expected}, computed {actual} — refusing to apply anything "
            "(fail closed, before the first mutation). The canonical schema is "
            "immutable: add a 0002+ migration instead, or move the pin in "
            "opendox.runtime.migrations.CANONICAL_MIGRATION_SHA256 deliberately."
        )
        self.expected = expected
        self.actual = actual
        self.version = version


class LedgerNarrowingIneffectiveError(MigrationError):
    """The configured runtime role still holds a write on the ledger.

    `revoke` succeeds and changes nothing for the ledger's OWNER, for a
    superuser, and for a role holding the same privilege through another grant.
    Raising here is what keeps "the ledger is narrowed" from being a claim the
    run makes about work it did not do (Copilot review of openDox-code#25).
    """


class RuntimeAccessMissingError(MigrationError):
    """The configured runtime role cannot use the schema the run just applied.

    The bundled bootstrap grants that role its rights on the database's FIRST
    START, as `$POSTGRES_USER`, so `alter default privileges` covers only the
    tables `$POSTGRES_USER` goes on to create. The migration DSN's user is
    configured separately: point it at another owner — or skip the
    managed-database prerequisite entirely — and the run creates the six tables
    with no privilege for the served role at all. `/readyz` then reports a
    reachable database and an applied schema while every API request fails with
    `permission denied for table …` (Copilot review of openDox-code#25, round
    12). The run asks Postgres directly instead, and a run that cannot be
    served is a failed run.
    """


class MigrationChecksumDriftError(MigrationError):
    """An already-applied migration's file has changed since it was applied."""

    def __init__(self, *, version: str, recorded: str, current: str) -> None:
        super().__init__(
            f"migration {version} was applied with checksum {recorded} but the "
            f"file now hashes to {current} — refusing to proceed (fail closed). "
            "The database and this tree disagree about what was applied; that "
            "is a fact to resolve, not a difference to skip past."
        )
        self.version = version
        self.recorded = recorded
        self.current = current


@dataclass(frozen=True)
class Migration:
    """One discovered migration file."""

    version: str
    name: str
    path: Path

    @property
    def is_canonical(self) -> bool:
        return self.version == CANONICAL_MIGRATION_VERSION

    @property
    def down_path(self) -> Path:
        """The optional reversal sidecar, `<version>_<name>.down.sql`."""
        return self.path.with_suffix("").with_suffix(".down.sql")

    @property
    def reversible(self) -> bool:
        return self.down_path.is_file()

    def read_sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def snapshot(self) -> bytes:
        """The file's raw bytes, read ONCE — and these are the bytes that run.

        `apply()` used to hash the file (`checksum()`), then read it again
        (`read_sql()`) to execute it, with the canonical gate a third read
        before both. A migrations directory that can change under the process
        — a mounted volume, a deploy that rewrites it — could therefore pass
        the byte pin and execute something else, and the ledger would record
        the digest of the bytes that did NOT run (Copilot review of
        openDox-code#25, round 11). One read, one digest, one execution.
        """
        return self.path.read_bytes()

    @staticmethod
    def digest_of(raw: bytes) -> str:
        """Lowercase hex SHA-256 of exactly these bytes."""
        return hashlib.sha256(raw).hexdigest()

    def checksum(self) -> str:
        """Lowercase hex SHA-256 of the file's raw bytes."""
        return self.digest_of(self.snapshot())


@dataclass(frozen=True)
class AppliedMigration:
    """One ledger row."""

    version: str
    name: str
    checksum: str
    reversible: bool


def discover_migrations(
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> list[Migration]:
    """Every `NNNN_name.sql` in `migrations_dir`, ordered by NUMERIC version.

    Numeric and not lexicographic: `0010` sorts before `0002` as text, and a
    runner that applied migrations in string order would be correct for exactly
    nine migrations and then quietly wrong. `.down.sql` sidecars are reversals
    and are never themselves discovered as migrations.
    """
    directory = Path(migrations_dir)
    if not directory.is_dir():
        raise MigrationError(f"migrations directory not found at {directory}")
    migrations: list[Migration] = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or entry.name.endswith(".down.sql"):
            continue
        match = _MIGRATION_FILENAME_RE.match(entry.name)
        if match is None:
            continue
        migrations.append(
            Migration(version=match.group("version"),
                      name=match.group("name"),
                      path=entry)
        )
    migrations.sort(key=lambda m: int(m.version))
    # NO TWO FILES MAY CLAIM ONE VERSION, and this is refused HERE rather than
    # by the ledger's primary key. `tests_runtime/test_migration_shape.py`
    # holds THIS TREE to unique versions; an image is not this tree, and two
    # `0002_*.sql` files in a configured directory made `apply()` run and
    # COMMIT the first and then fail on the second — a partially applied run,
    # which is the one state the runner exists to prevent (Copilot review of
    # openDox-code#25, round 7). A refusal before any mutation costs nothing
    # and is the same answer `discover` gives any other malformed directory.
    # AND NOTHING BELOW THE CANONICAL VERSION IS A MIGRATION. The filename
    # shape accepts `0000_*.sql`, and discovery only ordered and de-duplicated
    # — so such a file ran BEFORE the pinned `0001`, mutating the database
    # after the digest gate had passed and against the act's own
    # `0001`-canonical / `0002`-and-up-additive contract (Copilot review of
    # openDox-code#25, round 8). Refused here, where every caller sees it.
    for migration in migrations:
        if int(migration.version) < int(CANONICAL_MIGRATION_VERSION):
            raise MigrationError(
                f"{migration.path.name} claims version {migration.version}, "
                f"below the canonical {CANONICAL_MIGRATION_VERSION}. The "
                "canonical migration is the first thing this schema has; a "
                "file before it would run after its digest was verified and "
                "before the schema it pins exists. Nothing is applied.")
    seen: dict[str, str] = {}
    for migration in migrations:
        if migration.version in seen:
            raise MigrationError(
                f"two migrations claim version {migration.version}: "
                f"{seen[migration.version]} and {migration.path.name}. A run "
                "would apply and commit one and fail on the other, leaving a "
                "partially migrated database; nothing is applied.")
        seen[migration.version] = migration.path.name
    return migrations


def canonical_migration(
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> Migration:
    """The `0001` file, or a refusal naming the directory it is not in."""
    for migration in discover_migrations(migrations_dir):
        if migration.is_canonical:
            return migration
    raise MigrationError(
        f"no canonical migration ({CANONICAL_MIGRATION_VERSION}) found in "
        f"{migrations_dir}"
    )


def verify_canonical_digest(
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> str:
    """Hash `0001` and refuse unless it is the pinned bytes. Returns the digest.

    A free function and not only a runner method, so the CLI's `status` verb
    and the `validate` check can both answer "is this tree's canonical schema
    the one this install is pinned to?" without a database anywhere near them.
    """
    migration = canonical_migration(migrations_dir)
    actual = migration.checksum()
    if actual != CANONICAL_MIGRATION_SHA256:
        raise CanonicalDigestMismatchError(
            expected=CANONICAL_MIGRATION_SHA256, actual=actual)
    return actual


def _unquoted(entry: str) -> str:
    """One `search_path` entry, with PostgreSQL's quoting removed."""
    entry = entry.strip()
    if len(entry) >= 2 and entry.startswith('"') and entry.endswith('"'):
        return entry[1:-1].replace('""', '"')
    return entry


def selected_schema(conn: Any) -> str:
    """`current_schema()`, REFUSED when it is a search-path FALLBACK.

    `current_schema()` is the first EXISTING schema on the path, never the
    first CONFIGURED one. MEASURED on postgres 16.15 with no `tenant` schema:

        set search_path = tenant, public;
        select current_schema();        -- public
        select current_schemas(false);  -- {public}
        show search_path;               -- tenant, public

    So a connection that selects a schema which was dropped, renamed or never
    created reads and WRITES another one in silence. Every caller here
    qualifies with this answer precisely so that it cannot fall through — and
    the answer itself was the fallback: `applied()` reported `public`'s ledger
    as the selected schema's, after which `plan()` called a fresh schema
    migrated and `/readyz` called it ready, and the CLI's `reset`, whose whole
    promise is "this schema's coordination state and nothing else", dropped
    `public.*` (Copilot review of openDox-code#25, round 14, in both places).

    THE WHOLE CONFIGURED PATH IS WALKED, not only its first entry. Comparing
    the first entry alone left `search_path = "$user", tenant, public` with
    neither the role's schema nor `tenant` present: `$user` was exempt, so the
    walk stopped and `public` was accepted — the same silent fallback one
    position along (Copilot review of openDox-code#25, round 16). Every NAMED
    entry ahead of the one PostgreSQL resolved must exist; the rule is
    "nothing this connection asked for was skipped".

    `"$user"` IS EXEMPT, and only it: it is not a schema NAME but the first
    entry of PostgreSQL's own DEFAULT `search_path`, where an absent user
    schema is skipped BY DESIGN — so a plain install is not refused for having
    one. It is resolved against `current_user` so that a session whose OWN
    schema is the answer stops the walk there, which is what that path means.

    AND THE QUESTION IS "CAN THIS CONNECTION USE IT", NOT "DOES IT EXIST".
    PostgreSQL skips a search-path entry the session lacks USAGE on exactly as
    it skips one that is absent, so an EXISTING but unauthorized entry passed
    a `pg_namespace` existence probe and the fallback was accepted — the very
    outcome this function exists to refuse, one privilege along (Copilot review
    of openDox-code#25, round 19). MEASURED on postgres 16.15, as a role with
    no grant on a schema that exists:

        set search_path = m_probe, public;
        select current_schema();                                  -- public
        select current_schemas(false);                            -- {public}
        select count(*) from pg_namespace where nspname='m_probe'; -- 1
        select has_schema_privilege(current_user,'m_probe','usage'); -- f

    The refusal names WHICH of the two it is, because the remedy differs:
    create the schema, or grant usage on it.
    """
    row = conn.execute("select current_schema(), "
                       "current_setting('search_path'), current_user"
                       ).fetchone()
    schema = row[0] if row else None
    if not schema:
        raise MigrationError(
            "this connection has no current schema; no statement here will "
            "run through a search-path fallback to find one")
    path = (row[1] if len(row) > 1 else "") or ""
    user = row[2] if len(row) > 2 else None
    configured = [entry for entry in
                  (_unquoted(entry) for entry in path.split(",")) if entry]
    skipped: list[str] = []
    for entry in configured:
        if entry == "$user":
            if schema == user:
                break                    # the session's own schema answered
            continue                     # absent, and absent BY DESIGN
        if entry == schema:
            break                        # what this connection asked for
        skipped.append(entry)
    if skipped:
        rows = conn.execute(
            "select nspname, has_schema_privilege(current_user, oid, 'usage') "
            "from pg_catalog.pg_namespace "
            "where nspname = any(%s::text[])", (skipped,)).fetchall()
        usable = {found[0] for found in rows if found[1]}
        denied = {found[0] for found in rows if not found[1]}
        missing = [entry for entry in skipped if entry not in usable]
        if missing:
            why = ("exists, and this connection may not USE it"
                   if missing[0] in denied else "does not exist")
            remedy = (f"Grant usage on {missing[0]!r} to this role"
                      if missing[0] in denied else f"Create {missing[0]!r}")
            raise MigrationError(
                f"this connection selects {missing[0]!r}, which {why}: "
                f"PostgreSQL's search-path fallback answered {schema!r} "
                "instead, and every statement here would read and write THAT "
                f"schema. {remedy}, or point the DSN at the "
                "schema this database actually holds — the coordination state "
                "is not moved by silently choosing another one")
    return str(schema)


class MigrationRunner:
    """Applies ordered SQL to a database, fail-closed.

    `db` is any object with `connection()` and `transaction()` context managers
    yielding a connection that carries `.execute(sql, params=None)` (returning
    a cursor), `.transaction()` and `.commit()` / `.rollback()` — the four-part
    contract the module docstring states, which is what
    `opendox.runtime.db.Database` is and what a test double can be without
    importing a driver.
    """

    def __init__(self, db: Any, *,
                 migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
                 runtime_role: str | None = None) -> None:
        self._db = db
        self._migrations_dir = Path(migrations_dir)
        self._runtime_role = runtime_role

    # -- introspection ----------------------------------------------------

    def discover(self) -> list[Migration]:
        return discover_migrations(self._migrations_dir)

    @contextmanager
    def _session(self, conn: Any = None) -> Iterator[Any]:
        """Either the caller's connection, or one checked out for this call.

        THE ARGUMENT EXISTS FOR THE ADVISORY LOCK. `apply()` holds
        `MIGRATION_LOCK_KEY` on one session, and a session-level advisory lock
        protects only the session that took it: every read and every DDL the
        run then made through `self._db.transaction()` checked out a DIFFERENT
        pool connection, so two runners each holding their own lock session
        could race through the bootstrap, the ledger read and the migration
        transactions — and a pool sized to one connection deadlocked instead
        (Copilot review of openDox-code#25). Passing the lock-owning
        connection down is what makes the lock cover the work it names.
        """
        if conn is not None:
            yield conn
            return
        with self._db.connection() as owned:
            yield owned

    def applied(self, conn: Any = None) -> list[AppliedMigration]:
        """The ledger's rows IN THIS SCHEMA, or `[]` where it has none yet.

        `to_regclass` rather than a `select` that would raise: an absent ledger
        is the state of a fresh database and must be distinguishable from a
        database that cannot be read at all.

        QUALIFIED WITH THE SELECTED SCHEMA, and that is not decoration. A
        connection's `search_path` is `<schema>,public`, so an unqualified
        `to_regclass('opendox_schema_migrations')` finds a ledger in `public`
        when the selected schema has none — after which `plan()` reports a
        fresh schema as fully migrated and `/readyz` calls it ready (Copilot
        review of openDox-code#25). The same search path is what let a test
        harness write its tables into `public` once, so this is the second time
        the shape has bitten; it is pinned here.

        AND THE QUALIFICATION IS ASKED OF `selected_schema`, NOT OF
        `current_schema()`, because that function IS the fallback: see it for
        the measurement and for the third instance of this shape.
        """
        with self._session(conn) as conn:
            schema = selected_schema(conn)
            # `quote_ident` and CONCATENATION, not `format('%I.%I', …)`:
            # psycopg's client-side placeholder scanner reads `%I` as a
            # placeholder it does not know and refuses the whole statement, so
            # the server-side formatter cannot be reached through it.
            exists = conn.execute(
                "select to_regclass(quote_ident(%s) || '.' || quote_ident(%s)) "
                "is not null", (schema, LEDGER_TABLE)).fetchone()
            if not exists or not exists[0]:
                return []
            rows = conn.execute(
                "select version, name, checksum, reversible "
                f"from {LEDGER_TABLE} order by version").fetchall()
        return [AppliedMigration(version=r[0], name=r[1], checksum=r[2],
                                 reversible=r[3]) for r in rows]

    def plan(self, conn: Any = None) -> list[Migration]:
        """The pending migrations, in the order they would be applied.

        VERSIONS ONLY, and `drift()` is where the rest of the answer is: see
        that method for why "nothing pending" is not the same as "this database
        matches this tree".

        `conn` IS THE PROBE'S HANDLE, and it is the same argument `applied()`
        already took: `/readyz` asks three questions under ONE `timeoutSeconds`
        and each of them checked out its own pooled connection, so under pool
        contention the probe's budget covered one wait and paid three (Copilot
        review of openDox-code#25, round 19, suppressed).
        """
        already = {row.version for row in self.applied(conn)}
        return [m for m in self.discover() if m.version not in already]

    def drift(self, conn: Any = None) -> list[str]:
        """Applied migrations this tree can no longer account for.

        TWO KINDS, both of which `plan()` CANNOT see because it compares
        versions and nothing else (Copilot review of openDox-code#25):

          * a migration whose file has CHANGED since it was applied — `apply()`
            refuses it with `MigrationChecksumDriftError`, and without this
            method `/readyz` and `opendox-runtime runtime status` both reported
            `schema: applied` for a database the runner would refuse;
          * a migration whose file is GONE — the ledger says it ran and the
            tree cannot say what it did, which makes a deleted migration
            indistinguishable from a valid no-op.

        Returns the versions, sorted, with a one-word reason each, so a caller
        can name them. Empty is the only clean answer.

        `conn` is `plan()`'s, for the same reason: one probe, one checkout.
        """
        on_disk = {m.version: m for m in self.discover()}
        out: list[str] = []
        for row in self.applied(conn):
            migration = on_disk.get(row.version)
            if migration is None:
                out.append(f"{row.version}:missing")
            elif migration.checksum() != row.checksum:
                out.append(f"{row.version}:changed")
        return sorted(out)

    # -- apply ------------------------------------------------------------

    def bootstrap_ledger(self, conn: Any = None) -> None:
        """Create the ledger if it is absent — IN THE SELECTED SCHEMA OR NOT AT ALL.

        `LEDGER_DDL` is unqualified, which is right: it must land wherever the
        connection's `search_path` selects. But `current_schema()` is that
        path's FALLBACK, so on a connection configured for a schema that no
        longer exists this `create table` landed in `public` and COMMITTED —
        and `applied()`, which asks `selected_schema` and refuses, ran
        afterwards: a fail-closed run that had already mutated another schema
        (Copilot review of openDox-code#25, round 15). The guard is asked
        before the DDL, so a run that will refuse refuses before it writes.
        """
        if conn is not None:
            selected_schema(conn)
            with conn.transaction():
                conn.execute(LEDGER_DDL)
            return
        with self._db.transaction() as owned:
            selected_schema(owned)
            owned.execute(LEDGER_DDL)

    def apply(self) -> list[str]:
        """Apply every pending migration in order; return the versions applied.

        SERIALIZED ON `MIGRATION_LOCK_KEY` for the whole run — see that
        constant for why. The lock is taken on a connection held open across
        the gate, the bootstrap, the ledger read and every per-migration
        transaction, and released in a `finally` so a failed run does not leave
        the next one waiting on a session that has gone away (Postgres would
        release it when the backend exits anyway; releasing it explicitly is
        what makes a retry in the SAME process immediate).

        THE WHOLE RUN'S BYTES ARE READ FIRST, and the canonical gate runs on
        them, before the ledger is even bootstrapped — so a tree carrying the
        wrong `0001` changes nothing at all.
        """
        with self._db.connection() as lock:
            lock.execute("select pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
            lock.commit()
            try:
                return self._apply_locked(lock)
            finally:
                # The connection may be mid-transaction if a migration raised;
                # roll that back before the unlock so the unlock is not itself
                # swallowed by a failed transaction block.
                lock.rollback()
                lock.execute("select pg_advisory_unlock(%s)",
                             (MIGRATION_LOCK_KEY,))
                lock.commit()

    def snapshot_run(self) -> list[tuple[Migration, bytes]]:
        """Every migration and ITS BYTES, read once, with the gate applied.

        NO DATABASE. This is discovery plus one read per file plus the
        canonical digest check, so `apply()` can take its whole view of the
        tree BEFORE it mutates anything.

        WHY THE WHOLE RUN AND NOT JUST `0001` (Copilot review of
        openDox-code#25, round 12). The gate used to hash the canonical file,
        `bootstrap_ledger()` and `protect_ledger()` then COMMITTED, and the
        loop re-read the bytes and re-checked the pin. A migrations directory
        that changes under the process — which this runner explicitly supports,
        and which is why the per-file snapshot exists at all — could therefore
        pass the gate, have the ledger table and its privilege changes
        committed, and only then raise `CanonicalDigestMismatchError`: the
        promised "a tree carrying the wrong `0001` changes nothing at all" was
        not kept, because by then two things had changed. One read of every
        file, before the first `commit`, is the version of that promise a
        mutable directory cannot walk past — and it is `Migration.snapshot()`'s
        own rule ("one read, one digest, one execution") widened from a file to
        a run.
        """
        run = [(migration, migration.snapshot())
               for migration in self.discover()]
        for migration, raw in run:
            if not migration.is_canonical:
                continue
            actual = Migration.digest_of(raw)
            if actual != CANONICAL_MIGRATION_SHA256:
                raise CanonicalDigestMismatchError(
                    expected=CANONICAL_MIGRATION_SHA256, actual=actual)
            return run
        raise MigrationError(
            f"no canonical migration ({CANONICAL_MIGRATION_VERSION}) found in "
            f"{self._migrations_dir}")

    def _apply_locked(self, lock: Any) -> list[str]:
        """`apply`'s body, ON THE CONNECTION THAT OWNS THE RUN'S LOCK.

        EVERY statement below goes through `lock`. It used to reach the
        database through `self._db.transaction()`, which checks out another
        pool connection the advisory lock does not cover — see `_session`.
        """
        run = self.snapshot_run()
        self.bootstrap_ledger(lock)
        lock.commit()

        # THE LEDGER IS NARROWED BEFORE ANY MIGRATION RUNS, not after. When
        # this came last, a misconfigured `runtime_role` failed the run only
        # once every migration and its ledger INSERT had already committed —
        # and `/readyz` asks about schema and drift, not about grants, so the
        # install could serve with the SERVED role still able to rewrite the
        # runner's tamper-evident record (Copilot review of openDox-code#25).
        # Now the narrowing is a precondition: it runs the moment the table
        # exists, and a run that cannot narrow the ledger applies nothing.
        self.protect_ledger(lock)
        lock.commit()

        applied_rows = self.applied(lock)
        on_disk = {migration.version for migration, _ in run}
        vanished = sorted(row.version for row in applied_rows
                          if row.version not in on_disk)
        if vanished:
            raise MigrationError(
                f"the ledger records migration(s) {vanished} that this tree "
                "does not contain. A run cannot say what they did, so it "
                "cannot say the database matches the tree; restore the file(s) "
                "or reconcile the ledger deliberately. (Fail closed — the same "
                "rule a checksum drift gets.)")

        recorded = {row.version: row.checksum for row in applied_rows}
        applied_now: list[str] = []

        for migration, raw in run:
            # THE BYTES ARE TAKEN ONCE AND EVERYTHING BELOW IS ABOUT THEM: the
            # digest recorded in the ledger, the pin checked for `0001`, and the
            # SQL executed. Three separate reads meant the gate could pass on
            # one version of the file and the run execute another (Copilot
            # review of openDox-code#25, round 11); `snapshot_run()` above now
            # takes that one read BEFORE the ledger is bootstrapped, so the pin
            # has already been checked against exactly these bytes and there is
            # nothing left here to re-check (round 12).
            current = Migration.digest_of(raw)
            if migration.version in recorded:
                if recorded[migration.version] != current:
                    raise MigrationChecksumDriftError(
                        version=migration.version,
                        recorded=recorded[migration.version],
                        current=current)
                continue
            with lock.transaction():
                lock.execute(raw.decode("utf-8"))
                lock.execute(
                    f"insert into {LEDGER_TABLE} "
                    "(version, name, checksum, reversible, applied_at) "
                    "values (%s, %s, %s, %s, now())",
                    (migration.version, migration.name, current,
                     migration.reversible))
            lock.commit()
            applied_now.append(migration.version)

        # AND AGAIN AT THE END, because a migration's own DDL may widen the
        # served role's rights (`grant … on all tables in schema`) and would
        # then have re-granted the ledger along with its own tables.
        self.protect_ledger(lock)
        lock.commit()
        # AND THE SERVED ROLE'S ACCESS IS MEASURED, for the same reason the
        # narrowing above is: a grant that was never made is invisible until a
        # request fails. This is the LAST act of the run, after the narrowing,
        # so it reads the privileges the install will actually serve with.
        self.verify_runtime_access(lock)
        return applied_now

    #: The rights the served role must hold on every coordination table. The
    #: ledger is the one exception and is checked in the other direction by
    #: `protect_ledger`.
    SERVED_PRIVILEGES: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE", "DELETE")

    #: The tables those rights are required ON: the coordination tables this
    #: runtime applies, and nothing else that happens to share the schema.
    #: RULING Q1's own list, imported from the module that declares it.
    SERVED_TABLES: tuple[str, ...] = COORDINATION_TABLES

    def verify_runtime_access(self, conn: Any = None) -> None:
        """Refuse a run whose served role cannot read and write what it applied.

        A no-op when no role is configured, exactly like `protect_ledger`: a
        single-role install is legal and has nothing to check.

        THE LEDGER IS EXCLUDED, because `protect_ledger` has just taken three
        of these four privileges away from it on purpose.

        The question is asked as `has_table_privilege`, which accounts for
        ownership and for group membership, so a role granted through a group
        passes — the check is "can this role use this table", not "is there a
        grant row naming it".
        """
        if not self._runtime_role:
            return
        if conn is not None:
            self._check_runtime_access(conn)
            return
        with self._db.connection() as owned:
            self._check_runtime_access(owned)

    def _check_runtime_access(self, conn: Any) -> None:
        # The role name is a PARAMETER here: `has_table_privilege` is a
        # function call, not an identifier position.
        # THE SELECTED SCHEMA, not `current_schema()` in the predicate: the
        # run applied its DDL into the schema `selected_schema` names, and a
        # connection whose configured schema is missing would otherwise have
        # this check answer for `public` — measuring the privileges of tables
        # this run did not create (Copilot review of openDox-code#25, round
        # 14, the same shape one method along).
        schema = selected_schema(conn)
        # AND `USAGE` ON THE SCHEMA, WHICH NO TABLE GRANT IMPLIES. A role can
        # hold every privilege on every table and still not be able to name one
        # of them: without `usage` on the schema, `select * from users` is
        # "permission denied for schema". The check claimed to answer "can the
        # served role use what this run applied" and did not ask the one
        # question that gates all the others (Copilot review of
        # openDox-code#25, round 15, suppressed).
        usable = conn.execute("select has_schema_privilege(%s, %s, 'usage')",
                              (self._runtime_role, schema)).fetchone()
        if not usable or not usable[0]:
            raise RuntimeAccessMissingError(
                f"{self._runtime_role!r} has no USAGE on schema {schema!r}, so "
                "it cannot name a table in it whatever grants those tables "
                "carry. `grant usage on schema … to <runtime role>` "
                "(docs/runtime.md, the managed-database note)")
        # THE COORDINATION TABLES, NOT EVERY TABLE IN THE SCHEMA. This scanned
        # `relkind = 'r'` across the whole schema, so a table that has nothing
        # to do with this runtime — another application sharing the schema, an
        # operator's scratch table — FAILED the migration run for a privilege
        # the served role was never meant to hold; and the run says in terms
        # that the served role needs these rights on the tables IT applied
        # (Copilot review of openDox-code#25, round 15, suppressed). The list
        # is RULING Q1's own, imported rather than retyped, and
        # `test_applying_creates_exactly_the_six_tables_and_the_ledger` holds
        # it to what the migrations create.
        missing = conn.execute(
            "select c.relname, p.privilege "
            "  from pg_catalog.pg_class c "
            "  join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
            "  cross join unnest(%s::text[]) as p(privilege) "
            " where n.nspname = %s "
            "   and c.relkind = 'r' "
            "   and c.relname = any(%s::text[]) "
            "   and c.relname <> %s "
            "   and not has_table_privilege(%s, c.oid, p.privilege) "
            " order by c.relname, p.privilege",
            (list(self.SERVED_PRIVILEGES), schema, list(self.SERVED_TABLES),
             LEDGER_TABLE, self._runtime_role)).fetchall()
        # AND A TABLE THAT IS NOT THERE IS MISSING, not absent from the
        # answer. The query is driven by `pg_class`, so a required coordination
        # table that was DROPPED produces no row at all and was never added to
        # `missing` — a rerun after `users` was removed reported success and
        # the API failed on the relation later (Copilot review of
        # openDox-code#25, round 16, suppressed). Restricting the scan to
        # `SERVED_TABLES` in the same round is what made the gap reachable, so
        # the set is compared rather than assumed.
        present = {found[0] for found in conn.execute(
            "select c.relname from pg_catalog.pg_class c "
            "  join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
            " where n.nspname = %s and c.relkind = 'r' "
            "   and c.relname = any(%s::text[])",
            (schema, list(self.SERVED_TABLES))).fetchall()}
        absent = [table for table in self.SERVED_TABLES if table not in present]
        if absent:
            raise RuntimeAccessMissingError(
                f"the schema {schema!r} this run applied is missing "
                f"{', '.join(absent)}; the coordination tables RULING Q1 names "
                "have to be there for the served role to use them, and a run "
                "that reports success without them leaves the API to fail on "
                "the relation instead")
        if not missing:
            return
        named = ", ".join(f"{row[0]}:{row[1]}" for row in missing)
        raise RuntimeAccessMissingError(
            f"{self._runtime_role!r} cannot use the schema this run applied — "
            f"missing {named}. The bootstrap that creates the role sets "
            "default privileges FOR THE ROLE THAT RUNS IT, so a migration DSN "
            "authenticating as a different owner creates tables the served "
            "role has no rights on, and a managed database that skipped the "
            "documented prerequisite grants nothing at all. Grant them with "
            "`grant select, insert, update, delete on all tables in schema "
            "… to <runtime role>` and `alter default privileges for role "
            "<migration owner> …` (docs/runtime.md, the managed-database "
            "note), or serve as the role the bootstrap granted.")

    def protect_ledger(self, conn: Any = None) -> None:
        """Narrow the SERVED role's rights on the ledger to SELECT.

        WHY THE RUNNER DOES THIS AND NOT THE ROLE-CREATION SCRIPT. The compose
        and Kubernetes bootstrap scripts run on the database's FIRST START,
        before any migration exists, so they can only set default privileges —
        which then cover the ledger along with everything else, and the served
        role could INSERT, UPDATE or DELETE the runner's own tamper-evident
        record (Copilot review of openDox-code#25). Hiding an applied migration
        or manufacturing one would make the fail-closed drift check check a
        story the API wrote. The runner is the process that OWNS the ledger and
        runs as the privileged identity, so it is the one place the narrowing
        can be applied at the right moment: after the table exists.

        SELECT is kept, deliberately: `/readyz` reads the ledger through the
        served DSN to report a pending schema.

        A no-op when no role is configured — a single-role install (a developer
        running one Postgres) is legal and just does not get this separation.
        """
        if not self._runtime_role:
            return
        # The role NAME is validated as a plain SQL identifier by
        # `config._role_name`; SQL takes identifiers as syntax, so it cannot be
        # a parameter, and validating the shape is what makes the
        # interpolation safe. Asserted here too, because this method is public
        # and a caller may not have come through the config loader.
        if not _PLAIN_IDENTIFIER.fullmatch(self._runtime_role):
            raise MigrationError(
                f"{self._runtime_role!r} is not a plain SQL identifier; the "
                "ledger narrowing interpolates a role name as syntax and "
                "refuses anything outside [A-Za-z_][A-Za-z0-9_]*")
        if conn is not None:
            with conn.transaction():
                self._narrow_ledger(conn)
            return
        with self._db.transaction() as owned:
            self._narrow_ledger(owned)

    def _narrow_ledger(self, conn: Any) -> None:
        # QUOTED, because Postgres FOLDS an unquoted identifier to lower case
        # while the bootstrap creates the role with `%I`, which quotes it. A
        # configured `MyRole` — accepted by `_ROLE_NAME` and by
        # `_PLAIN_IDENTIFIER`, both of which allow upper case — therefore had
        # its grant and revoke aimed at `myrole`: a different role, or none
        # (Copilot review of openDox-code#25, round 7). The shape is already
        # validated as a plain identifier above, so doubling any quote is
        # belt-and-braces rather than the guard.
        role = '"' + self._runtime_role.replace('"', '""') + '"'
        conn.execute(
            f"revoke insert, update, delete, truncate on {LEDGER_TABLE} "
            f"from {role}")
        conn.execute(
            f"grant select on {LEDGER_TABLE} to {role}")
        # AND THE NARROWING IS MEASURED, because `revoke` can succeed and
        # change nothing. A role that OWNS the ledger — which is what happens
        # when both DSNs are pointed at the migration identity — keeps every
        # privilege, and so does a superuser or a role holding the same write
        # through another grant; the run then reported a narrowed ledger that
        # the served identity could still rewrite (Copilot review of
        # openDox-code#25). Postgres is asked the question directly, with the
        # role name as a PARAMETER (this is a function call, not an
        # identifier), and a `true` here fails the whole run.
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            row = conn.execute(
                "select has_table_privilege(%s, %s, %s)",
                (self._runtime_role, LEDGER_TABLE, privilege)).fetchone()
            if row and row[0]:
                raise LedgerNarrowingIneffectiveError(
                    f"{self._runtime_role!r} still has {privilege} on "
                    f"{LEDGER_TABLE} after the revoke. A role that owns the "
                    "ledger (both DSNs pointed at the migration identity), a "
                    "superuser, or a role holding the privilege through "
                    "another grant cannot be narrowed by revoking from it, and "
                    "an unnarrowed served role can rewrite the runner's own "
                    "tamper-evident record. Serve as a role that is not the "
                    "owner of the coordination schema.")
