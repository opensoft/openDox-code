"""The FastAPI application: six coordination collections behind the broker.

RULING Q2 (opensoft/openxFactory#656 comment 5542792997) makes this FastAPI +
Postgres on the `xFactory-Hermes-Install` pattern; RULING Q1 (comment
5542694957) fixes what it serves. Every route below reads or writes ONE of the
six tables the canonical migration declares, and there is no route that reads a
document: specs, changes, ideation documents and contracts are read from
repositories and written back only through the apply lane.

THE ROUTE SET IS THE COLLECTION SET. `opendox.runtime.COLLECTIONS` is the
closed tuple and `tests_runtime/test_runtime_surface.py` reads the mounted
routes against it, so a seventh collection cannot appear without the tuple
moving — the same closure `corpus_adapter.OPERATIONS` keeps over the adapter's
six operations, for the same reason.

AUTHENTICATION IS THE BROKER'S; AUTHORIZATION IS A ROW. Design § D5: "an
account is a durable row, authentication delegates to the Keycloak broker, and
authorization stops being a property of the request's origin." So:

  * THE UNAUTHENTICATED SURFACE IS `/livez` AND `/readyz`, and it is exactly
    those two. Both are ORCHESTRATOR PROBES: a liveness probe that needed a
    bearer token would need the broker to be up in order to discover that the
    broker is down, and a readiness probe that needed one could never report an
    unreachable database. They answer about THIS PROCESS's dependencies and
    return no row, no id and no document. `/livez` answers before any
    dependency is reachable — the Hermes install's own shape, so a probe never
    reports a broker outage as a dead process.

    The first cut of this docstring said `/livez` was the only one, which was
    wrong twice over: `/readyz` was already public, and FastAPI's defaults also
    published `/docs`, `/redoc` and `/openapi.json` (Copilot review of
    openDox-code#25). The schema viewers are now OFF unless
    `OPENDOX_PUBLISH_OPENAPI` says otherwise, and
    `tests_runtime/test_api_endpoints.py` enumerates the unauthenticated routes
    against this list rather than trusting it.
  * every other route resolves a bearer token to an `identity.User` row and
    then asks `memberships.role` about THAT row. There is no loopback
    exemption, no `--allow-local` and no header that stands in for a token:
    those are exactly what the inversion removes.

THE APPLICATION OPENS THE POOL, THE MIGRATIONS ARE NOT APPLIED HERE. Schema is
applied by `opendox runtime migrate` with the privileged DSN and never at
request time — the Hermes install records the same separation ("Privileged
one-shot migration executor. This service is never the long-running application
container and receives no runtime DSN"), and `/readyz` reports an unmigrated
database rather than migrating it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from opendox.runtime import API_V1, identity, migrations, oidc
from opendox.runtime.config import RuntimeSettings, load_settings

# ---------------------------------------------------------------------------
# request bodies — every write verb takes a declared shape
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)


class MembershipCreate(BaseModel):
    user_id: str
    project_id: str
    role: str


class RemoteAttach(BaseModel):
    remote_url: str = Field(min_length=1)


class SessionCreate(BaseModel):
    project_id: str | None = None


class DraftPut(BaseModel):
    session_id: str
    project_id: str
    document_key: str = Field(min_length=1)
    body: str
    basis_revision: str | None = None


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------


class AppContext:
    """What one application process was assembled with.

    Constructed by :func:`create_app` and stashed on the app's state, so tests
    hand in a `Database` pointed at a throwaway schema and a verifier built
    over a file key set without patching a module global.
    """

    def __init__(self, *, settings: RuntimeSettings, database: Any,
                 verifier: Any) -> None:
        self.settings = settings
        self.database = database
        self.verifier = verifier


def _context(request: Request) -> AppContext:
    # ANNOTATED `Request` AND NOT `Any`, and it is load-bearing: FastAPI reads
    # a dependency's annotations to decide where each argument comes from, and
    # a parameter typed `Any` is taken for a QUERY PARAMETER — every route
    # would then answer 422 "missing query parameter: request" instead of
    # authenticating. Measured, not assumed: that is exactly what the first
    # run of `tests_runtime/test_api_endpoints.py` reported, on sixteen cases.
    return request.app.state.context  # type: ignore[no-any-return]


def get_context(request: Request) -> AppContext:
    return _context(request)


class _LazyStore:
    """A `CoordinationStore` that checks a connection out ON FIRST USE.

    WHY LAZY. `get_principal` depends on the store, and FastAPI resolves a
    dependency before it calls the function that asked for it — so an EAGER
    store opened a transaction and took a pooled connection before anybody had
    looked at the `Authorization` header. A request with no bearer token, or a
    forged one, then failed with a database error whenever Postgres was
    unreachable or the pool was exhausted, instead of the 401 it had earned
    (Copilot review of openDox-code#25): the cheapest possible refusal was
    made to depend on the most expensive resource in the process.

    Deferring the checkout keeps the transaction semantics a route needs — the
    FIRST use opens it, every later use is the same connection, and the
    teardown commits or rolls it back — while an unauthenticated request now
    touches no connection at all.
    """

    def __init__(self, database: Any) -> None:
        self._database = database
        self._exit: Any = None
        self._store: identity.CoordinationStore | None = None

    def _open(self) -> identity.CoordinationStore:
        if self._store is None:
            self._exit = self._database.transaction()
            self._store = identity.CoordinationStore(self._exit.__enter__())
        return self._store

    def __getattr__(self, name: str) -> Any:
        return getattr(self._open(), name)

    def close(self, exc: BaseException | None) -> None:
        if self._exit is None:
            return
        if exc is None:
            self._exit.__exit__(None, None, None)
        else:
            self._exit.__exit__(type(exc), exc, exc.__traceback__)


def get_store(request: Request) -> Iterator[Any]:
    """One transaction per request, opened on first use, and one store over it.

    A request that writes three rows writes them atomically because they share
    this connection; a request that only reads still gets one consistent
    snapshot; and a request that is refused before it reads anything opens no
    transaction at all.
    """
    context = _context(request)
    store = _LazyStore(context.database)
    try:
        yield store
    except BaseException as exc:
        store.close(exc)
        raise
    else:
        store.close(None)


def get_principal(
    request: Request,
    store: Annotated[Any, Depends(get_store)],
    authorization: Annotated[str | None, Header()] = None,
) -> identity.User:
    """The DURABLE ROW this request is made by (design § D5's inversion).

    A missing or malformed `Authorization: Bearer …` is 401 and says which,
    without echoing the header back.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "auth.missing_bearer",
                    "message": "an Authorization: Bearer <token> header is "
                               "required; this runtime authorizes a user row, "
                               "never a request origin"})
    token = authorization.split(" ", 1)[1].strip()
    context = _context(request)
    try:
        claims = context.verifier.verify(token)
    except oidc.OidcError as exc:
        raise HTTPException(status_code=401,
                            detail={"code": exc.code,
                                    "message": str(exc)}) from exc
    return oidc.principal_for(store, claims)


StoreDep = Annotated[Any, Depends(get_store)]
PrincipalDep = Annotated[identity.User, Depends(get_principal)]
LimitQuery = Annotated[int | None, Query(ge=1, le=identity.MAX_PAGE_SIZE)]


def _require_own_open_session(store: Any, *,
                              user: identity.User, session_id: str,
                              project_id: str,
                              require_open: bool = True) -> identity.Session:
    """The session is this principal's, and it is this project's.

    MEMBERSHIP IS NOT ENOUGH FOR A DRAFT. `drafts` is keyed by
    `(session_id, document_key)`, so a member who could name another member's
    session id could overwrite — or discard — that member's unsaved text
    through the upsert, and be a legitimate member of the project the whole
    time (Copilot review of openDox-code#25, critical on the write path and on
    the delete). A draft belongs to the sitting typing it; this is where that
    is enforced.

    `require_open` is False on the discard path: a draft left by a session that
    has since ended is still that user's to throw away.
    """
    session = _found(lambda: store.get_session(session_id))
    if session.user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail={"code": "authz.not_your_session",
                    "message": "a draft belongs to the session typing it, and "
                               "that session is not this principal's"})
    if session.project_id != project_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "coordination.session_project_mismatch",
                    "message": f"session {session_id} is open on project "
                               f"{session.project_id}, not {project_id}"})
    if require_open and session.ended_at is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "coordination.session_closed",
                    "message": f"session {session_id} has ended; open a new "
                               "one before saving"})
    return session


def _require_role(store: Any, *, user: identity.User,
                  project_id: str, allowed: tuple[str, ...]) -> identity.Membership:
    """Authorization, asked about the ROW and answered by `memberships.role`."""
    try:
        membership = store.membership_for(user_id=user.id, project_id=project_id)
    except identity.NotFoundError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "authz.not_a_member",
                    "message": f"user {user.id} has no membership in project "
                               f"{project_id}"}) from exc
    if membership.role not in allowed:
        raise HTTPException(
            status_code=403,
            detail={"code": "authz.role_insufficient",
                    "message": f"role {membership.role!r} is not one of "
                               f"{list(allowed)} for project {project_id}"})
    return membership


# ---------------------------------------------------------------------------
# routers — one per collection, in `COLLECTIONS` order
# ---------------------------------------------------------------------------

#: THE REFUSALS EVERY AUTHENTICATED ROUTE CAN RETURN, declared once and hung on
#: each router, so the published OpenAPI schema says what a client must handle
#: rather than leaving it to be discovered (SonarCloud `python:S8415`). Every
#: refusal body is `{"detail": {"code": ..., "message": ...}}` — a STABLE
#: machine `code` a client branches on, and a message for a human, which is the
#: same shape `corpus_adapter.Refusal` uses one layer down.
REFUSALS: dict[int | str, dict[str, Any]] = {
    401: {"description": "no bearer token, or one the broker's keys do not "
                         "verify (`auth.*`)"},
    403: {"description": "a verified principal whose `memberships.role` does "
                         "not permit this act (`authz.*`)"},
    404: {"description": "no such row (`coordination.not_found`)"},
    409: {"description": "a uniqueness or vocabulary rule the caller broke "
                         "(`coordination.conflict`, `repository.refused`)"},
}

users = APIRouter(prefix="/users", tags=["users"], responses=REFUSALS)
memberships = APIRouter(prefix="/memberships", tags=["memberships"],
                        responses=REFUSALS)
projects = APIRouter(prefix="/projects", tags=["projects"],
                     responses=REFUSALS)
project_repositories = APIRouter(prefix="/project-repositories",
                                 tags=["project-repositories"],
                                 responses=REFUSALS)
sessions = APIRouter(prefix="/sessions", tags=["sessions"],
                     responses=REFUSALS)
drafts = APIRouter(prefix="/drafts", tags=["drafts"],
                   responses=REFUSALS)


@users.get("/me")
def read_me(principal: PrincipalDep) -> dict[str, Any]:
    """The row this token resolved to — the whole of the inversion, visible."""
    return _user_json(principal)


# `del principal` IN A READ HANDLER IS DELIBERATE AND IS SAID ONCE HERE. The
# `PrincipalDep` parameter is what makes the route authenticated at all —
# FastAPI resolves the dependency, which verifies the token and upserts the row,
# before the body runs — and a handler that does not then USE the value is a
# handler whose authorization is "any signed-in principal may read this". `del`
# states that in code instead of leaving an argument that looks forgotten. A
# route that narrows further calls `_require_role`, and every write does.


@users.get("")
def list_users(store: StoreDep, principal: PrincipalDep,
               limit: LimitQuery = None,
               after: str | None = None) -> list[dict[str, Any]]:
    del principal
    return [_user_json(u) for u in store.list_users(limit=limit, after=after)]


@users.get("/{user_id}")
def read_user(user_id: str, store: StoreDep,
              principal: PrincipalDep) -> dict[str, Any]:
    del principal
    return _user_json(_found(lambda: store.get_user(user_id)))


@memberships.get("")
def list_memberships(store: StoreDep, principal: PrincipalDep,
                     project_id: str | None = None,
                     user_id: str | None = None,
                     limit: LimitQuery = None,
                     after: str | None = None) -> list[dict[str, Any]]:
    del principal
    return [_membership_json(m) for m in store.list_memberships(
        project_id=project_id, user_id=user_id, limit=limit, after=after)]


@memberships.post("", status_code=201)
def create_membership(body: MembershipCreate, store: StoreDep,
                      principal: PrincipalDep) -> dict[str, Any]:
    _require_role(store, user=principal, project_id=body.project_id,
                  allowed=("owner",))
    # BOTH REFERENCED ROWS ARE RESOLVED FIRST. Without this, a body naming a
    # user or project that does not exist reached the insert and came back as
    # the database's foreign-key violation — which `_conflict` does not
    # translate, so the caller got a 500 for a request whose only fault was a
    # wrong id (Copilot review of openDox-code#25). `_found` makes it the 404
    # it is. `identity` also translates a foreign-key violation now, for the
    # race where the row is deleted between this read and the insert.
    _found(lambda: store.get_user(body.user_id))
    _found(lambda: store.get_project(body.project_id))
    return _membership_json(_conflict(lambda: store.create_membership(
        user_id=body.user_id, project_id=body.project_id, role=body.role)))


@projects.get("")
def list_projects(store: StoreDep, principal: PrincipalDep,
                  limit: LimitQuery = None,
                  after: str | None = None) -> list[dict[str, Any]]:
    del principal
    return [_project_json(p) for p in store.list_projects(limit=limit, after=after)]


@projects.post("", status_code=201)
def create_project(body: ProjectCreate, store: StoreDep,
                   principal: PrincipalDep) -> dict[str, Any]:
    """Create a project and make its creator the owner, in ONE transaction.

    The repository is NOT created here: `split-opendox-two-layer-product` § 3.6
    makes repository creation a first-class act with its own verb, so a project
    that has no repository yet is a visible state rather than a half-finished
    write.
    """
    project = _conflict(lambda: store.create_project(
        slug=body.slug, title=body.title, created_by=principal.id))
    store.create_membership(user_id=principal.id, project_id=project.id,
                            role="owner")
    return _project_json(project)


@projects.get("/{project_id}")
def read_project(project_id: str, store: StoreDep,
                 principal: PrincipalDep) -> dict[str, Any]:
    del principal
    return _project_json(_found(lambda: store.get_project(project_id)))


# ---------------------------------------------------------------------------
# § 3.6 — THE REPOSITORY-CREATION ACT, on the project it belongs to
#
# "openDox CREATES A REPOSITORY AS A FIRST-CLASS ACT, or the origin complaint
# returns one level down" (`split-opendox-two-layer-product` § 3.6). A verb,
# not a side effect of `POST /projects`: a project with no repository yet is a
# visible state, and the act that gives it one is a thing somebody did.
#
# These three routes hang off `/projects/{id}/repository` rather than off the
# `project-repositories` collection, because the act is performed ON A PROJECT
# and the collection is the map it writes into. `COLLECTIONS` therefore does
# not grow: the closed six are what the database owns, and this is a verb over
# one of them.
# ---------------------------------------------------------------------------


@projects.post("/{project_id}/repository", status_code=201)
def create_project_repository(project_id: str, request: Request,
                              store: StoreDep,
                              principal: PrincipalDep) -> dict[str, Any]:
    """Create this project's plain local git repository (RULING C3).

    Writes the map row and creates the repository in ONE act, in this
    request's transaction — see `repository_act`'s header for why the row goes
    first and what the remaining window is.
    """
    from opendox.runtime import repository_act

    _found(lambda: store.get_project(project_id))
    _require_role(store, user=principal, project_id=project_id,
                  allowed=("owner",))
    settings = _context(request).settings
    try:
        created = _conflict(lambda: repository_act.create_repository(
            store, project_id=project_id,
            root=settings.project_repository_root,
            actor=principal.display_name or principal.subject))
    except repository_act.RepositoryActRefused as exc:
        raise HTTPException(status_code=409,
                            detail={"code": "repository.refused",
                                    "message": str(exc)}) from exc
    body = _repository_json(created.row)
    body["initial_commit"] = created.initial_commit
    return body


@projects.put("/{project_id}/repository/remote")
def attach_project_remote(project_id: str, body: RemoteAttach, store: StoreDep,
                          principal: PrincipalDep) -> dict[str, Any]:
    """RULING C3's "a remote can be attached later" — one update, no migration."""
    from opendox.runtime import repository_act

    _require_role(store, user=principal, project_id=project_id,
                  allowed=("owner",))
    _found(lambda: store.repository_for_project(project_id))
    try:
        # The credential check happens in the act, so the CLI gets it too; this
        # route only has to let the refusal through as a 409 with a message
        # that never echoes the URL.
        row = repository_act.attach_remote(store, project_id=project_id,
                                           remote_url=body.remote_url)
    except repository_act.RepositoryActRefused as exc:
        raise HTTPException(status_code=409,
                            detail={"code": "repository.refused",
                                    "message": str(exc)}) from exc
    return _repository_json(row)


@projects.post("/{project_id}/repository/push")
def push_project_repository(project_id: str, store: StoreDep,
                            principal: PrincipalDep) -> dict[str, Any]:
    """Move this project into a governed factory. RULING C3: it is a PUSH."""
    from opendox.runtime import repository_act

    _require_role(store, user=principal, project_id=project_id,
                  allowed=("owner",))
    _found(lambda: store.repository_for_project(project_id))
    try:
        remote_url = repository_act.push_to_remote(store, project_id=project_id)
    except repository_act.RepositoryActRefused as exc:
        raise HTTPException(status_code=409,
                            detail={"code": "repository.refused",
                                    "message": str(exc)}) from exc
    return {"project_id": project_id, "pushed_to": remote_url,
            "note": "a push, not a migration (RULING C3)"}


@project_repositories.get("")
def list_project_repositories(store: StoreDep, principal: PrincipalDep,
                              limit: LimitQuery = None,
                              after: str | None = None) -> list[dict[str, Any]]:
    del principal
    return [_repository_json(r) for r in store.list_project_repositories(
        limit=limit, after=after)]


@project_repositories.get("/{project_id}")
def read_project_repository(project_id: str, store: StoreDep,
                            principal: PrincipalDep) -> dict[str, Any]:
    del principal
    return _repository_json(
        _found(lambda: store.repository_for_project(project_id)))


@sessions.get("")
def list_sessions(store: StoreDep, principal: PrincipalDep,
                  limit: LimitQuery = None,
                  after: str | None = None) -> list[dict[str, Any]]:
    return [_session_json(s) for s in store.list_sessions(
        user_id=principal.id, limit=limit, after=after)]


@sessions.post("", status_code=201)
def open_session(body: SessionCreate, store: StoreDep,
                 principal: PrincipalDep) -> dict[str, Any]:
    if body.project_id is not None:
        _require_role(store, user=principal, project_id=body.project_id,
                      allowed=identity.ROLES)
    return _session_json(store.open_session(user_id=principal.id,
                                            project_id=body.project_id))


@sessions.delete("/{session_id}")
def close_session(session_id: str, store: StoreDep,
                  principal: PrincipalDep) -> dict[str, Any]:
    session = _found(lambda: store.get_session(session_id))
    if session.user_id != principal.id:
        raise HTTPException(status_code=403,
                            detail={"code": "authz.not_your_session",
                                    "message": "a session is closed by the user "
                                               "who opened it"})
    return _session_json(_found(lambda: store.close_session(session_id)))


@drafts.get("")
def list_drafts(store: StoreDep, principal: PrincipalDep,
                session_id: str | None = None,
                project_id: str | None = None,
                limit: LimitQuery = None,
                after: str | None = None) -> list[dict[str, Any]]:
    """The principal's OWN drafts, and nobody else's.

    A DRAFT IS THE ONE PLACE THIS SCHEMA HOLDS BYTES (RULING Q1's "unsaved
    drafts"), so listing it is reading a document that has not been written
    back yet. The first cut of this route authenticated and then filtered by
    caller-supplied ids alone, which let any signed-in principal read every
    draft body in the install (Copilot review of openDox-code#25, critical, and
    it was right). The filter is now the PRINCIPAL'S OWN SESSIONS: a draft
    belongs to the sitting that is typing it, and that sitting belongs to one
    user.
    """
    own = [session.id for session in store.list_sessions(
        user_id=principal.id, limit=identity.MAX_PAGE_SIZE)]
    if session_id is not None:
        if session_id not in own:
            raise HTTPException(
                status_code=403,
                detail={"code": "authz.not_your_session",
                        "message": "a draft is read by the user whose session "
                                   "is typing it"})
        own = [session_id]
    # THE OWNERSHIP FILTER IS IN THE QUERY, not applied to a page the query
    # already cut. Filtering after the LIMIT returned an empty page whenever
    # the global page happened to hold nobody else's drafts, and `after`
    # pagination could not walk past it — a correct-looking empty answer to a
    # principal who has drafts (Copilot review of openDox-code#25).
    found = store.list_drafts(session_ids=own, project_id=project_id,
                              limit=limit, after=after)
    return [_draft_json(d) for d in found]


@drafts.put("", status_code=200)
def put_draft(body: DraftPut, store: StoreDep,
              principal: PrincipalDep) -> dict[str, Any]:
    """Save UNSAVED text. This writes no document and reaches no repository.

    RULING Q1 puts unsaved drafts in the database by name. Writing one back is
    the apply lane's act, through the corpus adapter's `write_back` — never a
    side effect of saving a draft.
    """
    _require_role(store, user=principal, project_id=body.project_id,
                  allowed=("owner", "member"))
    _require_own_open_session(store, user=principal, session_id=body.session_id,
                              project_id=body.project_id)
    return _draft_json(store.put_draft(
        session_id=body.session_id, project_id=body.project_id,
        document_key=body.document_key, body=body.body,
        basis_revision=body.basis_revision))


@drafts.delete("/{draft_id}", status_code=204)
def discard_draft(draft_id: str, store: StoreDep,
                  principal: PrincipalDep) -> None:
    draft = _found(lambda: store.get_draft(draft_id))
    _require_role(store, user=principal, project_id=draft.project_id,
                  allowed=("owner", "member"))
    _require_own_open_session(store, user=principal, session_id=draft.session_id,
                              project_id=draft.project_id, require_open=False)
    store.delete_draft(draft_id)


# ---------------------------------------------------------------------------
# serialization — explicit, never a dataclass dumped wholesale
# ---------------------------------------------------------------------------


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def _user_json(user: identity.User) -> dict[str, Any]:
    return {"id": user.id, "issuer": user.issuer, "subject": user.subject,
            "email": user.email, "display_name": user.display_name,
            "created_at": _iso(user.created_at),
            "last_seen_at": _iso(user.last_seen_at)}


def _membership_json(m: identity.Membership) -> dict[str, Any]:
    return {"id": m.id, "user_id": m.user_id, "project_id": m.project_id,
            "role": m.role, "created_at": _iso(m.created_at)}


def _project_json(p: identity.Project) -> dict[str, Any]:
    return {"id": p.id, "slug": p.slug, "title": p.title,
            "created_by": p.created_by, "created_at": _iso(p.created_at)}


def _repository_json(r: identity.ProjectRepository) -> dict[str, Any]:
    return {"id": r.id, "project_id": r.project_id, "adapter": r.adapter,
            "location": r.location, "remote_url": r.remote_url,
            "created_at": _iso(r.created_at)}


def _session_json(s: identity.Session) -> dict[str, Any]:
    return {"id": s.id, "user_id": s.user_id, "project_id": s.project_id,
            "started_at": _iso(s.started_at),
            "last_seen_at": _iso(s.last_seen_at),
            "ended_at": _iso(s.ended_at)}


def _draft_json(d: identity.Draft) -> dict[str, Any]:
    return {"id": d.id, "session_id": d.session_id, "project_id": d.project_id,
            "document_key": d.document_key, "body": d.body,
            "basis_revision": d.basis_revision, "updated_at": _iso(d.updated_at)}


def _found(call: Any) -> Any:
    try:
        return call()
    except identity.NotFoundError as exc:
        raise HTTPException(status_code=404,
                            detail={"code": "coordination.not_found",
                                    "message": str(exc)}) from exc


def _conflict(call: Any) -> Any:
    try:
        return call()
    except identity.ConflictError as exc:
        raise HTTPException(status_code=409,
                            detail={"code": "coordination.conflict",
                                    "message": str(exc)}) from exc


# ---------------------------------------------------------------------------
# the application
# ---------------------------------------------------------------------------


def build_v1_router() -> APIRouter:
    """The `/api/v1` surface, routers mounted in `COLLECTIONS` order."""
    api = APIRouter(prefix=API_V1)
    api.include_router(users)
    api.include_router(memberships)
    api.include_router(projects)
    api.include_router(project_repositories)
    api.include_router(sessions)
    api.include_router(drafts)
    return api


def create_app(*, settings: RuntimeSettings | None = None,
               database: Any = None, verifier: Any = None) -> FastAPI:
    """Assemble one application.

    Everything is injectable and nothing is a module global: a test hands in a
    `Database` on a throwaway schema and a verifier over a file key set, and
    the deployed process hands in neither and gets the environment's.
    """
    resolved = settings or load_settings()

    if database is None:
        from opendox.runtime.db import Database  # deferred: see __init__'s contract

        database = Database(resolved.database_url)
    if verifier is None:
        verifier = oidc.build_verifier(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.context.database.open()
        try:
            yield
        finally:
            app.state.context.database.close()

    # THE SCHEMA VIEWERS ARE OFF UNLESS THE INSTALL SAYS OTHERWISE. FastAPI
    # publishes `/docs`, `/redoc` and `/openapi.json` to an unauthenticated
    # caller by default; this runtime's contract is that the only public routes
    # are the two probes, so the default here is `None` for all three and
    # `OPENDOX_PUBLISH_OPENAPI=true` is the deliberate act that turns them on
    # (a development install, or one behind an authenticating proxy).
    publish = resolved.publish_openapi
    app = FastAPI(title="openDox runtime",
                  summary="identity and coordination (RULING Q1); "
                          "documents live in repositories",
                  openapi_url="/openapi.json" if publish else None,
                  docs_url="/docs" if publish else None,
                  redoc_url="/redoc" if publish else None,
                  lifespan=lifespan)
    app.state.context = AppContext(settings=resolved, database=database,
                                   verifier=verifier)

    @app.get("/livez")
    def livez() -> dict[str, str]:
        """Liveness, and deliberately nothing else.

        Answers before any dependency is reachable, so a broker outage or an
        unmigrated database is reported by `/readyz` and never mistaken for a
        dead process by an orchestrator that would then restart it.
        """
        return {"status": "live"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        """Readiness: the database answers, the SCHEMA IS APPLIED, and the
        broker's keys resolve.

        UNAUTHENTICATED, like `/livez`, and for the reason the module docstring
        gives: a probe that needed a token could never report that the broker
        is unreachable. It returns dependency names and verdicts — no row, no
        id, no document.

        THE MIGRATION CHECK IS NOT DECORATION. `select 1` succeeds against a
        fresh Postgres with no coordination tables at all, so readiness without
        it turns a not-yet-migrated install READY and sends it traffic that
        fails on missing relations (Copilot review of openDox-code#25). A
        pending migration is `not-ready`, named, and the run that fixes it is
        `opendox-runtime migrate`.
        """
        checks: dict[str, str] = {}
        ok = True
        try:
            with app.state.context.database.connection() as conn:
                conn.execute("select 1")
            checks["database"] = "ok"
        # reported, never raised at a probe
        except Exception as exc:  # noqa: BLE001
            checks["database"] = f"unavailable: {type(exc).__name__}"
            ok = False
        if checks["database"] == "ok":
            try:
                runner = migrations.MigrationRunner(
                    app.state.context.database,
                    migrations_dir=app.state.context.settings.migrations_dir)
                pending = [m.version for m in runner.plan()]
                drifted = runner.drift()
                if pending:
                    checks["schema"] = (
                        "pending: " + ",".join(pending)
                        + " — run `opendox-runtime migrate`")
                    ok = False
                elif drifted:
                    # NOTHING PENDING IS NOT THE SAME AS MATCHING THIS TREE: a
                    # migration whose file changed, or vanished, is invisible
                    # to `plan()` and is REFUSED by `apply()`. Readiness that
                    # ignored it called an image the runner would not migrate
                    # healthy (Copilot review of openDox-code#25).
                    checks["schema"] = "drifted: " + ",".join(drifted)
                    ok = False
                else:
                    checks["schema"] = "applied"
            # reported, never raised at a probe
            except Exception as exc:  # noqa: BLE001
                checks["schema"] = f"unreadable: {type(exc).__name__}"
                ok = False
        try:
            app.state.context.verifier.probe_keys()
            checks["broker_keys"] = "ok"
        # same
        except Exception as exc:  # noqa: BLE001
            checks["broker_keys"] = f"unavailable: {type(exc).__name__}"
            ok = False
        return JSONResponse(status_code=200 if ok else 503,
                            content={"status": "ready" if ok else "not-ready",
                                     "checks": checks})

    app.include_router(build_v1_router())
    return app
