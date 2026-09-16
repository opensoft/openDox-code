"""The ordered SQL, measured: order, the pin, and the ledger's two copies.

HERMETIC BY CONSTRUCTION — this module imports the standard library and
`opendox.runtime.migrations` only, so it runs in the leg's REQUIRED `validate`
job, which installs `.[test]` and not `.[runtime]`. Everything it asserts is a
property of the files on disk; nothing here needs a database.
"""

from __future__ import annotations

import hashlib
import re
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
        assert re.match(r"^\d{4}_[a-z0-9_]+(\.down)?\.sql$", entry.name), (
            f"{entry.name} is not `NNNN_lower_snake.sql` (or its `.down.sql` "
            "sidecar); the runner discovers by that form and a file outside it "
            "is silently never applied")


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
