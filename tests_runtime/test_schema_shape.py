"""RULING Q1's boundary, read off the canonical schema itself.

"the database owns identity and coordination; git owns governed artifacts.
Users, memberships, projects, the project-to-repository mapping, sessions and
unsaved drafts live in the openDox database. Specs, changes, ideation documents
and contracts stay in git, read from repositories and written back only through
the apply lane." — opensoft/openxFactory#656 comment 5542694957.

This file is the slice's own running proof. `test_migration_shape.py` measures
that the SQL is ordered and pinned and would be just as green if the schema had
a `documents` table in it; this one measures what the schema SAYS.

HERMETIC, and the list is the file's real import block: standard library,
`pytest`, and the two stdlib-only package modules `opendox.runtime.identity`
and `opendox.runtime.migrations` (the ledger table's name is read from the
second, so the six coordination tables can be counted without it). It named
only `identity`, which made the module's own hermeticity claim narrower than
its imports — and this suite ran in the REQUIRED job without the `runtime`
extra, where what may be imported was the whole question (Copilot review of
openDox-code#25, round 10, suppressed). Nothing here needs a database or the
`runtime` extra.
"""

from __future__ import annotations

import re
from pathlib import Path

from opendox.runtime import identity, migrations

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "migrations" / "0001_identity_and_coordination.sql"
#: The health store's tables, declared additively (#1144 box 14.1). R2Q13 (a),
#: ruled by opensoft/openxFactory#656 comment 6003486656, whose option text
#: (plan 038's `clarify-questions.md:651-653`) reads: "the closure test reads
#: `0001` together with `0003_`, in the same change". `0002` is not read: it
#: declares the ledger, which is infrastructure and not a table the domain
#: owns (`test_the_ledger_is_not_declared_in_the_canonical_migration`).
HEALTH = ROOT / "migrations" / "0003_health.sql"

#: Everything outside a `--` comment, in `0001` and `0003_` together. Every
#: assertion below reads THIS, so a word in a comment can neither create a
#: table nor hide one.
def _statements() -> str:
    return "\n".join(line
                     for declaring in (CANONICAL, HEALTH)
                     for line in declaring.read_text(encoding="utf-8").splitlines()
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
#: sessions and unsaved drafts live in the openDox database." THEN THE TWO
#: HEALTH TABLES, transcribed from R2Q13 option (a)'s text (plan 038's
#: `clarify-questions.md:651-653`), which Brett Heap ruled in opensoft/
#: openxFactory#656 comment 6003486656: "DOMAIN. The results table joins Q1's
#: list in `identity.TABLES`, and the closure test reads `0001` together with
#: `0003_`, in the same change, as the ruling's words have it" — ruling
#: `5784155201` item 4's "health results become a seventh table … with the
#: closure test moved in the SAME change". Q1's principle stands: no document,
#: and a disposable store (#1144 box 14.3).
RULED_TABLES: tuple[str, ...] = (
    "users", "memberships", "projects", "project_repositories", "sessions",
    "drafts",
    "health_runs", "health_findings",
)


def test_the_store_declares_exactly_the_tables_the_ruling_names() -> None:
    assert identity.TABLES == RULED_TABLES, (
        "`identity.TABLES` and the ruled list disagree; RULING Q1 is #656 "
        "comment 5542694957, R2Q13 (a) is #656 comment 6003486656, and this "
        "tuple is transcribed from them")


def test_the_canonical_schema_declares_exactly_rulings_six_tables() -> None:
    """The list is CLOSED. Compared as a SET, deliberately.

    The NAME keeps #1144 box 14.2's citation of it. What it reads is `0001`
    and `0003_` together, held to RULING Q1's six and R2Q13 (a)'s two: the
    seventh-table claim box 14.2 asks to see made in the open is made in
    `RULED_TABLES`, in `identity.TABLES` and in `0003_`'s header, in one change.

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
        "the tables `0001` and `0003_` declare and the ruled list disagree. "
        "RULING Q1 names six things the database owns and R2Q13 (a) adds the "
        "two health tables; another table is a claim about that boundary and "
        "has to be made in the open — in a ruling, then in this file, then in "
        "`identity.TABLES`.")


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
    assert "issuer" in names
    assert "subject" in names
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
