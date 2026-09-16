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


# -- the read routes are scoped to the principal -----------------------------
#
# THE CONTRACT IN `app.py`'S DOCSTRING WAS TRUE OF THE WRITES AND FALSE OF THE
# READS: `GET /users`, `GET /memberships`, `GET /projects` and the
# project-repository reads authenticated and then returned the whole install,
# so any signed-in account could enumerate every user's issuer/subject/email
# and every project's repository `location` and `remote_url` (Copilot review of
# openDox-code#25 — a thread, and again as a suppressed comment naming the
# docstring). These are the assertions that keep the sentence and the handlers
# the same thing.


def _write_repository_row(database, *, project_id: str, location: str) -> None:
    """Commit a map row the way § 3.6's act will, so the API can read it."""
    from opendox.runtime.identity import CoordinationStore

    with database.transaction() as conn:
        CoordinationStore(conn).create_project_repository(
            project_id=project_id, adapter="local-git", location=location)


def test_a_stranger_enumerates_no_project_no_membership_and_no_repository(
        client, database, mint_token) -> None:
    owner = mint_token(subject="scope-owner")
    stranger = mint_token(subject="scope-stranger")
    project = client.post("/api/v1/projects",
                          json={"slug": "private-one", "title": "Private"},
                          headers=_auth(owner)).json()
    _write_repository_row(database, project_id=project["id"],
                          location="/var/lib/opendox/projects/private-one")

    # The owner sees its own project, its membership and its map row.
    assert [p["id"] for p in client.get("/api/v1/projects",
                                        headers=_auth(owner)).json()] == [project["id"]]
    assert client.get("/api/v1/memberships", headers=_auth(owner)).json() != []
    mine = client.get("/api/v1/project-repositories", headers=_auth(owner)).json()
    assert [r["project_id"] for r in mine] == [project["id"]]

    # The stranger is a signed-in principal with no membership anywhere.
    assert client.get("/api/v1/projects", headers=_auth(stranger)).json() == []
    assert client.get("/api/v1/memberships", headers=_auth(stranger)).json() == []
    assert client.get("/api/v1/project-repositories",
                      headers=_auth(stranger)).json() == []


def test_a_stranger_sees_only_itself_in_the_user_directory(
        client, mint_token) -> None:
    owner = mint_token(subject="dir-owner", email="owner@example.test")
    stranger = mint_token(subject="dir-stranger")
    owner_me = client.get("/api/v1/users/me", headers=_auth(owner)).json()
    stranger_me = client.get("/api/v1/users/me", headers=_auth(stranger)).json()

    listed = client.get("/api/v1/users", headers=_auth(stranger)).json()
    assert [u["id"] for u in listed] == [stranger_me["id"]]

    # And the owner's row is not reachable by id either — 404, not 403, so the
    # route is not an oracle for which user ids exist.
    refused = client.get(f"/api/v1/users/{owner_me['id']}",
                         headers=_auth(stranger))
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"]["code"] == "coordination.not_found"


def test_sharing_a_project_is_what_makes_two_users_visible_to_each_other(
        client, mint_token) -> None:
    """Visibility is a PROJECT RELATION and not a role."""
    owner = mint_token(subject="share-owner")
    other = mint_token(subject="share-other")
    project = client.post("/api/v1/projects",
                          json={"slug": "shared", "title": "Shared"},
                          headers=_auth(owner)).json()
    owner_me = client.get("/api/v1/users/me", headers=_auth(owner)).json()
    other_me = client.get("/api/v1/users/me", headers=_auth(other)).json()

    assert client.get(f"/api/v1/users/{owner_me['id']}",
                      headers=_auth(other)).status_code == 404

    client.post("/api/v1/memberships",
                json={"user_id": other_me["id"], "project_id": project["id"],
                      "role": "reader"}, headers=_auth(owner))

    assert client.get(f"/api/v1/users/{owner_me['id']}",
                      headers=_auth(other)).status_code == 200
    seen = {u["id"] for u in client.get("/api/v1/users",
                                        headers=_auth(other)).json()}
    assert seen == {owner_me["id"], other_me["id"]}
    # `reader` is enough to read the project itself and its map row.
    assert client.get(f"/api/v1/projects/{project['id']}",
                      headers=_auth(other)).status_code == 200


def test_a_non_member_is_refused_a_project_and_its_map_row_by_name(
        client, database, mint_token) -> None:
    owner = mint_token(subject="refuse-owner")
    stranger = mint_token(subject="refuse-stranger")
    project = client.post("/api/v1/projects",
                          json={"slug": "refused", "title": "Refused"},
                          headers=_auth(owner)).json()
    _write_repository_row(database, project_id=project["id"],
                          location="/var/lib/opendox/projects/refused")

    for path in (f"/api/v1/projects/{project['id']}",
                 f"/api/v1/project-repositories/{project['id']}"):
        response = client.get(path, headers=_auth(stranger))
        assert response.status_code == 403, (path, response.text)
        assert response.json()["detail"]["code"] == "authz.not_a_member"


def test_a_project_that_does_not_exist_answers_exactly_as_one_it_may_not_see(
        client, mint_token) -> None:
    """404-vs-403 must not become an existence oracle over the id space."""
    owner = mint_token(subject="oracle-owner")
    stranger = mint_token(subject="oracle-stranger")
    project = client.post("/api/v1/projects",
                          json={"slug": "oracle", "title": "Oracle"},
                          headers=_auth(owner)).json()
    real = client.get(f"/api/v1/projects/{project['id']}",
                      headers=_auth(stranger))
    invented = client.get("/api/v1/projects/p_does_not_exist",
                          headers=_auth(stranger))
    assert real.status_code == invented.status_code == 403
    assert (real.json()["detail"]["code"]
            == invented.json()["detail"]["code"] == "authz.not_a_member")


def test_a_second_membership_for_the_same_pair_is_a_conflict_not_a_role_change(
        client, mint_token) -> None:
    """`POST /memberships` is declared a create and now behaves like one.

    The insert carried `on conflict … do update set role = excluded.role`, so a
    repeated POST silently REWROTE an existing member's role and still answered
    201, while the route advertised 409 for a duplicate (Copilot review of
    openDox-code#25, suppressed comment). A role change is a different act and
    does not get to arrive disguised as a join.
    """
    owner = mint_token(subject="upsert-owner")
    other = mint_token(subject="upsert-other")
    project = client.post("/api/v1/projects",
                          json={"slug": "upsert", "title": "Upsert"},
                          headers=_auth(owner)).json()
    other_me = client.get("/api/v1/users/me", headers=_auth(other)).json()
    body = {"user_id": other_me["id"], "project_id": project["id"],
            "role": "reader"}
    assert client.post("/api/v1/memberships", json=body,
                       headers=_auth(owner)).status_code == 201

    promoted = client.post("/api/v1/memberships",
                           json={**body, "role": "owner"}, headers=_auth(owner))
    assert promoted.status_code == 409, promoted.text
    assert promoted.json()["detail"]["code"] == "coordination.conflict"

    listed = client.get(f"/api/v1/memberships?project_id={project['id']}"
                        f"&user_id={other_me['id']}",
                        headers=_auth(owner)).json()
    assert [m["role"] for m in listed] == ["reader"], (
        "the duplicate POST changed the role it was refused for")


def test_a_users_own_drafts_survive_more_sessions_than_one_page_holds(
        client, database, mint_token) -> None:
    """The ownership filter is a JOIN, not a page of session ids.

    `list_drafts` collected the principal's sessions with one capped query and
    passed the ids down, so a user with more than `MAX_PAGE_SIZE` sittings lost
    the drafts of every later one and was refused its OWN session by name
    (Copilot review of openDox-code#25, suppressed comment). The schema caps
    sessions per user at nothing, so the cap had to leave the authorization
    path entirely.
    """
    from opendox.runtime import identity as identity_module

    owner = mint_token(subject="paging-owner")
    project = client.post("/api/v1/projects",
                          json={"slug": "paging", "title": "Paging"},
                          headers=_auth(owner)).json()
    me = client.get("/api/v1/users/me", headers=_auth(owner)).json()

    # One more sitting than a single page of the old ownership lookup held.
    extra = identity_module.MAX_PAGE_SIZE + 1
    with database.transaction() as conn:
        store = identity_module.CoordinationStore(conn)
        for _ in range(extra):
            store.open_session(user_id=me["id"], project_id=project["id"])
    newest = client.post("/api/v1/sessions", json={"project_id": project["id"]},
                         headers=_auth(owner)).json()

    saved = client.put("/api/v1/drafts",
                       json={"session_id": newest["id"],
                             "project_id": project["id"],
                             "document_key": "late.md",
                             "body": "typed in the 502nd sitting"},
                       headers=_auth(owner))
    assert saved.status_code == 200, saved.text

    listed = client.get("/api/v1/drafts", headers=_auth(owner)).json()
    assert [d["id"] for d in listed] == [saved.json()["id"]]
    by_session = client.get(f"/api/v1/drafts?session_id={newest['id']}",
                            headers=_auth(owner))
    assert by_session.status_code == 200, by_session.text
    assert [d["id"] for d in by_session.json()] == [saved.json()["id"]]


def test_a_hidden_user_and_a_missing_one_answer_byte_for_byte_the_same(
        client, mint_token) -> None:
    """The status matched; the BODY did not, which is the same oracle.

    Reading the row first meant a missing user came back as `_found`'s
    `no user with id=…` and a hidden one as a message naming visibility — 404
    twice, distinguishable at a glance, so the id space was still walkable
    (Copilot review of openDox-code#25, round 5).
    """
    owner = mint_token(subject="oracle2-owner")
    stranger = mint_token(subject="oracle2-stranger")
    owner_me = client.get("/api/v1/users/me", headers=_auth(owner)).json()

    hidden = client.get(f"/api/v1/users/{owner_me['id']}",
                        headers=_auth(stranger))
    missing = client.get("/api/v1/users/u_does_not_exist",
                         headers=_auth(stranger))
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json(), (
        "the two 404s differ, so the route still answers which ids exist")
    # And the body names no id at all — naming one puts the probe in the answer.
    assert owner_me["id"] not in hidden.text
