"""The six collections, exercised end to end against a real Postgres.

An in-process client over the real application, the real `TokenVerifier`
(local key set) and the real migrated schema — so what is measured here is what
a deployed runtime does, not what a stub agrees to.

DB-BACKED — runs in the `runtime` CI job; skipped, with the reason printed,
where no `OPENDOX_TEST_DATABASE_URL` is reachable.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pathlib import Path

from opendox.runtime import COLLECTIONS
from opendox.runtime.config import PREFIX, load_settings
from tests_runtime.conftest import TEST_AUDIENCE, TEST_ISSUER


@pytest.fixture
def client(database, postgres_dsn: str, verifier) -> Iterator[object]:
    """A `TestClient` over the real app, on this test's own schema.

    The application is given its OWN `Database` on the same schema rather than
    the fixture's: the app's lifespan opens and closes the pool it is handed,
    and sharing one with the fixture would have the teardown closing a pool the
    app had already closed.
    """
    fastapi_testclient = pytest.importorskip(
        "fastapi.testclient",
        reason="the `runtime` extra is not installed: pip install -e '.[runtime,test]'")
    from opendox.runtime.app import create_app
    from opendox.runtime.db import Database

    settings = load_settings({
        PREFIX + "DATABASE_URL": postgres_dsn,
        PREFIX + "OIDC_ISSUER": TEST_ISSUER,
        PREFIX + "OIDC_AUDIENCE": TEST_AUDIENCE,
    })
    app = create_app(settings=settings,
                     database=Database(postgres_dsn, schema=database.schema),
                     verifier=verifier)
    with fastapi_testclient.TestClient(app) as test_client:
        yield test_client


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# -- the boundary ------------------------------------------------------------


def test_livez_answers_without_a_token(client) -> None:
    """The ONLY unauthenticated route, and it answers before any dependency."""
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_readyz_reports_the_database_and_the_broker_by_name(client) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["broker_keys"] == "ok"


@pytest.mark.parametrize("collection", list(COLLECTIONS))
def test_every_collection_refuses_an_unauthenticated_request(
        client, collection: str) -> None:
    """There is no loopback exemption — design § D5's inversion, as a 401.

    "authorization stops being a property of the request's origin". An
    in-process client IS the loopback case, and it is refused like any other.
    """
    response = client.get(f"/api/v1/{collection}")
    assert response.status_code == 401, collection
    assert response.json()["detail"]["code"] == "auth.missing_bearer"


def test_a_token_from_another_issuer_is_refused_by_the_api(
        client, mint_token) -> None:
    response = client.get("/api/v1/projects",
                          headers=_auth(mint_token(issuer="https://elsewhere")))
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "auth.invalid_issuer"


# -- identity ----------------------------------------------------------------


def test_first_request_creates_the_account_and_users_me_returns_it(
        client, mint_token) -> None:
    token = mint_token(subject="student-3", email="s3@example.test",
                       name="Student Three")
    response = client.get("/api/v1/users/me", headers=_auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["issuer"] == TEST_ISSUER
    assert body["subject"] == "student-3"
    assert body["email"] == "s3@example.test"
    assert body["display_name"] == "Student Three"
    assert "password" not in body
    assert "token" not in body

    again = client.get("/api/v1/users/me", headers=_auth(token)).json()
    assert again["id"] == body["id"], "a second request minted a second account"


# -- projects and memberships ------------------------------------------------


def test_creating_a_project_makes_its_creator_the_owner(client, mint_token) -> None:
    token = mint_token(subject="owner-1")
    created = client.post("/api/v1/projects",
                          json={"slug": "first-project", "title": "First"},
                          headers=_auth(token))
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["slug"] == "first-project"

    me = client.get("/api/v1/users/me", headers=_auth(token)).json()
    memberships = client.get(
        f"/api/v1/memberships?project_id={project['id']}",
        headers=_auth(token)).json()
    assert [(m["user_id"], m["role"]) for m in memberships] == [(me["id"], "owner")]


def test_a_project_is_created_without_a_repository(client, mint_token) -> None:
    """§ 3.6 makes repository creation a FIRST-CLASS ACT with its own verb.

    So a project with no repository is a visible state rather than a
    half-finished write — this test is the shape § 3.6's act then fills.
    """
    token = mint_token(subject="owner-2")
    project = client.post("/api/v1/projects",
                          json={"slug": "no-repo-yet", "title": "No repo"},
                          headers=_auth(token)).json()
    response = client.get(f"/api/v1/project-repositories/{project['id']}",
                          headers=_auth(token))
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "coordination.not_found"


def test_a_duplicate_slug_is_a_conflict_and_not_a_second_project(
        client, mint_token) -> None:
    token = mint_token(subject="owner-3")
    body = {"slug": "taken", "title": "Taken"}
    assert client.post("/api/v1/projects", json=body,
                       headers=_auth(token)).status_code == 201
    clash = client.post("/api/v1/projects", json=body, headers=_auth(token))
    assert clash.status_code == 409
    assert clash.json()["detail"]["code"] == "coordination.conflict"


def test_only_an_owner_may_add_a_membership(client, mint_token) -> None:
    """Authorization is asked about the ROW, and answered by `memberships.role`."""
    owner = mint_token(subject="owner-4")
    stranger = mint_token(subject="stranger-1")
    project = client.post("/api/v1/projects",
                          json={"slug": "guarded", "title": "Guarded"},
                          headers=_auth(owner)).json()
    stranger_me = client.get("/api/v1/users/me", headers=_auth(stranger)).json()

    refused = client.post("/api/v1/memberships",
                          json={"user_id": stranger_me["id"],
                                "project_id": project["id"], "role": "member"},
                          headers=_auth(stranger))
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "authz.not_a_member"

    allowed = client.post("/api/v1/memberships",
                          json={"user_id": stranger_me["id"],
                                "project_id": project["id"], "role": "member"},
                          headers=_auth(owner))
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["role"] == "member"


def test_a_role_outside_the_closed_vocabulary_is_refused(
        client, mint_token) -> None:
    owner = mint_token(subject="owner-5")
    project = client.post("/api/v1/projects",
                          json={"slug": "roles", "title": "Roles"},
                          headers=_auth(owner)).json()
    me = client.get("/api/v1/users/me", headers=_auth(owner)).json()
    response = client.post("/api/v1/memberships",
                           json={"user_id": me["id"],
                                 "project_id": project["id"],
                                 "role": "administrator"},
                           headers=_auth(owner))
    assert response.status_code == 409
    assert "administrator" in response.json()["detail"]["message"]


# -- sessions and drafts -----------------------------------------------------


def test_a_session_opens_closes_and_belongs_to_the_user_who_opened_it(
        client, mint_token) -> None:
    owner = mint_token(subject="owner-6")
    other = mint_token(subject="owner-7")
    project = client.post("/api/v1/projects",
                          json={"slug": "sessions", "title": "Sessions"},
                          headers=_auth(owner)).json()
    session = client.post("/api/v1/sessions",
                          json={"project_id": project["id"]},
                          headers=_auth(owner))
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]
    assert session.json()["ended_at"] is None

    theirs = client.delete(f"/api/v1/sessions/{session_id}", headers=_auth(other))
    assert theirs.status_code == 403
    assert theirs.json()["detail"]["code"] == "authz.not_your_session"

    closed = client.delete(f"/api/v1/sessions/{session_id}", headers=_auth(owner))
    assert closed.status_code == 200
    assert closed.json()["ended_at"] is not None


def test_a_draft_is_saved_replaced_and_discarded_and_reaches_no_repository(
        client, mint_token) -> None:
    """RULING Q1 puts UNSAVED drafts in the database; writing back is the
    apply lane's act and never a side effect of saving one."""
    owner = mint_token(subject="owner-8")
    project = client.post("/api/v1/projects",
                          json={"slug": "drafts", "title": "Drafts"},
                          headers=_auth(owner)).json()
    session = client.post("/api/v1/sessions",
                          json={"project_id": project["id"]},
                          headers=_auth(owner)).json()

    body = {"session_id": session["id"], "project_id": project["id"],
            "document_key": "ideation/brainstorm/first.md",
            "body": "# first\n", "basis_revision": "abc123"}
    saved = client.put("/api/v1/drafts", json=body, headers=_auth(owner))
    assert saved.status_code == 200, saved.text
    assert saved.json()["body"] == "# first\n"

    body["body"] = "# first, edited\n"
    replaced = client.put("/api/v1/drafts", json=body, headers=_auth(owner))
    assert replaced.json()["id"] == saved.json()["id"], (
        "a second save of the same document in the same session must REPLACE "
        "the draft, not accumulate one per keystroke")
    assert replaced.json()["body"] == "# first, edited\n"

    listed = client.get(f"/api/v1/drafts?session_id={session['id']}",
                        headers=_auth(owner)).json()
    assert [d["id"] for d in listed] == [saved.json()["id"]]

    discarded = client.delete(f"/api/v1/drafts/{saved.json()['id']}",
                              headers=_auth(owner))
    assert discarded.status_code == 204
    assert client.get(f"/api/v1/drafts?session_id={session['id']}",
                      headers=_auth(owner)).json() == []


def test_a_reader_may_not_save_a_draft(client, mint_token) -> None:
    owner = mint_token(subject="owner-9")
    reader = mint_token(subject="reader-1")
    project = client.post("/api/v1/projects",
                          json={"slug": "readonly", "title": "Read only"},
                          headers=_auth(owner)).json()
    reader_me = client.get("/api/v1/users/me", headers=_auth(reader)).json()
    client.post("/api/v1/memberships",
                json={"user_id": reader_me["id"], "project_id": project["id"],
                      "role": "reader"}, headers=_auth(owner))
    session = client.post("/api/v1/sessions",
                          json={"project_id": project["id"]},
                          headers=_auth(reader)).json()
    response = client.put("/api/v1/drafts",
                          json={"session_id": session["id"],
                                "project_id": project["id"],
                                "document_key": "x.md", "body": "no"},
                          headers=_auth(reader))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "authz.role_insufficient"


# -- the boundary, again, from the client's side -----------------------------


def test_the_api_serves_no_document_route_at_all(client, mint_token) -> None:
    """RULING Q1: specs, changes, ideation documents and contracts stay in git."""
    token = mint_token(subject="prober-1")
    for path in ("/api/v1/documents", "/api/v1/specs", "/api/v1/changes",
                 "/api/v1/ideation", "/api/v1/contracts"):
        assert client.get(path, headers=_auth(token)).status_code == 404, path


def test_a_list_query_is_always_bounded(client, mint_token) -> None:
    token = mint_token(subject="prober-2")
    over = client.get("/api/v1/projects?limit=100000", headers=_auth(token))
    assert over.status_code == 422, (
        "an unbounded page size must be refused by the declared query shape, "
        "not clamped silently")


# ---------------------------------------------------------------------------
# the review round's own assertions (Copilot review of openDox-code#25)
# ---------------------------------------------------------------------------


def _project_with(client, token: str, slug: str) -> dict:
    return client.post("/api/v1/projects", json={"slug": slug, "title": slug},
                       headers=_auth(token)).json()


def test_a_draft_is_not_readable_by_another_member_of_the_project(
        client, mint_token) -> None:
    """A DRAFT IS THE ONE PLACE THIS SCHEMA HOLDS BYTES, so listing one is
    reading unwritten text. The first cut filtered by caller-supplied ids after
    authenticating, which let any signed-in principal read every draft in the
    install."""
    owner = mint_token(subject="draft-owner")
    other = mint_token(subject="draft-other")
    project = _project_with(client, owner, "draft-privacy")
    other_me = client.get("/api/v1/users/me", headers=_auth(other)).json()
    client.post("/api/v1/memberships",
                json={"user_id": other_me["id"], "project_id": project["id"],
                      "role": "member"}, headers=_auth(owner))

    session = client.post("/api/v1/sessions", json={"project_id": project["id"]},
                          headers=_auth(owner)).json()
    saved = client.put("/api/v1/drafts",
                       json={"session_id": session["id"],
                             "project_id": project["id"],
                             "document_key": "secret.md",
                             "body": "not yours to read"},
                       headers=_auth(owner))
    assert saved.status_code == 200, saved.text

    # The other MEMBER sees nothing, and is refused the owner's session by name.
    assert client.get("/api/v1/drafts", headers=_auth(other)).json() == []
    refused = client.get(f"/api/v1/drafts?session_id={session['id']}",
                         headers=_auth(other))
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "authz.not_your_session"
    # And the owner still sees their own.
    mine = client.get("/api/v1/drafts", headers=_auth(owner)).json()
    assert [d["document_key"] for d in mine] == ["secret.md"]


def test_a_member_may_not_write_into_another_members_session(
        client, mint_token) -> None:
    """`drafts` is keyed by `(session_id, document_key)`, so naming another
    member's session id would OVERWRITE their unsaved text through the upsert —
    while being a legitimate member of the project the whole time."""
    owner = mint_token(subject="sess-owner")
    other = mint_token(subject="sess-other")
    project = _project_with(client, owner, "session-privacy")
    other_me = client.get("/api/v1/users/me", headers=_auth(other)).json()
    client.post("/api/v1/memberships",
                json={"user_id": other_me["id"], "project_id": project["id"],
                      "role": "member"}, headers=_auth(owner))
    session = client.post("/api/v1/sessions", json={"project_id": project["id"]},
                          headers=_auth(owner)).json()
    client.put("/api/v1/drafts",
               json={"session_id": session["id"], "project_id": project["id"],
                     "document_key": "x.md", "body": "mine"},
               headers=_auth(owner))

    clobber = client.put("/api/v1/drafts",
                         json={"session_id": session["id"],
                               "project_id": project["id"],
                               "document_key": "x.md", "body": "theirs"},
                         headers=_auth(other))
    assert clobber.status_code == 403
    assert clobber.json()["detail"]["code"] == "authz.not_your_session"
    still = client.get("/api/v1/drafts", headers=_auth(owner)).json()
    assert [d["body"] for d in still] == ["mine"]


def test_a_member_may_not_discard_another_members_draft(
        client, mint_token) -> None:
    owner = mint_token(subject="del-owner")
    other = mint_token(subject="del-other")
    project = _project_with(client, owner, "delete-privacy")
    other_me = client.get("/api/v1/users/me", headers=_auth(other)).json()
    client.post("/api/v1/memberships",
                json={"user_id": other_me["id"], "project_id": project["id"],
                      "role": "member"}, headers=_auth(owner))
    session = client.post("/api/v1/sessions", json={"project_id": project["id"]},
                          headers=_auth(owner)).json()
    draft = client.put("/api/v1/drafts",
                       json={"session_id": session["id"],
                             "project_id": project["id"],
                             "document_key": "y.md", "body": "mine"},
                       headers=_auth(owner)).json()
    refused = client.delete(f"/api/v1/drafts/{draft['id']}", headers=_auth(other))
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "authz.not_your_session"
    assert client.delete(f"/api/v1/drafts/{draft['id']}",
                         headers=_auth(owner)).status_code == 204


def test_a_session_open_on_another_project_cannot_hold_this_projects_draft(
        client, mint_token) -> None:
    owner = mint_token(subject="mismatch-owner")
    one = _project_with(client, owner, "mismatch-one")
    two = _project_with(client, owner, "mismatch-two")
    session = client.post("/api/v1/sessions", json={"project_id": one["id"]},
                          headers=_auth(owner)).json()
    response = client.put("/api/v1/drafts",
                          json={"session_id": session["id"],
                                "project_id": two["id"],
                                "document_key": "z.md", "body": "?"},
                          headers=_auth(owner))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "coordination.session_project_mismatch")


def test_a_closed_session_cannot_save_a_draft(client, mint_token) -> None:
    owner = mint_token(subject="closed-owner")
    project = _project_with(client, owner, "closed-session")
    session = client.post("/api/v1/sessions", json={"project_id": project["id"]},
                          headers=_auth(owner)).json()
    client.delete(f"/api/v1/sessions/{session['id']}", headers=_auth(owner))
    response = client.put("/api/v1/drafts",
                          json={"session_id": session["id"],
                                "project_id": project["id"],
                                "document_key": "w.md", "body": "?"},
                          headers=_auth(owner))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "coordination.session_closed"


def test_the_unauthenticated_surface_is_exactly_the_two_probes(
        client, mint_token) -> None:
    """Enumerated against the running app, not read off the docstring.

    FastAPI publishes `/docs`, `/redoc` and `/openapi.json` to anybody by
    default; the contract is that the public surface is the two orchestrator
    probes, and `OPENDOX_PUBLISH_OPENAPI` is what changes that deliberately.
    """
    public = []
    for route in client.app.routes:
        path = getattr(route, "path", None)
        if path is None or path.startswith("/api/"):
            continue
        response = client.get(path)
        if response.status_code != 401:
            public.append(path)
    assert sorted(public) == ["/livez", "/readyz"], public
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_the_schema_viewers_appear_only_when_the_install_says_so(
        database, postgres_dsn: str, verifier) -> None:
    from fastapi.testclient import TestClient

    from opendox.runtime.app import create_app
    from opendox.runtime.config import PREFIX, load_settings
    from opendox.runtime.db import Database
    from tests_runtime.conftest import TEST_AUDIENCE, TEST_ISSUER

    settings = load_settings({
        PREFIX + "DATABASE_URL": postgres_dsn,
        PREFIX + "OIDC_ISSUER": TEST_ISSUER,
        PREFIX + "OIDC_AUDIENCE": TEST_AUDIENCE,
        PREFIX + "PUBLISH_OPENAPI": "true",
    })
    app = create_app(settings=settings,
                     database=Database(postgres_dsn, schema=database.schema),
                     verifier=verifier)
    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200


def test_readiness_refuses_an_unmigrated_database_by_name(
        postgres_dsn: str, verifier) -> None:
    """`select 1` succeeds against a schema with no tables in it at all.

    Readiness without a migration check therefore turns a fresh install READY
    and sends it traffic that fails on missing relations.
    """
    import uuid

    from fastapi.testclient import TestClient

    from opendox.runtime.app import create_app
    from opendox.runtime.config import PREFIX, load_settings
    from opendox.runtime.db import Database
    from tests_runtime.conftest import TEST_AUDIENCE, TEST_ISSUER

    schema = "t_" + uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            conn.execute(f"create schema {schema}")
        try:
            settings = load_settings({
                PREFIX + "DATABASE_URL": postgres_dsn,
                PREFIX + "OIDC_ISSUER": TEST_ISSUER,
                PREFIX + "OIDC_AUDIENCE": TEST_AUDIENCE,
            })
            app = create_app(settings=settings,
                             database=Database(postgres_dsn, schema=schema),
                             verifier=verifier)
            with TestClient(app) as client:
                response = client.get("/readyz")
            assert response.status_code == 503, response.text
            body = response.json()
            assert body["status"] == "not-ready"
            assert body["checks"]["database"] == "ok"
            assert body["checks"]["schema"].startswith("pending: 0001,0002")
            assert "opendox-runtime migrate" in body["checks"]["schema"]
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")


def test_readiness_is_ready_once_the_schema_is_applied(client) -> None:
    body = client.get("/readyz").json()
    assert body["status"] == "ready"
    assert body["checks"]["schema"] == "applied"


def test_an_unauthenticated_request_opens_no_database_transaction(
        client, mint_token) -> None:
    """The cheapest refusal must not depend on the most expensive resource.

    `get_principal` depends on the store, and FastAPI resolves a dependency
    before it calls the function that asked for it — so an EAGER store took a
    pooled connection before anybody looked at `Authorization`, and a request
    with no token failed with a database error whenever Postgres was
    unreachable or the pool was exhausted.
    """
    from opendox.runtime.app import _LazyStore

    opened: list[int] = []
    original = _LazyStore._open

    def _counting_open(self):  # noqa: ANN001
        opened.append(1)
        return original(self)

    _LazyStore._open = _counting_open
    try:
        assert client.get("/api/v1/projects").status_code == 401
        assert opened == [], "an unauthenticated request checked out a connection"
        assert client.get("/api/v1/projects",
                          headers=_auth(mint_token(subject="lazy-1"))
                          ).status_code == 200
        assert opened, "an authenticated request never opened one"
    finally:
        _LazyStore._open = original


def test_a_membership_naming_an_unknown_row_is_a_404_and_not_a_500(
        client, mint_token) -> None:
    owner = mint_token(subject="fk-owner")
    project = _project_with(client, owner, "fk-project")
    me = client.get("/api/v1/users/me", headers=_auth(owner)).json()

    missing_user = client.post(
        "/api/v1/memberships",
        json={"user_id": "no-such-user", "project_id": project["id"],
              "role": "member"}, headers=_auth(owner))
    assert missing_user.status_code == 404, missing_user.text
    assert missing_user.json()["detail"]["code"] == "coordination.not_found"

    missing_project = client.post(
        "/api/v1/memberships",
        json={"user_id": me["id"], "project_id": "no-such-project",
              "role": "member"}, headers=_auth(owner))
    # No membership in that project, so authorization refuses before the row
    # lookup — which is the correct order and still not a 500.
    assert missing_project.status_code in (403, 404), missing_project.text


def test_draft_pagination_returns_the_principals_drafts_not_an_empty_page(
        client, mint_token) -> None:
    """The ownership filter used to be applied AFTER the LIMIT.

    A global page holding only other users' drafts therefore came back empty
    for a principal who has drafts, and `after` could not walk past it.
    """
    owner = mint_token(subject="page-owner")
    other = mint_token(subject="page-other")
    project = _project_with(client, owner, "pagination")
    other_me = client.get("/api/v1/users/me", headers=_auth(other)).json()
    client.post("/api/v1/memberships",
                json={"user_id": other_me["id"], "project_id": project["id"],
                      "role": "member"}, headers=_auth(owner))
    other_session = client.post("/api/v1/sessions",
                                json={"project_id": project["id"]},
                                headers=_auth(other)).json()
    mine_session = client.post("/api/v1/sessions",
                               json={"project_id": project["id"]},
                               headers=_auth(owner)).json()
    # Twelve of theirs and one of mine; with a page of ten, a post-filter would
    # very likely return nothing for me.
    for index in range(12):
        client.put("/api/v1/drafts",
                   json={"session_id": other_session["id"],
                         "project_id": project["id"],
                         "document_key": f"theirs-{index}.md", "body": "x"},
                   headers=_auth(other))
    client.put("/api/v1/drafts",
               json={"session_id": mine_session["id"],
                     "project_id": project["id"],
                     "document_key": "mine.md", "body": "y"},
               headers=_auth(owner))

    page = client.get("/api/v1/drafts?limit=10", headers=_auth(owner)).json()
    assert [d["document_key"] for d in page] == ["mine.md"], page


def test_readiness_refuses_a_database_whose_migration_file_has_changed(
        database, postgres_dsn: str, verifier, tmp_path) -> None:
    """Nothing pending is not the same as matching this tree."""
    import shutil

    from fastapi.testclient import TestClient

    from opendox.runtime.app import create_app
    from opendox.runtime.config import PREFIX, load_settings
    from opendox.runtime.db import Database
    from tests_runtime.conftest import TEST_AUDIENCE, TEST_ISSUER

    root = Path(__file__).resolve().parents[1] / "migrations"
    for name in ("0001_identity_and_coordination.sql",
                 "0002_migration_state.sql"):
        shutil.copyfile(root / name, tmp_path / name)
    edited = tmp_path / "0002_migration_state.sql"
    edited.write_text(edited.read_text(encoding="utf-8") + "\n-- edited\n",
                      encoding="utf-8")

    settings = load_settings({
        PREFIX + "DATABASE_URL": postgres_dsn,
        PREFIX + "OIDC_ISSUER": TEST_ISSUER,
        PREFIX + "OIDC_AUDIENCE": TEST_AUDIENCE,
        PREFIX + "MIGRATIONS_DIR": str(tmp_path),
    })
    app = create_app(settings=settings,
                     database=Database(postgres_dsn, schema=database.schema),
                     verifier=verifier)
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 503, response.text
    assert response.json()["checks"]["schema"] == "drifted: 0002:changed"
