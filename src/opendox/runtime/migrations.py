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

THIS MODULE IMPORTS NO DATABASE DRIVER. It is handed a `Database`-shaped object
— anything with `connection()` and `transaction()` context managers yielding
something with `.execute(sql, params)` — so discovery, checksums, the ledger
DDL and the plan can all be read under the leg's `validate` check, which
installs `.[test]` and not `.[runtime]`. `opendox.runtime.db` supplies the real
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

    def checksum(self) -> str:
        """Lowercase hex SHA-256 of the file's raw bytes."""
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


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


class MigrationRunner:
    """Applies ordered SQL to a database, fail-closed.

    `db` is any object with `connection()` and `transaction()` context managers
    yielding a connection whose `.execute(sql, params=None)` returns a cursor —
    which is what `opendox.runtime.db.Database` is and what a test double can be
    without importing a driver.
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

        QUALIFIED WITH `current_schema()`, and that is not decoration. A
        connection's `search_path` is `<schema>,public`, so an unqualified
        `to_regclass('opendox_schema_migrations')` finds a ledger in `public`
        when the selected schema has none — after which `plan()` reports a
        fresh schema as fully migrated and `/readyz` calls it ready (Copilot
        review of openDox-code#25). The same search path is what let a test
        harness write its tables into `public` once, so this is the second time
        the shape has bitten; it is pinned here.
        """
        with self._session(conn) as conn:
            schema_row = conn.execute("select current_schema()").fetchone()
            schema = schema_row[0] if schema_row else None
            if not schema:
                raise MigrationError(
                    "this connection has no current schema; the ledger cannot "
                    "be resolved without one")
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

    def plan(self) -> list[Migration]:
        """The pending migrations, in the order they would be applied.

        VERSIONS ONLY, and `drift()` is where the rest of the answer is: see
        that method for why "nothing pending" is not the same as "this database
        matches this tree".
        """
        already = {row.version for row in self.applied()}
        return [m for m in self.discover() if m.version not in already]

    def drift(self) -> list[str]:
        """Applied migrations this tree can no longer account for.

        TWO KINDS, both of which `plan()` CANNOT see because it compares
        versions and nothing else (Copilot review of openDox-code#25):

          * a migration whose file has CHANGED since it was applied — `apply()`
            refuses it with `MigrationChecksumDriftError`, and without this
            method `/readyz` and `opendox-runtime status` both reported
            `schema: applied` for a database the runner would refuse;
          * a migration whose file is GONE — the ledger says it ran and the
            tree cannot say what it did, which makes a deleted migration
            indistinguishable from a valid no-op.

        Returns the versions, sorted, with a one-word reason each, so a caller
        can name them. Empty is the only clean answer.
        """
        on_disk = {m.version: m for m in self.discover()}
        out: list[str] = []
        for row in self.applied():
            migration = on_disk.get(row.version)
            if migration is None:
                out.append(f"{row.version}:missing")
            elif migration.checksum() != row.checksum:
                out.append(f"{row.version}:changed")
        return sorted(out)

    # -- apply ------------------------------------------------------------

    def bootstrap_ledger(self, conn: Any = None) -> None:
        if conn is not None:
            with conn.transaction():
                conn.execute(LEDGER_DDL)
            return
        with self._db.transaction() as owned:
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

        The canonical gate runs FIRST, before the ledger is even bootstrapped,
        so a tree carrying the wrong `0001` changes nothing at all.
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

    def _apply_locked(self, lock: Any) -> list[str]:
        """`apply`'s body, ON THE CONNECTION THAT OWNS THE RUN'S LOCK.

        EVERY statement below goes through `lock`. It used to reach the
        database through `self._db.transaction()`, which checks out another
        pool connection the advisory lock does not cover — see `_session`.
        """
        verify_canonical_digest(self._migrations_dir)
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
        on_disk = {m.version for m in self.discover()}
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

        for migration in self.discover():
            current = migration.checksum()
            if migration.version in recorded:
                if recorded[migration.version] != current:
                    raise MigrationChecksumDriftError(
                        version=migration.version,
                        recorded=recorded[migration.version],
                        current=current)
                continue
            with lock.transaction():
                lock.execute(migration.read_sql())
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
        return applied_now

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
        conn.execute(
            f"revoke insert, update, delete, truncate on {LEDGER_TABLE} "
            f"from {self._runtime_role}")
        conn.execute(
            f"grant select on {LEDGER_TABLE} to {self._runtime_role}")
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
