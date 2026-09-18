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

The one first-party import is `config`, which is stdlib-only for the same
reason and is measured to be so by
`tests_runtime/test_runtime_surface.py::test_the_stdlib_only_modules_really_import_without_the_extra`
— it is imported for the remote-URL judgement below and for nothing else.

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

from .config import credential_in_a_remote_url, redacted_remote_url

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

#: AND BOUNDED IN BYTES, not only in rows — for the one listing that returns
#: bytes. A draft is the single place this schema holds a document body, each
#: capped at the API's request limit (1 MiB, `app.MAX_REQUEST_BODY_BYTES`, and
#: `tests_runtime/test_api_endpoints.py` asserts the two numbers are the same
#: number). `MAX_PAGE_SIZE` rows of them is half a gigabyte fetched, serialized
#: and held in a worker for ONE request, and a handful of concurrent callers is
#: then an outage — a row limit is not a size limit when a row is a document
#: (Copilot review of openDox-code#25, round 12, suppressed).
#:
#: A page therefore carries no more body bytes than a single draft may, AND
#: ALWAYS AT LEAST ONE ROW: the budget is applied to the bytes BEFORE each row,
#: so a draft larger than the whole budget is still returned (and pagination
#: can always make progress) while the page stops at the first row that would
#: cross it. The page is a PREFIX either way, so `after` walks the rest.
MAX_PAGE_BODY_BYTES = 1_048_576


class CoordinationError(Exception):
    """A refused coordination operation, named. Carries no secret material."""


class NotFoundError(CoordinationError):
    """The named row does not exist. Never an empty result standing in for it."""


class ConflictError(CoordinationError):
    """A uniqueness or vocabulary rule the caller broke, named."""


class RefusedError(CoordinationError):
    """A VALUE this store will not write, named by its shape and never echoed.

    Distinct from `ConflictError`, which is about the rows that already exist:
    this one is about the argument, and it is the answer before any statement
    runs. Like every `CoordinationError` it "carries no secret material" — the
    refusal names WHAT was found (`config.credential_in_a_remote_url` returns
    the shape, not the value), because a refusal that quotes the value it
    refused writes the credential into the log that reports the refusal, which
    is the failure `cli._safe_message` exists for.
    """


#: Postgres's SQLSTATE for `foreign_key_violation`. A row naming a user or a
#: project that does not exist is a NOT-FOUND, not an internal error — and the
#: pre-check the API makes cannot close the race where the referenced row is
#: deleted between the read and the insert.
FOREIGN_KEY_VIOLATION = "23503"

#: Postgres's SQLSTATE for `unique_violation`. Matched by VALUE off the
#: exception rather than by catching `psycopg.errors.UniqueViolation`, because
#: this module imports no database driver — see the module docstring — and
#: `sqlstate` is a plain string attribute psycopg puts on every database error.
UNIQUE_VIOLATION = "23505"


def _conflict_if_duplicate(call: Any, message: str) -> Any:
    """Run `call`, turning a UNIQUE VIOLATION into a `ConflictError`.

    A CHECK-THEN-INSERT IS NOT ATOMIC, and the race is not theoretical: two
    concurrent requests can both pass the pre-check, and the loser then gets
    the database's raw error rather than this module's. `app.py` maps
    `ConflictError` to 409 and nothing else, so without this the loser of a
    slug race got a 500 for a conflict the API documents as 409 (Copilot review
    of openDox-code#25). The pre-check stays, because it produces the better
    message in the ordinary case; this is what makes the race produce the same
    answer as the check.
    """
    try:
        return call()
    except Exception as exc:  # noqa: BLE001
        sqlstate = getattr(exc, "sqlstate", None)
        if sqlstate == FOREIGN_KEY_VIOLATION:
            raise NotFoundError(
                "a row this write references does not exist (or was deleted "
                "between the check and the insert)") from exc
        if sqlstate != UNIQUE_VIOLATION:
            raise
        raise ConflictError(message) from exc


def refuse_a_remote_url_that_carries_a_credential(remote_url: str | None) -> None:
    """The one gate on `project_repositories.remote_url`, at its only writer.

    The column is stored in the clear — RULING Q1 gives this database identity
    and coordination, not secrets — and `GET /api/v1/project-repositories`
    returns it to every member of the project, so a URL carrying a password is
    a credential published to a group and written to every backup of this
    database. It is refused rather than redacted for `_broker_url`'s reason:
    redaction would make the evidence safe and leave the row wrong, and a
    remote that only works with an embedded password is not a remote this
    runtime can use — § 3.6 hands the URL to `git`, which would then carry the
    password onto the process table.

    HERE RATHER THAN IN THE ROUTE, because there is no route: the API exposes
    only the two reads today, so the writer of record is this store and a check
    in a caller would be a check in the one caller that exists. § 3.6's
    `repository_act` refuses the same shape again before it ever calls in,
    which is layering and not duplication — this one is the guarantee about the
    COLUMN.
    """
    carried = credential_in_a_remote_url(remote_url)
    if carried is not None:
        raise RefusedError(
            f"remote_url carries {carried}; this column is stored in the clear "
            "and is readable by every member of the project, so the credential "
            "belongs in the deployment's credential store and the URL belongs "
            "here without it — the value is not repeated here, because a "
            "refusal that quotes it writes it into the log that reports the "
            "refusal")


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


@dataclass(frozen=True, repr=False)
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

    def __repr__(self) -> str:
        """`remote_url` REDACTED, exactly as `RuntimeSettings.__repr__` does.

        The store refuses a credential-bearing URL on the way in, so a row
        carrying one came from an earlier build, a restore or `psql` — and the
        generated `repr` would then put it in any log line, traceback or
        pytest assertion message that names the object. The same argument
        `config` makes for its own settings object: the object built outside
        the checked path is exactly the one nothing else protects.
        """
        return (f"ProjectRepository(id={self.id!r}, "
                f"project_id={self.project_id!r}, adapter={self.adapter!r}, "
                f"location={self.location!r}, "
                f"remote_url={redacted_remote_url(self.remote_url)!r}, "
                f"created_at={self.created_at!r})")


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

#: The same list, qualified. `list_drafts` joins `drafts` to a derived table
#: that also carries `id`, so an unqualified list there is ambiguous — and one
#: spelling derived from the other is what keeps the two in step.
_DRAFT_COLUMNS_QUALIFIED = ", ".join(
    f"d.{name.strip()}" for name in _DRAFT_COLUMNS.split(","))


#: The subject name `_one` reports for a missing map row. A constant because
#: it is the same subject in three places, and three literals are three places
#: a typo can make one refusal read as a different failure.
_PROJECT_REPOSITORY = "project repository"


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
        `migrations/0001_…sql`. `email` and `display_name` are never
        authoritative here: the broker owns them, and this row is a copy for
        display.

        AN ABSENT CLAIM LEAVES THE LAST ONE, AND THAT IS THE DECISION
        (`coalesce`). The docstring used to say the fields are "refreshed from
        the token's claims on every login" and "this row records what it last
        said", which the `coalesce` does not do: a claim that stops arriving
        leaves the previous value in place (Copilot review of openDox-code#25,
        round 13, suppressed). The sentence is what was wrong, not the SQL.
        This runtime sees ONE TOKEN PER REQUEST, not a profile event: whether a
        given token carries `email` depends on the scopes that token was issued
        for, so an access token without the claim is the broker saying nothing
        about the address — not saying it is gone. Assigning `excluded.email`
        directly would make the stored value FLAP between requests made with
        different tokens by the same person.

        THE CONSEQUENCE IS STATED RATHER THAN HIDDEN: a value REMOVED at the
        broker is not cleared here, and this row can therefore show an address
        the broker no longer holds until a token arrives with a different one.
        These fields are a display copy and nothing authorizes on them —
        `(issuer, subject)` is the identity, and every authorization in this
        module asks `memberships.role`.
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

    def list_users(self, *, visible_to: str | None = None,
                   limit: int | None = None,
                   after: str | None = None) -> list[User]:
        """One page of users; `visible_to` narrows it to a principal's own.

        VISIBILITY IS A PROJECT RELATION, not a role. A principal sees itself
        and every user it shares a project with — which is the set it can
        already name in a membership — and nobody else. Without this, any
        signed-in account could enumerate every account in the install
        (Copilot review of openDox-code#25): the routes authenticated and then
        listed the whole table, while the module's own contract said every
        non-probe route asks `memberships.role`.

        `visible_to=None` is the UNSCOPED listing and stays for callers that
        are not a request — a migration tool, an operator script — so the
        narrowing is a decision the API makes rather than one the store hides.
        """
        rows = self._conn.execute(
            f"select {_USER_COLUMNS} from users u "
            "where (%s::text is null or u.id > %s) "
            "and (%s::text is null or u.id = %s or exists ("
            "  select 1 from memberships mine"
            "   join memberships theirs on theirs.project_id = mine.project_id"
            "  where mine.user_id = %s and theirs.user_id = u.id)) "
            "order by u.id limit %s",
            (after, after, visible_to, visible_to, visible_to,
             clamp_limit(limit)),
        ).fetchall()
        return [User(*row) for row in rows]

    def user_is_visible_to(self, user_id: str, *, viewer_id: str) -> bool:
        """Whether `viewer_id` may see `user_id` at all. Itself, always."""
        if user_id == viewer_id:
            return True
        row = self._conn.execute(
            "select 1 from memberships mine "
            " join memberships theirs on theirs.project_id = mine.project_id "
            "where mine.user_id = %s and theirs.user_id = %s limit 1",
            (viewer_id, user_id)).fetchone()
        return row is not None

    # -- projects ---------------------------------------------------------

    def create_project(self, *, slug: str, title: str, created_by: str) -> Project:
        row = self._conn.execute(
            f"select {_PROJECT_COLUMNS} from projects where slug = %s", (slug,)
        ).fetchone()
        if row is not None:
            raise ConflictError(f"a project already exists at slug {slug!r}")
        row = _conflict_if_duplicate(
            lambda: self._conn.execute(
                f"insert into projects ({_PROJECT_COLUMNS}) "
                f"values (%s, %s, %s, %s, now()) returning {_PROJECT_COLUMNS}",
                (new_id(), slug, title, created_by),
            ).fetchone(),
            f"a project already exists at slug {slug!r}")
        return Project(*_one(row, "project", f"slug={slug!r}"))

    def get_project(self, project_id: str) -> Project:
        row = self._conn.execute(
            f"select {_PROJECT_COLUMNS} from projects where id = %s", (project_id,)
        ).fetchone()
        return Project(*_one(row, "project", f"id={project_id!r}"))

    def list_projects(self, *, member: str | None = None,
                      limit: int | None = None,
                      after: str | None = None) -> list[Project]:
        """One page of projects; `member` narrows it to that user's own.

        A project a principal has no membership in is not that principal's to
        see — and the membership is exactly the row every other authorization
        question in this runtime is asked about.
        """
        rows = self._conn.execute(
            f"select {_PROJECT_COLUMNS} from projects p "
            "where (%s::text is null or p.id > %s) "
            "and (%s::text is null or exists ("
            "  select 1 from memberships m"
            "   where m.project_id = p.id and m.user_id = %s)) "
            "order by p.id limit %s",
            (after, after, member, member, clamp_limit(limit)),
        ).fetchall()
        return [Project(*row) for row in rows]

    # -- memberships ------------------------------------------------------

    def create_membership(self, *, user_id: str, project_id: str,
                          role: str) -> Membership:
        if role not in ROLES:
            raise ConflictError(
                f"role {role!r} is not one of {list(ROLES)}; the vocabulary is "
                "closed by `memberships_role_check` in the canonical migration")
        # A PLAIN INSERT, AND THE UNIQUENESS IS THE ANSWER. This was an
        # `on conflict (user_id, project_id) do update set role = excluded.role`
        # upsert, which made `POST /memberships` — declared a create, documented
        # as 409 on a duplicate — silently REWRITE an existing member's role and
        # still answer 201 (Copilot review of openDox-code#25). A role change is
        # a different act from a join and does not get to arrive disguised as
        # one; until this runtime declares that act, a second POST for a pair
        # that already exists is the conflict `_conflict_if_duplicate` promises.
        row = _conflict_if_duplicate(
            lambda: self._conn.execute(
                f"insert into memberships ({_MEMBERSHIP_COLUMNS}) "
                "values (%s, %s, %s, %s, now()) "
                f"returning {_MEMBERSHIP_COLUMNS}",
                (new_id(), user_id, project_id, role),
            ).fetchone(),
            f"a membership already exists for user {user_id!r} in project "
            f"{project_id!r}")
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
                         visible_to: str | None = None,
                         limit: int | None = None,
                         after: str | None = None) -> list[Membership]:
        """One page of memberships; `visible_to` narrows it to shared projects.

        A membership is who may act on a project, so it is readable by the
        people that project already belongs to and by nobody else.
        """
        rows = self._conn.execute(
            f"select {_MEMBERSHIP_COLUMNS} from memberships x "
            "where (%s::text is null or x.project_id = %s) "
            "and (%s::text is null or x.user_id = %s) "
            "and (%s::text is null or exists ("
            "  select 1 from memberships mine"
            "   where mine.project_id = x.project_id and mine.user_id = %s)) "
            "and (%s::text is null or x.id > %s) order by x.id limit %s",
            (project_id, project_id, user_id, user_id, visible_to, visible_to,
             after, after, clamp_limit(limit)),
        ).fetchall()
        return [Membership(*row) for row in rows]

    # -- the project-to-repository map ------------------------------------

    def create_project_repository(self, *, project_id: str, adapter: str,
                                  location: str,
                                  remote_url: str | None = None) -> ProjectRepository:
        refuse_a_remote_url_that_carries_a_credential(remote_url)
        row = self._conn.execute(
            f"select {_REPOSITORY_COLUMNS} from project_repositories "
            "where project_id = %s", (project_id,)
        ).fetchone()
        if row is not None:
            raise ConflictError(
                f"project {project_id!r} already maps to a repository at "
                f"{row[3]!r}; the map is one row per project (RULING C3: a "
                "plain local git repository PER PROJECT)")
        row = _conflict_if_duplicate(
            lambda: self._conn.execute(
                f"insert into project_repositories ({_REPOSITORY_COLUMNS}) "
                "values (%s, %s, %s, %s, %s, now()) "
                f"returning {_REPOSITORY_COLUMNS}",
                (new_id(), project_id, adapter, location, remote_url),
            ).fetchone(),
            f"project {project_id!r} already maps to a repository; the map is "
            "one row per project (RULING C3: a plain local git repository PER "
            "PROJECT)")
        return ProjectRepository(
            *_one(row, _PROJECT_REPOSITORY, f"project_id={project_id!r}"))

    def repository_for_project(self, project_id: str) -> ProjectRepository:
        row = self._conn.execute(
            f"select {_REPOSITORY_COLUMNS} from project_repositories "
            "where project_id = %s", (project_id,)
        ).fetchone()
        return ProjectRepository(
            *_one(row, _PROJECT_REPOSITORY, f"project_id={project_id!r}"))

    def attach_remote(self, *, project_id: str, remote_url: str) -> ProjectRepository:
        """RULING C3's "a remote can be attached later", as one UPDATE.

        Deliberately NOT a migration and deliberately not a new row: the
        ruling's own sentence is that moving a project into a governed factory
        "is a push, not a migration", and a schema that made it a re-creation
        would contradict the ruling in the one place a reader would believe it.
        """
        refuse_a_remote_url_that_carries_a_credential(remote_url)
        row = self._conn.execute(
            "update project_repositories set remote_url = %s "
            f"where project_id = %s returning {_REPOSITORY_COLUMNS}",
            (remote_url, project_id),
        ).fetchone()
        return ProjectRepository(
            *_one(row, _PROJECT_REPOSITORY, f"project_id={project_id!r}"))

    def list_project_repositories(self, *, visible_to: str | None = None,
                                  limit: int | None = None,
                                  after: str | None = None) -> list[ProjectRepository]:
        """One page of the map; `visible_to` narrows it to a member's projects.

        A `location` and a `remote_url` say where a project's documents live,
        which is not a fact about somebody else's project that any signed-in
        account is owed.
        """
        rows = self._conn.execute(
            f"select {_REPOSITORY_COLUMNS} from project_repositories r "
            "where (%s::text is null or r.id > %s) "
            "and (%s::text is null or exists ("
            "  select 1 from memberships m"
            "   where m.project_id = r.project_id and m.user_id = %s)) "
            "order by r.id limit %s",
            (after, after, visible_to, visible_to, clamp_limit(limit)),
        ).fetchall()
        return [ProjectRepository(*row) for row in rows]

    # -- sessions ---------------------------------------------------------

    def open_session(self, *, user_id: str,
                     project_id: str | None = None) -> Session:
        """Open a sitting for this user, optionally bound to one project.

        WRAPPED LIKE EVERY OTHER REFERENCING WRITE. The route checks the
        caller's membership first, so an unknown project is already a 403 — but
        the project can be deleted BETWEEN that check and this insert, and the
        raw foreign-key violation then escaped the route as a 500 for a row
        that simply is not there any more (Copilot review of openDox-code#25,
        round 10, suppressed). `_conflict_if_duplicate` is the one place this
        module turns a SQLSTATE into its own error, and this write had been
        left outside it.
        """
        row = _conflict_if_duplicate(
            lambda: self._conn.execute(
                f"insert into sessions ({_SESSION_COLUMNS}) "
                "values (%s, %s, %s, now(), now(), null) "
                f"returning {_SESSION_COLUMNS}",
                (new_id(), user_id, project_id),
            ).fetchone(),
            f"a session for user {user_id!r} on project {project_id!r}")
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

        THE SESSION-OPEN PREDICATE IS PART OF THIS WRITE, not a check the
        caller made a moment earlier. `app.put_draft` asks
        `_require_own_open_session` first — which produces the better refusal
        in the ordinary case — but that read and this insert were two
        statements, so a `DELETE /sessions/{id}` committing between them let a
        draft be written into a sitting that had ended, which is exactly what
        `require_open=True` promises cannot happen (Copilot review of
        openDox-code#25, round 10, suppressed). The `where exists` is evaluated
        by the statement that writes, so the promise is kept by one atomic act
        rather than by the interval between two. A session closed before this
        statement begins is `NotFoundError`; one closed after it begins was
        open when the draft was saved, which is the true answer.

        AND THE PREDICATE LOCKS THE SESSION ROW (`for update`), because
        "evaluated by the statement that writes" is not the same as
        "serialized with the close". Under READ COMMITTED the `exists`
        subquery reads the snapshot the statement began with, so a
        `close_session` that commits AFTER that snapshot and BEFORE this
        transaction commits left the draft written into a sitting that had
        ended — the exact window the round-10 fix was for, one level down
        (Copilot review of openDox-code#25, round 13). `for update` makes the
        subquery WAIT on a close that is in flight and then re-evaluate
        against the committed row, so the two acts are ordered rather than
        overlapping: either the save commits first and the close follows it, or
        the save sees the ended session and refuses. Measured with two real
        connections, both ways.
        """
        row = _conflict_if_duplicate(
            lambda: self._conn.execute(
                f"insert into drafts ({_DRAFT_COLUMNS}) "
                "select %s, %s, %s, %s, %s, %s, now() "
                "where exists (select 1 from sessions "
                "where id = %s and ended_at is null for update) "
                "on conflict (session_id, document_key) do update set "
                "body = excluded.body, "
                "basis_revision = excluded.basis_revision, "
                "updated_at = now() "
                f"returning {_DRAFT_COLUMNS}",
                (new_id(), session_id, project_id, document_key, body,
                 basis_revision, session_id),
            ).fetchone(),
            f"a draft of {document_key!r} in session {session_id!r}")
        # AN EMPTY RETURNING IS THE PREDICATE, and it has one cause: the
        # session is not open. Every other failure of this statement raises.
        return Draft(*_one(row, "open session", f"id={session_id!r}"))

    def get_draft(self, draft_id: str) -> Draft:
        row = self._conn.execute(
            f"select {_DRAFT_COLUMNS} from drafts where id = %s", (draft_id,)
        ).fetchone()
        return Draft(*_one(row, "draft", f"id={draft_id!r}"))

    def list_drafts(self, *, session_id: str | None = None,
                    session_ids: Sequence[str] | None = None,
                    owned_by: str | None = None,
                    project_id: str | None = None,
                    limit: int | None = None,
                    after: str | None = None,
                    max_bytes: int | None = None) -> list[Draft]:
        """One page of drafts, with EVERY FILTER APPLIED IN THE QUERY.

        `owned_by` is the ownership filter and is the one the API uses: a
        draft belongs to the sitting typing it, and that sitting belongs to one
        user, so the ownership question is `sessions.user_id` and it is asked
        as a join. The first cut asked it by materializing the principal's
        session ids and passing them as `session_ids` — correct only while a
        user has fewer than `MAX_PAGE_SIZE` sessions, after which later
        sessions' drafts vanished from the listing and an explicit `session_id`
        for one of them was refused as somebody else's (Copilot review of
        openDox-code#25). The schema puts no cap on sessions per user, so the
        cap had to leave the authorization path entirely.

        `session_ids` is kept for callers that already hold an explicit,
        bounded set. An EMPTY list is "no sessions, therefore no drafts" and is
        answered without a query; `None` is "do not filter by session".

        AND THE PAGE IS BOUNDED IN BYTES AS WELL AS IN ROWS, in the query
        (`MAX_PAGE_BODY_BYTES` — see that constant for the size, the reason and
        the always-at-least-one-row rule). In SQL rather than in the handler
        because the cost this bounds is the FETCH: a filter applied after
        `fetchall()` would already have pulled every body across the connection
        and built it in memory, which is the half-gigabyte the cap exists to
        refuse. The running sum is taken over the rows BEFORE each row, so the
        result is a prefix of the page the row limit would have returned and
        `after` pagination is unchanged.
        """
        if session_ids is not None and not session_ids:
            return []
        budget = MAX_PAGE_BODY_BYTES if max_bytes is None else max_bytes
        if budget < 1:
            raise CoordinationError(
                f"a draft page byte budget of {budget} can return no row at "
                "all; the budget bounds the bytes BEFORE a row, so it must be "
                "at least 1")
        # THE BODIES ARE FETCHED FOR THE ROWS THE BUDGET KEEPS, and not for
        # the whole candidate page. The inner query used to carry every
        # `body` through the window and the sort before the outer predicate
        # dropped them, so a page of 500 one-megabyte drafts still made
        # Postgres read and move ~500 MB to return a short prefix — the
        # database cost this cap exists to bound (Copilot review of
        # openDox-code#25, round 15, suppressed). The inner query now selects
        # IDS and sizes; the bodies are joined back on the ids that survive.
        rows = self._conn.execute(
            f"select {_DRAFT_COLUMNS_QUALIFIED} from drafts d join ("
            "  select d.id, coalesce(sum(octet_length(d.body)) "
            "     over (order by d.id rows between unbounded preceding "
            "           and 1 preceding), 0) as bytes_before "
            "  from drafts d "
            "  where (%s::text is null or d.session_id = %s) "
            "  and (%s::text[] is null or d.session_id = any(%s)) "
            "  and (%s::text is null or exists ("
            "    select 1 from sessions s"
            "     where s.id = d.session_id and s.user_id = %s)) "
            "  and (%s::text is null or d.project_id = %s) "
            "  and (%s::text is null or d.id > %s) order by d.id limit %s"
            ") page on page.id = d.id "
            " where page.bytes_before < %s order by d.id",
            (session_id, session_id,
             list(session_ids) if session_ids is not None else None,
             list(session_ids) if session_ids is not None else None,
             owned_by, owned_by,
             project_id, project_id, after, after, clamp_limit(limit),
             budget),
        ).fetchall()
        return [Draft(*row) for row in rows]

    def delete_draft(self, draft_id: str) -> None:
        """Discard an unsaved draft. The corpus is untouched either way."""
        row = self._conn.execute(
            "delete from drafts where id = %s returning id", (draft_id,)
        ).fetchone()
        _one(row, "draft", f"id={draft_id!r}")
