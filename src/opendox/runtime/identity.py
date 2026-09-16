"""The coordination store: the six tables RULING Q1 names, and nothing else.

RULING Q1 (opensoft/openxFactory#656 comment 5542694957): "the database owns
identity and coordination; git owns governed artifacts. Users, memberships,
projects, the project-to-repository mapping, sessions and unsaved drafts live
in the openDox database. Specs, changes, ideation documents and contracts stay
in git, read from repositories and written back only through the apply lane."

So this module has exactly six record types and one store, and `TABLES` below
is the closed list a test reads against `migrations/0001_…sql`. There is no
`documents` table, no `specs` table and no `content` column outside
`drafts.body` — the one Q1 rules IN, because an unsaved draft is by definition
the text that has not entered the corpus yet.

EVERY STATEMENT IS COMPOSED FROM MODULE-LEVEL CONSTANTS AND EVERY RUNTIME VALUE
IS A `%s` PARAMETER. Table and column names below are literals in this file;
nothing a caller supplies is ever interpolated into SQL. The Hermes install
records the same rule for the same reason in its own `pyproject.toml`
(`per-file-ignores` for S608: "Repository/persistence SQL is composed only from
module-level constants … every runtime value is passed as a psycopg %s
parameter, never interpolated").

NO DRIVER IS IMPORTED HERE. The store is handed a connection — anything with
`.execute(sql, params)` returning a cursor with `.fetchone()` / `.fetchall()` —
so this module imports under the leg's `validate` check, which installs
`.[test]` and not `.[runtime]`. See `opendox/runtime/__init__.py`'s
import-weight contract.

IDENTITY IS A DURABLE ROW, WHICH INVERTS A PROMOTED RULE, and `upsert_user` is
where the inversion happens. Design § D5: "Two current requirements say in
terms that the dashboard authorizes nothing on the hosted actor and that
identity presence changes no capability verdict — write authority today is a
property of WHERE the request came from (a loopback console verdict), not WHO
sent it. Q1 and Q2 together invert that: an account is a durable row,
authentication delegates to the Keycloak broker, and authorization stops being
a property of the request's origin." A first login therefore WRITES, and the
row it writes is the subject of every later authorization question.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

#: The closed table list, in RULING Q1's own order. Read by
#: `tests_runtime/test_schema_shape.py` against the canonical migration: a
#: seventh table here or there is a claim about what the database owns.
TABLES: tuple[str, ...] = (
    "users",
    "memberships",
    "projects",
    "project_repositories",
    "sessions",
    "drafts",
)

#: The closed role vocabulary, matching `memberships_role_check` in
#: `migrations/0001_identity_and_coordination.sql`.
ROLES: tuple[str, ...] = ("owner", "member", "reader")

#: Bounded queries. Every list takes a LIMIT; a caller cannot ask for an
#: unbounded scan. The pagination cursor is the row's text primary key, which
#: is "a stable total order independent of the wall clock" — the Hermes
#: install's own reason, in `persistence/database.py`, and it holds here for
#: the same host.
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500


class CoordinationError(Exception):
    """A refused coordination operation, named. Carries no secret material."""


class NotFoundError(CoordinationError):
    """The named row does not exist. Never an empty result standing in for it."""


class ConflictError(CoordinationError):
    """A uniqueness or vocabulary rule the caller broke, named."""


def clamp_limit(limit: int | None) -> int:
    """Clamp a requested page size into `[1, MAX_PAGE_SIZE]`."""
    if limit is None:
        return DEFAULT_PAGE_SIZE
    if limit < 1:
        return 1
    return min(limit, MAX_PAGE_SIZE)


def new_id() -> str:
    """A fresh row identity.

    Application-generated rather than server-generated, so the schema needs no
    id extension and an id can be known before the insert it is part of — which
    is what lets `create_project_with_repository` write a project row, a
    membership row and a map row in ONE transaction naming ids it already has.
    """
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# records — frozen, and each one is exactly its table's columns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class User:
    id: str
    issuer: str
    subject: str
    email: str | None
    display_name: str | None
    created_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class Membership:
    id: str
    user_id: str
    project_id: str
    role: str
    created_at: datetime


@dataclass(frozen=True)
class Project:
    id: str
    slug: str
    title: str
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class ProjectRepository:
    """One project's entry in the PROJECT-TO-REPOSITORY MAP (RULING Q1).

    `adapter` and `location` are the whole of what distinguishes a student's
    plain local git repository from a governed factory's — `location` is opaque
    here exactly as `corpus_adapter.CorpusRef.location` is. `remote_url` is
    nullable because RULING C3 says a remote "can be attached later", and
    attaching one is an update of this column.
    """

    id: str
    project_id: str
    adapter: str
    location: str
    remote_url: str | None
    created_at: datetime


@dataclass(frozen=True)
class Session:
    id: str
    user_id: str
    project_id: str | None
    started_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True)
class Draft:
    """UNSAVED text, and the only bytes this schema holds (RULING Q1).

    `document_key` is where it would be written back (a
    `corpus_adapter.DocumentId.key`, opaque) and `basis_revision` is the
    revision the author was looking at — what `write_back` needs "in order to
    refuse a stale one".
    """

    id: str
    session_id: str
    project_id: str
    document_key: str
    body: str
    basis_revision: str | None
    updated_at: datetime


_USER_COLUMNS = "id, issuer, subject, email, display_name, created_at, last_seen_at"
_MEMBERSHIP_COLUMNS = "id, user_id, project_id, role, created_at"
_PROJECT_COLUMNS = "id, slug, title, created_by, created_at"
_REPOSITORY_COLUMNS = "id, project_id, adapter, location, remote_url, created_at"
_SESSION_COLUMNS = "id, user_id, project_id, started_at, last_seen_at, ended_at"
_DRAFT_COLUMNS = (
    "id, session_id, project_id, document_key, body, basis_revision, updated_at")


def _one(row: Sequence[Any] | None, what: str, key: str) -> Sequence[Any]:
    if row is None:
        raise NotFoundError(f"no {what} with {key}")
    return row


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------


class CoordinationStore:
    """Every read and write of the six tables, over ONE connection.

    The connection is the caller's unit of work: a caller that needs two writes
    to be atomic opens one transaction and hands the same connection to both
    calls. No method here opens, commits or rolls back anything — a store that
    committed on its own would make `create_project_with_repository`'s
    three-row act impossible to keep atomic.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    # -- users ------------------------------------------------------------

    def upsert_user(self, *, issuer: str, subject: str,
                    email: str | None = None,
                    display_name: str | None = None) -> User:
        """FIRST LOGIN WRITES THE ROW; every later login refreshes it.

        `(issuer, subject)` is the broker's identity and the natural key — see
        `migrations/0001_…sql`. `email` and `display_name` are refreshed from
        the token's claims on every login and are never authoritative here:
        the broker owns them, this row records what it last said.
        """
        row = self._conn.execute(
            f"insert into users ({_USER_COLUMNS}) "
            "values (%s, %s, %s, %s, %s, now(), now()) "
            "on conflict (issuer, subject) do update set "
            "email = coalesce(excluded.email, users.email), "
            "display_name = coalesce(excluded.display_name, users.display_name), "
            "last_seen_at = now() "
            f"returning {_USER_COLUMNS}",
            (new_id(), issuer, subject, email, display_name),
        ).fetchone()
        return User(*_one(row, "user", f"issuer={issuer!r} subject={subject!r}"))

    def get_user(self, user_id: str) -> User:
        row = self._conn.execute(
            f"select {_USER_COLUMNS} from users where id = %s", (user_id,)
        ).fetchone()
        return User(*_one(row, "user", f"id={user_id!r}"))

    def list_users(self, *, limit: int | None = None,
                   after: str | None = None) -> list[User]:
        rows = self._conn.execute(
            f"select {_USER_COLUMNS} from users "
            "where (%s::text is null or id > %s) order by id limit %s",
            (after, after, clamp_limit(limit)),
        ).fetchall()
        return [User(*row) for row in rows]

    # -- projects ---------------------------------------------------------

    def create_project(self, *, slug: str, title: str, created_by: str) -> Project:
        row = self._conn.execute(
            f"select {_PROJECT_COLUMNS} from projects where slug = %s", (slug,)
        ).fetchone()
        if row is not None:
            raise ConflictError(f"a project already exists at slug {slug!r}")
        row = self._conn.execute(
            f"insert into projects ({_PROJECT_COLUMNS}) "
            f"values (%s, %s, %s, %s, now()) returning {_PROJECT_COLUMNS}",
            (new_id(), slug, title, created_by),
        ).fetchone()
        return Project(*_one(row, "project", f"slug={slug!r}"))

    def get_project(self, project_id: str) -> Project:
        row = self._conn.execute(
            f"select {_PROJECT_COLUMNS} from projects where id = %s", (project_id,)
        ).fetchone()
        return Project(*_one(row, "project", f"id={project_id!r}"))

    def list_projects(self, *, limit: int | None = None,
                      after: str | None = None) -> list[Project]:
        rows = self._conn.execute(
            f"select {_PROJECT_COLUMNS} from projects "
            "where (%s::text is null or id > %s) order by id limit %s",
            (after, after, clamp_limit(limit)),
        ).fetchall()
        return [Project(*row) for row in rows]

    # -- memberships ------------------------------------------------------

    def create_membership(self, *, user_id: str, project_id: str,
                          role: str) -> Membership:
        if role not in ROLES:
            raise ConflictError(
                f"role {role!r} is not one of {list(ROLES)}; the vocabulary is "
                "closed by `memberships_role_check` in the canonical migration")
        row = self._conn.execute(
            f"insert into memberships ({_MEMBERSHIP_COLUMNS}) "
            "values (%s, %s, %s, %s, now()) "
            "on conflict (user_id, project_id) do update set role = excluded.role "
            f"returning {_MEMBERSHIP_COLUMNS}",
            (new_id(), user_id, project_id, role),
        ).fetchone()
        return Membership(*_one(row, "membership",
                                f"user_id={user_id!r} project_id={project_id!r}"))

    def membership_for(self, *, user_id: str, project_id: str) -> Membership:
        row = self._conn.execute(
            f"select {_MEMBERSHIP_COLUMNS} from memberships "
            "where user_id = %s and project_id = %s", (user_id, project_id)
        ).fetchone()
        return Membership(*_one(row, "membership",
                                f"user_id={user_id!r} project_id={project_id!r}"))

    def list_memberships(self, *, project_id: str | None = None,
                         user_id: str | None = None,
                         limit: int | None = None,
                         after: str | None = None) -> list[Membership]:
        rows = self._conn.execute(
            f"select {_MEMBERSHIP_COLUMNS} from memberships "
            "where (%s::text is null or project_id = %s) "
            "and (%s::text is null or user_id = %s) "
            "and (%s::text is null or id > %s) order by id limit %s",
            (project_id, project_id, user_id, user_id, after, after,
             clamp_limit(limit)),
        ).fetchall()
        return [Membership(*row) for row in rows]

    # -- the project-to-repository map ------------------------------------

    def create_project_repository(self, *, project_id: str, adapter: str,
                                  location: str,
                                  remote_url: str | None = None) -> ProjectRepository:
        row = self._conn.execute(
            f"select {_REPOSITORY_COLUMNS} from project_repositories "
            "where project_id = %s", (project_id,)
        ).fetchone()
        if row is not None:
            raise ConflictError(
                f"project {project_id!r} already maps to a repository at "
                f"{row[3]!r}; the map is one row per project (RULING C3: a "
                "plain local git repository PER PROJECT)")
        row = self._conn.execute(
            f"insert into project_repositories ({_REPOSITORY_COLUMNS}) "
            f"values (%s, %s, %s, %s, %s, now()) returning {_REPOSITORY_COLUMNS}",
            (new_id(), project_id, adapter, location, remote_url),
        ).fetchone()
        return ProjectRepository(
            *_one(row, "project repository", f"project_id={project_id!r}"))

    def repository_for_project(self, project_id: str) -> ProjectRepository:
        row = self._conn.execute(
            f"select {_REPOSITORY_COLUMNS} from project_repositories "
            "where project_id = %s", (project_id,)
        ).fetchone()
        return ProjectRepository(
            *_one(row, "project repository", f"project_id={project_id!r}"))

    def attach_remote(self, *, project_id: str, remote_url: str) -> ProjectRepository:
        """RULING C3's "a remote can be attached later", as one UPDATE.

        Deliberately NOT a migration and deliberately not a new row: the
        ruling's own sentence is that moving a project into a governed factory
        "is a push, not a migration", and a schema that made it a re-creation
        would contradict the ruling in the one place a reader would believe it.
        """
        row = self._conn.execute(
            "update project_repositories set remote_url = %s "
            f"where project_id = %s returning {_REPOSITORY_COLUMNS}",
            (remote_url, project_id),
        ).fetchone()
        return ProjectRepository(
            *_one(row, "project repository", f"project_id={project_id!r}"))

    def list_project_repositories(self, *, limit: int | None = None,
                                  after: str | None = None) -> list[ProjectRepository]:
        rows = self._conn.execute(
            f"select {_REPOSITORY_COLUMNS} from project_repositories "
            "where (%s::text is null or id > %s) order by id limit %s",
            (after, after, clamp_limit(limit)),
        ).fetchall()
        return [ProjectRepository(*row) for row in rows]

    # -- sessions ---------------------------------------------------------

    def open_session(self, *, user_id: str,
                     project_id: str | None = None) -> Session:
        row = self._conn.execute(
            f"insert into sessions ({_SESSION_COLUMNS}) "
            f"values (%s, %s, %s, now(), now(), null) returning {_SESSION_COLUMNS}",
            (new_id(), user_id, project_id),
        ).fetchone()
        return Session(*_one(row, "session", f"user_id={user_id!r}"))

    def touch_session(self, session_id: str) -> Session:
        row = self._conn.execute(
            "update sessions set last_seen_at = now() "
            f"where id = %s and ended_at is null returning {_SESSION_COLUMNS}",
            (session_id,),
        ).fetchone()
        return Session(*_one(row, "open session", f"id={session_id!r}"))

    def close_session(self, session_id: str) -> Session:
        row = self._conn.execute(
            "update sessions set ended_at = now() "
            f"where id = %s and ended_at is null returning {_SESSION_COLUMNS}",
            (session_id,),
        ).fetchone()
        return Session(*_one(row, "open session", f"id={session_id!r}"))

    def get_session(self, session_id: str) -> Session:
        row = self._conn.execute(
            f"select {_SESSION_COLUMNS} from sessions where id = %s", (session_id,)
        ).fetchone()
        return Session(*_one(row, "session", f"id={session_id!r}"))

    def list_sessions(self, *, user_id: str | None = None,
                      limit: int | None = None,
                      after: str | None = None) -> list[Session]:
        rows = self._conn.execute(
            f"select {_SESSION_COLUMNS} from sessions "
            "where (%s::text is null or user_id = %s) "
            "and (%s::text is null or id > %s) order by id limit %s",
            (user_id, user_id, after, after, clamp_limit(limit)),
        ).fetchall()
        return [Session(*row) for row in rows]

    # -- drafts -----------------------------------------------------------

    def put_draft(self, *, session_id: str, project_id: str, document_key: str,
                  body: str, basis_revision: str | None = None) -> Draft:
        """Create or replace the unsaved draft for one document in one session.

        Keyed by `(session_id, document_key)`: a draft belongs to the sitting
        that is typing it, so two sessions editing the same document hold two
        drafts and neither silently overwrites the other. Resolving them is the
        apply lane's business, not the database's.
        """
        row = self._conn.execute(
            f"insert into drafts ({_DRAFT_COLUMNS}) "
            "values (%s, %s, %s, %s, %s, %s, now()) "
            "on conflict (session_id, document_key) do update set "
            "body = excluded.body, basis_revision = excluded.basis_revision, "
            "updated_at = now() "
            f"returning {_DRAFT_COLUMNS}",
            (new_id(), session_id, project_id, document_key, body, basis_revision),
        ).fetchone()
        return Draft(*_one(row, "draft", f"document_key={document_key!r}"))

    def get_draft(self, draft_id: str) -> Draft:
        row = self._conn.execute(
            f"select {_DRAFT_COLUMNS} from drafts where id = %s", (draft_id,)
        ).fetchone()
        return Draft(*_one(row, "draft", f"id={draft_id!r}"))

    def list_drafts(self, *, session_id: str | None = None,
                    project_id: str | None = None,
                    limit: int | None = None,
                    after: str | None = None) -> list[Draft]:
        rows = self._conn.execute(
            f"select {_DRAFT_COLUMNS} from drafts "
            "where (%s::text is null or session_id = %s) "
            "and (%s::text is null or project_id = %s) "
            "and (%s::text is null or id > %s) order by id limit %s",
            (session_id, session_id, project_id, project_id, after, after,
             clamp_limit(limit)),
        ).fetchall()
        return [Draft(*row) for row in rows]

    def delete_draft(self, draft_id: str) -> None:
        """Discard an unsaved draft. The corpus is untouched either way."""
        row = self._conn.execute(
            "delete from drafts where id = %s returning id", (draft_id,)
        ).fetchone()
        _one(row, "draft", f"id={draft_id!r}")
