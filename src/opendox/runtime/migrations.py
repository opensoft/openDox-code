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

_MIGRATION_FILENAME_RE = re.compile(r"^(?P<version>\d+)_(?P<name>.+)\.sql$")


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
                 migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR) -> None:
        self._db = db
        self._migrations_dir = Path(migrations_dir)

    # -- introspection ----------------------------------------------------

    def discover(self) -> list[Migration]:
        return discover_migrations(self._migrations_dir)

    def applied(self) -> list[AppliedMigration]:
        """The ledger's rows, or `[]` where no ledger exists yet.

        `to_regclass` rather than a `select` that would raise: an absent ledger
        is the state of a fresh database and must be distinguishable from a
        database that cannot be read at all.
        """
        with self._db.connection() as conn:
            exists = conn.execute(
                "select to_regclass(%s) is not null", (LEDGER_TABLE,)).fetchone()
            if not exists or not exists[0]:
                return []
            rows = conn.execute(
                "select version, name, checksum, reversible "
                f"from {LEDGER_TABLE} order by version").fetchall()
        return [AppliedMigration(version=r[0], name=r[1], checksum=r[2],
                                 reversible=r[3]) for r in rows]

    def plan(self) -> list[Migration]:
        """The pending migrations, in the order they would be applied."""
        already = {row.version for row in self.applied()}
        return [m for m in self.discover() if m.version not in already]

    # -- apply ------------------------------------------------------------

    def bootstrap_ledger(self) -> None:
        with self._db.transaction() as conn:
            conn.execute(LEDGER_DDL)

    def apply(self) -> list[str]:
        """Apply every pending migration in order; return the versions applied.

        The canonical gate runs FIRST, before the ledger is even bootstrapped,
        so a tree carrying the wrong `0001` changes nothing at all.
        """
        verify_canonical_digest(self._migrations_dir)
        self.bootstrap_ledger()

        recorded = {row.version: row.checksum for row in self.applied()}
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
            with self._db.transaction() as conn:
                conn.execute(migration.read_sql())
                conn.execute(
                    f"insert into {LEDGER_TABLE} "
                    "(version, name, checksum, reversible, applied_at) "
                    "values (%s, %s, %s, %s, now())",
                    (migration.version, migration.name, current,
                     migration.reversible))
            applied_now.append(migration.version)

        return applied_now
