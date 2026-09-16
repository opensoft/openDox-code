"""RULING Q1's boundary, read off the canonical schema itself.

"the database owns identity and coordination; git owns governed artifacts.
Users, memberships, projects, the project-to-repository mapping, sessions and
unsaved drafts live in the openDox database. Specs, changes, ideation documents
and contracts stay in git, read from repositories and written back only through
the apply lane." — opensoft/openxFactory#656 comment 5542694957.

This file is the slice's own running proof. `test_migration_shape.py` measures
that the SQL is ordered and pinned and would be just as green if the schema had
a `documents` table in it; this one measures what the schema SAYS.

HERMETIC: standard library + `opendox.runtime.identity` only.
"""

from __future__ import annotations

import re
from pathlib import Path

from opendox.runtime import identity, migrations

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "migrations" / "0001_identity_and_coordination.sql"

#: Everything outside a `--` comment. Every assertion below reads THIS, so a
#: word in a comment can neither create a table nor hide one.
def _statements() -> str:
    return "\n".join(line for line in CANONICAL.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("--"))


def _declared_tables() -> list[str]:
    return re.findall(r"^create table (?:if not exists )?(\w+)",
                      _statements(), re.MULTILINE)


def _columns_of(table: str) -> list[tuple[str, str]]:
    """`(name, type)` for one `create table` block, comments already stripped."""
    body = re.search(rf"^create table (?:if not exists )?{table} \((.*?)^\);",
                     _statements(), re.MULTILINE | re.DOTALL)
    assert body is not None, f"no create table block for {table}"
    out: list[tuple[str, str]] = []
    for line in body.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("constraint"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out


#: RULING Q1's list, transcribed from the comment and in the ruling's own
#: order, so this file does not read the closure off the very module it is
#: checking. "Users, memberships, projects, the project-to-repository mapping,
#: sessions and unsaved drafts live in the openDox database."
RULED_TABLES: tuple[str, ...] = (
    "users", "memberships", "projects", "project_repositories", "sessions",
    "drafts",
)


def test_the_store_declares_exactly_the_tables_the_ruling_names() -> None:
    assert identity.TABLES == RULED_TABLES, (
        "`identity.TABLES` and RULING Q1's own list disagree; the ruling is "
        "#656 comment 5542694957 and this tuple is transcribed from it")


def test_the_canonical_schema_declares_exactly_rulings_six_tables() -> None:
    """The list is CLOSED. Compared as a SET, deliberately.

    The SQL's declaration order is fixed by the foreign keys — `projects` has
    to exist before `memberships` references it — so it is not free to be the
    ruling's reading order, and a test that demanded it would be asserting
    something Postgres decided. What is closed is the MEMBERSHIP of the set;
    the reading order lives in `identity.TABLES` and the test above holds that
    to the ruling.
    """
    declared = _declared_tables()
    assert len(declared) == len(set(declared)) == len(RULED_TABLES)
    assert set(declared) == set(RULED_TABLES), (
        "the canonical migration's tables and RULING Q1's list disagree. "
        "RULING Q1 names six things the database owns; a seventh table is a "
        "claim about that boundary and has to be made in the open — in the "
        "ruling, then in this file, then in `identity.TABLES`.")


def test_no_table_is_a_document_store() -> None:
    """The one content-bearing column is `drafts.body`, and Q1 rules it in.

    Every other table addresses documents and never carries them: the map row
    holds a `location`, a draft holds a `document_key` and a `basis_revision`.
    A `content`/`body`/`text`-of-a-document column anywhere else would be the
    hybrid RULING Q1 REJECTED ("documents in the database with git as an
    export; and the hybrid (ideas in the DB until promoted)").
    """
    content_columns: list[str] = []
    for table in identity.TABLES:
        for name, _type in _columns_of(table):
            if name in {"content", "body", "document", "text", "payload",
                        "blob", "bytes", "source"}:
                content_columns.append(f"{table}.{name}")
    assert content_columns == ["drafts.body"], (
        f"content-bearing columns found: {content_columns}. RULING Q1 puts "
        "UNSAVED DRAFTS in the database by name and nothing else; specs, "
        "changes, ideation documents and contracts stay in git.")


def test_no_credential_is_storable_anywhere_in_the_schema() -> None:
    """Authentication delegates to the broker, so there is nowhere to put one.

    Enforced as a property of the schema rather than of the code that writes
    it: a column that could hold a password is a column somebody eventually
    will.
    """
    banned = re.compile(r"\b\w*(password|secret|token|credential|private_key)\w*\b",
                        re.IGNORECASE)
    offenders = [f"{table}.{name}"
                 for table in identity.TABLES
                 for name, _type in _columns_of(table)
                 if banned.search(name)]
    assert offenders == [], (
        f"credential-shaped columns found: {offenders}. RULING Q2 delegates "
        "authentication to the Keycloak broker; this runtime verifies tokens "
        "and stores none.")


def test_the_user_row_is_keyed_by_the_brokers_identity() -> None:
    """Design § D5's inversion needs `(issuer, subject)` to be the natural key.

    `subject` alone is unique only WITHIN an issuer, so a schema that made it
    globally unique would merge two people the day a second realm is brokered.
    """
    names = [name for name, _ in _columns_of("users")]
    assert "issuer" in names and "subject" in names
    assert "constraint users_issuer_subject_key unique (issuer, subject)" in _statements()


def test_the_project_to_repository_map_is_one_row_per_project() -> None:
    """RULING C3: "a plain local git repository PER PROJECT"."""
    names = [name for name, _ in _columns_of("project_repositories")]
    assert names == ["id", "project_id", "adapter", "location", "remote_url",
                     "created_at"]
    assert ("constraint project_repositories_project_key unique (project_id)"
            in _statements())


def test_a_remote_is_attachable_later_rather_than_required() -> None:
    """RULING C3: "a remote can be attached later" — so the column is NULLable.

    A `not null` here would make "moving a project into a governed factory is a
    push, not a migration" false at the schema level: every standalone project
    would need a remote before its first save.
    """
    types = dict(_columns_of("project_repositories"))
    assert "not" not in _statements().split("remote_url")[1].split("\n")[0], (
        "remote_url must be nullable")
    assert types["remote_url"] == "text"


def test_every_role_the_store_accepts_is_a_role_the_schema_accepts() -> None:
    check = re.search(r"memberships_role_check check \(role in \((.*?)\)\)",
                      _statements())
    assert check is not None
    declared = tuple(part.strip().strip("'") for part in check.group(1).split(","))
    assert declared == identity.ROLES


def test_the_ledger_is_not_declared_in_the_canonical_migration() -> None:
    # It is bootstrapped by the runner and declared additively in 0002; a copy
    # here would be a third spelling of one table.
    assert migrations.LEDGER_TABLE not in _declared_tables()
