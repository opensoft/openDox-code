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

  * `/livez` is the ONLY unauthenticated route, and it answers before any
    dependency is reachable — the Hermes install's own shape, so a liveness
    probe never reports a broker outage as a dead process.
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

from opendox.runtime import API_V1, identity, oidc
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


def get_store(request: Request) -> Iterator[identity.CoordinationStore]:
    """One transaction per request, and one store over it.

    A request that writes three rows writes them atomically because they share
    this connection; a request that only reads still gets one consistent
    snapshot.
    """
    context = _context(request)
    with context.database.transaction() as conn:
        yield identity.CoordinationStore(conn)


def get_principal(
    request: Request,
    store: Annotated[identity.CoordinationStore, Depends(get_store)],
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


StoreDep = Annotated[identity.CoordinationStore, Depends(get_store)]
PrincipalDep = Annotated[identity.User, Depends(get_principal)]
LimitQuery = Annotated[int | None, Query(ge=1, le=identity.MAX_PAGE_SIZE)]


def _require_role(store: identity.CoordinationStore, *, user: identity.User,
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

users = APIRouter(prefix="/users", tags=["users"])
memberships = APIRouter(prefix="/memberships", tags=["memberships"])
projects = APIRouter(prefix="/projects", tags=["projects"])
project_repositories = APIRouter(prefix="/project-repositories",
                                 tags=["project-repositories"])
sessions = APIRouter(prefix="/sessions", tags=["sessions"])
drafts = APIRouter(prefix="/drafts", tags=["drafts"])


@users.get("/me")
def read_me(principal: PrincipalDep) -> dict[str, Any]:
    """The row this token resolved to — the whole of the inversion, visible."""
    return _user_json(principal)


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
    del principal
    return [_draft_json(d) for d in store.list_drafts(
        session_id=session_id, project_id=project_id, limit=limit, after=after)]


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

    app = FastAPI(title="openDox runtime",
                  summary="identity and coordination (RULING Q1); "
                          "documents live in repositories",
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
        """Readiness: the database answers and the broker's keys resolve."""
        checks: dict[str, str] = {}
        ok = True
        try:
            with app.state.context.database.connection() as conn:
                conn.execute("select 1")
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001 - reported, never raised at a probe
            checks["database"] = f"unavailable: {type(exc).__name__}"
            ok = False
        try:
            app.state.context.verifier.probe_keys()
            checks["broker_keys"] = "ok"
        except Exception as exc:  # noqa: BLE001 - same
            checks["broker_keys"] = f"unavailable: {type(exc).__name__}"
            ok = False
        return JSONResponse(status_code=200 if ok else 503,
                            content={"status": "ready" if ok else "not-ready",
                                     "checks": checks})

    app.include_router(build_v1_router())
    return app
