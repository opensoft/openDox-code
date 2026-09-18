"""The six collections, exercised end to end against a real Postgres.

An in-process client over the real application, the real `TokenVerifier`
(local key set) and the real migrated schema — so what is measured here is what
a deployed runtime does, not what a stub agrees to.

DB-BACKED — runs in the `runtime` CI job; skipped, with the reason printed,
where no `OPENDOX_TEST_DATABASE_URL` is reachable.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from opendox.runtime import COLLECTIONS
from tests_runtime.conftest import TEST_ISSUER


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
            assert "opendox-runtime runtime migrate" in body["checks"]["schema"]
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


# -- Copilot's sixth round on #25 --------------------------------------------


def test_readiness_refuses_a_migrations_directory_without_the_pinned_0001(
        database, postgres_dsn: str, verifier, tmp_path) -> None:
    """An EMPTY directory made `plan()` and `drift()` both empty.

    `discover()` returns `[]` for a directory that exists and holds no
    migration, so on a fresh database readiness reported `schema: applied` and
    admitted traffic to an install with no coordination schema at all — an
    image that lost `0001`, or a wrong `OPENDOX_MIGRATIONS_DIR`, looked
    healthier than a pending one (Copilot review of openDox-code#25, round 6).
    The pinned canonical file is verified BEFORE the plan, which is the same
    gate `apply()` runs first.
    """
    from fastapi.testclient import TestClient

    from opendox.runtime.app import create_app
    from opendox.runtime.config import PREFIX, load_settings
    from opendox.runtime.db import Database
    from tests_runtime.conftest import TEST_AUDIENCE, TEST_ISSUER

    empty = tmp_path / "no-migrations-here"
    empty.mkdir()
    settings = load_settings({
        PREFIX + "DATABASE_URL": postgres_dsn,
        PREFIX + "OIDC_ISSUER": TEST_ISSUER,
        PREFIX + "OIDC_AUDIENCE": TEST_AUDIENCE,
        PREFIX + "MIGRATIONS_DIR": str(empty),
    })
    app = create_app(settings=settings,
                     database=Database(postgres_dsn, schema=database.schema),
                     verifier=verifier)
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 503, response.text
    schema = response.json()["checks"]["schema"]
    assert schema.startswith("unreadable: MigrationError"), schema


def test_a_request_body_over_the_cap_is_refused_before_it_is_parsed(
        client, mint_token) -> None:
    """`DraftPut.body` had no bound at all.

    An authenticated caller could hand FastAPI an arbitrarily large JSON
    document, have it parsed into memory and written into an unbounded `text`
    column — process memory and database storage spent by one request, on a
    surface where every other HTTP entry point in this repository caps its
    bytes (Copilot review of openDox-code#25, round 6).
    """
    from opendox.runtime.app import MAX_REQUEST_BODY_BYTES

    token = mint_token(subject="bulk-writer")
    project = client.post("/api/v1/projects",
                          json={"slug": "capped", "title": "Capped"},
                          headers=_auth(token)).json()
    session = client.post("/api/v1/sessions",
                          json={"project_id": project["id"]},
                          headers=_auth(token)).json()

    oversized = "x" * (MAX_REQUEST_BODY_BYTES + 1)
    refused = client.put("/api/v1/drafts",
                         json={"session_id": session["id"],
                               "project_id": project["id"],
                               "document_key": "big.md",
                               "body": oversized},
                         headers=_auth(token))
    assert refused.status_code == 413, refused.status_code
    assert refused.json()["detail"]["code"] == "request.too_large"

    # And the cap is the only thing refusing it: the same request one document
    # smaller is accepted and stored.
    accepted = client.put("/api/v1/drafts",
                          json={"session_id": session["id"],
                                "project_id": project["id"],
                                "document_key": "big.md",
                                "body": "x" * 1024},
                          headers=_auth(token))
    assert accepted.status_code in (200, 201), accepted.text


def test_a_referenced_row_deleted_under_a_write_is_404_and_not_500(
        client, mint_token, database,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The one race a pre-check cannot close, driven deliberately.

    The route resolves both referenced rows first, so an id that is simply
    wrong is already a 404. What it cannot close is the row going away BETWEEN
    that read and the insert: `identity._conflict_if_duplicate` translates the
    foreign-key violation into `NotFoundError`, and the write was wrapped in
    `_conflict` alone — which catches `ConflictError` and nothing else — so
    that raced request escaped as a 500 instead of the documented 404 (Copilot
    review of openDox-code#25, round 6, suppressed). `_conflict` translates
    both now.

    The race is made deterministic by letting the pre-check see a row the
    insert will not find: that is the only difference between this test and
    the ordinary wrong-id case, and it is exactly the window.
    """
    import dataclasses

    from opendox.runtime import identity

    owner = mint_token(subject="fk-race-owner")
    other = mint_token(subject="fk-race-other")
    project = client.post("/api/v1/projects",
                          json={"slug": "fk-race", "title": "FK race"},
                          headers=_auth(owner)).json()
    stranger = client.get("/api/v1/users/me", headers=_auth(other)).json()
    with database.transaction() as conn:
        conn.execute("delete from users where id = %s", (stranger["id"],))

    real_get_user = identity.CoordinationStore.get_user

    def _stale_read(self, user_id: str):
        if user_id == stranger["id"]:
            # What the pre-check saw a moment before the delete.
            return identity.User(
                *(stranger.get(field.name) for field in
                  dataclasses.fields(identity.User)))
        return real_get_user(self, user_id)

    monkeypatch.setattr(identity.CoordinationStore, "get_user", _stale_read)

    refused = client.post("/api/v1/memberships",
                          json={"user_id": stranger["id"],
                                "project_id": project["id"],
                                "role": "reader"},
                          headers=_auth(owner))
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"]["code"] == "coordination.not_found"


# -- Copilot's tenth round on #25 --------------------------------------------


def test_a_session_that_ends_under_the_write_takes_no_draft(
        client, database, mint_token, monkeypatch: pytest.MonkeyPatch) -> None:
    """`require_open=True` is a promise about the WRITE, not about a read.

    The route's check and the upsert were two statements, so a
    `DELETE /sessions/{id}` committing between them wrote a draft into a
    sitting that had ended — the one thing that check exists to prevent
    (Copilot review of openDox-code#25, round 10, suppressed). The predicate
    now travels in the insert. The race is made deterministic the way this file
    already drives one: the pre-check is shown the row as it was a moment
    before the close.
    """
    import dataclasses

    from opendox.runtime import identity

    token = mint_token(subject="race-close")
    project = _project_with(client, token, "close-race")
    session = client.post("/api/v1/sessions", json={"project_id": project["id"]},
                          headers=_auth(token)).json()
    client.delete(f"/api/v1/sessions/{session['id']}", headers=_auth(token))

    real_get_session = identity.CoordinationStore.get_session

    def _still_open(self, session_id: str):
        row = real_get_session(self, session_id)
        if session_id == session["id"]:
            # What the pre-check saw a moment before the close committed.
            return dataclasses.replace(row, ended_at=None)
        return row

    monkeypatch.setattr(identity.CoordinationStore, "get_session", _still_open)

    refused = client.put("/api/v1/drafts",
                         json={"session_id": session["id"],
                               "project_id": project["id"],
                               "document_key": "raced.md", "body": "?"},
                         headers=_auth(token))
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"]["code"] == "coordination.not_found"
    with database.connection() as conn:
        rows = conn.execute("select count(*) from drafts where session_id = %s",
                            (session["id"],)).fetchone()
    assert rows[0] == 0, "a draft was written into a session that had ended"


def test_a_draft_answers_the_same_to_a_stranger_whether_or_not_it_exists(
        client, mint_token) -> None:
    """The existence oracle, one step out from the one round 7 closed.

    Round 7 normalized "unknown draft" and "another member's draft" for a
    member of the project. A caller who is NOT a member still got
    `authz.not_a_member` for a draft that exists and `authz.not_your_session`
    for an id that does not, so the id space was walkable by anyone with an
    account (Copilot review of openDox-code#25, round 10, suppressed).
    """
    owner = mint_token(subject="oracle-owner")
    stranger = mint_token(subject="oracle-stranger")
    project = _project_with(client, owner, "oracle-project")
    session = client.post("/api/v1/sessions", json={"project_id": project["id"]},
                          headers=_auth(owner)).json()
    draft = client.put("/api/v1/drafts",
                       json={"session_id": session["id"],
                             "project_id": project["id"],
                             "document_key": "secret.md", "body": "mine"},
                       headers=_auth(owner)).json()

    real = client.delete(f"/api/v1/drafts/{draft['id']}",
                         headers=_auth(stranger))
    invented = client.delete("/api/v1/drafts/no-such-draft-id",
                             headers=_auth(stranger))
    assert real.status_code == invented.status_code == 403
    assert real.json() == invented.json(), (
        "a stranger can tell a real draft id from an invented one")
    # And the owner's own discard still works.
    assert client.delete(f"/api/v1/drafts/{draft['id']}",
                         headers=_auth(owner)).status_code == 204


def test_a_draft_deleted_under_the_discard_is_404_and_not_500(
        client, mint_token, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two concurrent discards by the owner, the second arriving late.

    The route read the row, authorized, and then called `delete_draft`
    directly, so `identity.NotFoundError` escaped as a 500 instead of the
    documented coordination 404 — the session-close path beside it was already
    wrapped in `_found` (Copilot review of openDox-code#25, round 10,
    suppressed).
    """
    import dataclasses

    from opendox.runtime import identity

    token = mint_token(subject="discard-race")
    project = _project_with(client, token, "discard-race")
    session = client.post("/api/v1/sessions", json={"project_id": project["id"]},
                          headers=_auth(token)).json()
    draft = client.put("/api/v1/drafts",
                       json={"session_id": session["id"],
                             "project_id": project["id"],
                             "document_key": "gone.md", "body": "x"},
                       headers=_auth(token)).json()
    assert client.delete(f"/api/v1/drafts/{draft['id']}",
                         headers=_auth(token)).status_code == 204

    stale = identity.Draft(
        id=draft["id"], session_id=session["id"], project_id=project["id"],
        document_key="gone.md", body="x", basis_revision=None,
        updated_at=None)
    monkeypatch.setattr(identity.CoordinationStore, "get_draft",
                        lambda self, draft_id: dataclasses.replace(stale))

    late = client.delete(f"/api/v1/drafts/{draft['id']}", headers=_auth(token))
    assert late.status_code == 404, late.text
    assert late.json()["detail"]["code"] == "coordination.not_found"


def test_a_project_deleted_under_an_open_session_is_404_and_not_500(
        client, database, mint_token, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other referencing write this API makes, and it was unwrapped.

    `POST /sessions` checks the caller's membership and then inserts; the
    project can go between the two, and the foreign-key violation escaped the
    route as a 500 rather than the documented 404. `identity.open_session` now
    goes through `_conflict_if_duplicate` like every other referencing write,
    and the route through `_conflict` (Copilot review of openDox-code#25, round
    10, suppressed).
    """
    from opendox.runtime import identity

    token = mint_token(subject="session-fk-race")
    project = _project_with(client, token, "session-fk-race")
    membership = client.get("/api/v1/memberships", headers=_auth(token)).json()[0]
    with database.transaction() as conn:
        conn.execute("delete from projects where id = %s", (project["id"],))

    stale = identity.Membership(
        id=membership["id"], user_id=membership["user_id"],
        project_id=project["id"], role="owner", created_at=None)
    monkeypatch.setattr(identity.CoordinationStore, "membership_for",
                        lambda self, *, user_id, project_id: stale)

    refused = client.post("/api/v1/sessions",
                          json={"project_id": project["id"]},
                          headers=_auth(token))
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"]["code"] == "coordination.not_found"


def test_the_store_translates_a_foreign_key_violation_on_a_session(
        store) -> None:
    """And the translation is the store's, measured against a real Postgres.

    `_conflict_if_duplicate` is the one place this module turns a SQLSTATE into
    its own error, and `open_session` was written outside it — so the API layer
    had nothing to translate and the raw driver error became a 500.
    """
    from opendox.runtime import identity

    user = store.upsert_user(issuer="https://broker.test/realms/opendox",
                             subject="fk-session-store")
    with pytest.raises(identity.NotFoundError):
        store.open_session(user_id=user.id, project_id="no-such-project")


def test_a_repository_refusal_reaching_the_api_is_redacted(
        client, mint_token, monkeypatch: pytest.MonkeyPatch) -> None:
    """The API returned `str(exc)` for a repository refusal, unredacted.

    Those messages were treated as secret-free by construction, and they are
    not: `repository_act.repository_location` refuses a project id it cannot
    use as a directory name and echoes it, and that id comes from the request
    path (Copilot review of openDox-code#26, round 10; the CLI's three handlers
    took the same fix). The route cannot be driven to THAT message today — an
    id with a `/` in it does not route here and the membership check answers
    first — so the refusal is raised where the act raises it, which is what the
    handler sees.
    """
    from opendox.runtime import repository_act

    token = mint_token(subject="redacted-refusal")
    project = _project_with(client, token, "redacted-refusal")

    def _refuse_with_a_dsn(*args: object, **kwargs: object):
        raise repository_act.RepositoryActRefused(
            "'postgresql://someone:hunter2@db.internal/opendox' is not a "
            "usable project id for a directory name")

    monkeypatch.setattr(repository_act, "create_repository", _refuse_with_a_dsn)
    refused = client.post(f"/api/v1/projects/{project['id']}/repository",
                          headers=_auth(token))
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "repository.refused"
    assert "hunter2" not in refused.text, refused.text
    assert "<redacted" in refused.text, refused.text

def test_a_chunked_body_over_the_cap_is_refused_as_it_arrives(
        client, database, mint_token) -> None:
    """The cap's OTHER half: a request that declares no `Content-Length`.

    The existing oversized case sends `json=…`, so it only ever exercises the
    declared-length fast path — the middleware's `counting_receive` branch, the
    one protection a streamed body has, had no test at all, and a regression
    there would leave the cap test green while parsing continued unbounded
    (Copilot review of openDox-code#25, round 11, suppressed). This request is
    chunked: httpx sends `Transfer-Encoding: chunked` for a generator body, so
    the ASGI app sees several `http.request` messages and no declared length.
    """
    from opendox.runtime.app import MAX_REQUEST_BODY_BYTES

    token = mint_token(subject="chunked-cap")
    project = _project_with(client, token, "chunked-cap")
    session = client.post("/api/v1/sessions", json={"project_id": project["id"]},
                          headers=_auth(token)).json()

    chunk = b"x" * 262_144
    chunks = MAX_REQUEST_BODY_BYTES // len(chunk) + 2      # over the cap

    def _stream():
        head = ('{"session_id": "' + session["id"] + '", "project_id": "'
                + project["id"] + '", "document_key": "streamed.md", '
                '"body": "').encode()
        yield head
        for _ in range(chunks):
            yield chunk
        yield b'"}'

    refused = client.put("/api/v1/drafts", content=_stream(),
                         headers={**_auth(token),
                                  "Content-Type": "application/json"})
    assert refused.status_code == 413, refused.text
    assert refused.json()["detail"]["code"] == "request.too_large"
    # AND NOTHING WAS WRITTEN: the refusal is the point, not the status line.
    with database.connection() as conn:
        rows = conn.execute("select count(*) from drafts where session_id = %s",
                            (session["id"],)).fetchone()
    assert rows[0] == 0


# -- Copilot's twelfth round on #25 -------------------------------------------


def test_a_draft_page_is_bounded_in_bytes_and_not_only_in_rows(
        client, database, mint_token) -> None:
    """A row limit is not a size limit when a row is a document.

    `PUT /drafts` caps one body at `MAX_REQUEST_BODY_BYTES` (1 MiB), and this
    listing returned up to `MAX_PAGE_SIZE` (500) of them — roughly 500 MiB
    fetched, serialized and held in a worker for ONE request, with a handful of
    concurrent callers enough to exhaust the process (Copilot review of
    openDox-code#25, round 12, suppressed). A page now carries no more body
    bytes than a single draft may, and ALWAYS AT LEAST ONE ROW so a draft
    larger than the budget is still readable and `after` can always advance.

    THE BODIES ARE GROWN IN SQL, and that is the point rather than a shortcut:
    the cap on the way IN is per draft, so the only way to make a page too
    large is with drafts that are each individually legal.
    """
    from opendox.runtime import identity
    from opendox.runtime.app import MAX_REQUEST_BODY_BYTES

    # THE BUDGET IS NAMED THROUGH THE REQUEST CAP, which exists in both shapes,
    # so what fails against the old one is the COUNT and not an import.
    budget = MAX_REQUEST_BODY_BYTES

    owner = mint_token(subject="page-bytes-owner")
    project = _project_with(client, owner, "page-bytes")
    session = client.post("/api/v1/sessions",
                          json={"project_id": project["id"]},
                          headers=_auth(owner)).json()
    keys = [f"big-{index}.md" for index in range(3)]
    for key in keys:
        saved = client.put("/api/v1/drafts",
                           json={"session_id": session["id"],
                                 "project_id": project["id"],
                                 "document_key": key, "body": "x"},
                           headers=_auth(owner))
        assert saved.status_code == 200, saved.text

    # Three legal drafts whose bodies together exceed the budget.
    chunk = 600 * 1024
    with database.transaction() as conn:
        conn.execute("update drafts set body = repeat('x', %s)", (chunk,))

    page = client.get("/api/v1/drafts?limit=500", headers=_auth(owner)).json()
    assert len(page) == 2, (
        f"the page returned {len(page)} drafts and "
        f"{sum(len(d['body']) for d in page)} body bytes; the budget is "
        f"{budget}")
    rest = client.get(f"/api/v1/drafts?limit=500&after={page[-1]['id']}",
                      headers=_auth(owner)).json()
    assert len(rest) == 1, rest
    assert {d["document_key"] for d in page} | {d["document_key"]
                                                for d in rest} == set(keys), (
        "the two pages are not the whole listing; `after` no longer walks it")

    # AND A DRAFT BIGGER THAN THE WHOLE BUDGET IS STILL RETURNED: the budget is
    # the bytes BEFORE a row, so the first row of a page is never excluded and
    # pagination can always make progress.
    with database.transaction() as conn:
        conn.execute("update drafts set body = repeat('x', %s)", (2 * budget,))
    single = client.get("/api/v1/drafts?limit=500", headers=_auth(owner)).json()
    assert len(single) == 1, len(single)
    assert len(single[0]["body"]) == 2 * budget

    # AND THE TWO NUMBERS ARE ONE NUMBER. Asserted last, so the behaviour above
    # is what a run against the old shape fails on.
    assert identity.MAX_PAGE_BODY_BYTES == MAX_REQUEST_BODY_BYTES, (
        "the page budget and the request cap have drifted apart; the rule is "
        "that a page carries no more body bytes than one draft may")


# -- Copilot's thirteenth round on #25 ----------------------------------------


def test_a_close_in_flight_orders_the_draft_write_instead_of_racing_it(
        client, database, postgres_dsn: str, mint_token) -> None:
    """"Evaluated by the write" is not the same as "serialized with the close".

    Round 10 put the session-open predicate INTO the insert, which closed the
    interval between the route's check and the write. It did not close the one
    inside the statement: under READ COMMITTED the `exists` subquery reads the
    snapshot the statement began with, so a `close_session` committing AFTER
    that snapshot and BEFORE this transaction commits still left the draft
    written into a sitting that had ended (Copilot review of openDox-code#25,
    round 13). `for update` makes the subquery WAIT on a close that is in
    flight and re-evaluate against the committed row.

    MEASURED WITH TWO REAL CONNECTIONS, and the assertion that fails against
    the old shape is the FIRST one: with the close uncommitted, the write is
    still running. Against the old shape it has already finished — successfully
    — and the draft is in the database before the session is closed.
    """
    import threading

    from opendox.runtime import identity
    from opendox.runtime.db import Database

    token = mint_token(subject="close-order")
    project = _project_with(client, token, "close-order")
    session = client.post("/api/v1/sessions", json={"project_id": project["id"]},
                          headers=_auth(token)).json()

    closing = Database(postgres_dsn, schema=database.schema,
                       application_name="opendox-test-closer")
    outcome: dict[str, object] = {}

    def _save() -> None:
        try:
            with database.transaction() as conn:
                identity.CoordinationStore(conn).put_draft(
                    session_id=session["id"], project_id=project["id"],
                    document_key="ordered.md", body="x")
            outcome["result"] = "saved"
        except BaseException as exc:            # noqa: BLE001 - recorded
            outcome["result"] = exc

    with closing:
        with closing.connection() as holder:
            # The close is IN FLIGHT: the row is updated and not committed.
            holder.execute("update sessions set ended_at = now() "
                           "where id = %s", (session["id"],))
            writer = threading.Thread(target=_save, daemon=True)
            writer.start()
            writer.join(timeout=3.0)
            assert writer.is_alive(), (
                "the draft write finished while a close was in flight; it read "
                "the session out of its own snapshot instead of waiting for "
                f"the row (outcome: {outcome.get('result')!r})")
            holder.commit()
        writer.join(timeout=15.0)

    assert not writer.is_alive(), "the write never finished after the commit"
    assert isinstance(outcome["result"], identity.NotFoundError), outcome
    with database.connection() as conn:
        rows = conn.execute("select count(*) from drafts where session_id = %s",
                            (session["id"],)).fetchone()
    assert rows[0] == 0, "a draft was written into a session that had ended"


def test_a_claim_that_stops_arriving_leaves_the_last_one_and_says_so(
        database, mint_token) -> None:
    """`coalesce` is the decision; the docstring was what was wrong.

    It said the display fields are "refreshed from the token's claims on every
    login" and that the row "records what it last said", which `coalesce` does
    not do: a claim that stops arriving leaves the previous value (Copilot
    review of openDox-code#25, round 13, suppressed). This runtime sees ONE
    TOKEN PER REQUEST, not a profile event — whether a token carries `email`
    depends on the scopes it was issued for — so assigning `excluded.email`
    directly would make the stored value FLAP between requests made with
    different tokens by the same person. Both halves are measured here, and the
    docstring now states the consequence: a value REMOVED at the broker is not
    cleared until a token arrives with a different one.
    """
    from opendox.runtime import identity

    with database.transaction() as conn:
        store = identity.CoordinationStore(conn)
        first = store.upsert_user(issuer="https://broker.test/realms/opendox",
                                  subject="claims-come-and-go",
                                  email="one@example.invalid",
                                  display_name="One")
        assert (first.email, first.display_name) == ("one@example.invalid",
                                                     "One")
        # A LATER TOKEN THAT CARRIES THE CLAIMS refreshes them.
        second = store.upsert_user(issuer="https://broker.test/realms/opendox",
                                   subject="claims-come-and-go",
                                   email="two@example.invalid",
                                   display_name="Two")
        assert second.id == first.id
        assert (second.email, second.display_name) == ("two@example.invalid",
                                                       "Two")
        # A LATER TOKEN THAT CARRIES NEITHER leaves them.
        third = store.upsert_user(issuer="https://broker.test/realms/opendox",
                                  subject="claims-come-and-go")
        assert third.id == first.id
        assert (third.email, third.display_name) == ("two@example.invalid",
                                                     "Two")
        assert third.last_seen_at >= second.last_seen_at


def test_the_page_budget_is_applied_before_the_bodies_are_fetched() -> None:
    """The cap bounded what the APPLICATION received and not what Postgres read.

    The inner query selected every `body` and carried it through the window
    function and the sort before the outer predicate dropped it, so a page of
    500 one-megabyte drafts still made the database read and move roughly 500
    MB to return a short prefix — the cost this cap exists to remove (Copilot
    review of openDox-code#25, round 15, suppressed). The inner query selects
    IDS and sizes now; the bodies are joined back on the ids that survive.

    Asserted on the statement, because that IS the fix: the behaviour — which
    rows come back, and that at least one always does — is measured by the case
    above, and is unchanged.
    """
    import inspect

    from opendox.runtime.identity import CoordinationStore

    source = inspect.getsource(CoordinationStore.list_drafts)
    inner = source.split('from drafts d join (', 1)[1].split(') page on', 1)[0]
    assert "octet_length(d.body)" in inner, (
        "the running sum no longer measures the bodies")
    assert "d.body" not in inner.replace("octet_length(d.body)", ""), (
        "the inner query still selects a body it does not return")
    assert "select d.id," in inner, inner
    # And the outer query is the one that names the columns a caller gets.
    assert "page on page.id = d.id" in source, source


def test_a_readiness_probe_makes_one_pool_checkout(
        client, monkeypatch: pytest.MonkeyPatch) -> None:
    """The probe's budget covers ONE checkout wait, and this asked for three.

    `test_deploy_shape.py` derives the readiness probe's `timeoutSeconds` from
    one `DEFAULT_CHECKOUT_TIMEOUT_SECONDS` plus the JWKS timeout, and holds it
    strictly over both. `/readyz` then checked out for `select 1`, again inside
    `plan()` and again inside `drift()` — each of which calls `applied()` — so
    a pool under contention made the probe wait three of those under a budget
    that covers one. kubelet cuts an over-budget probe off mid-flight and the
    next one overlaps it (Copilot review of openDox-code#25, round 19,
    suppressed).

    The count is the assertion, because the wait itself is a race: three
    checkouts is the defect whether or not a given run contends.
    """
    database = client.app.state.context.database
    checkouts = []
    real = database.connection

    def _counted(*args: object, **kwargs: object):
        checkouts.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(database, "connection", _counted)
    body = client.get("/readyz").json()
    assert body["checks"]["database"] == "ok", body
    assert body["checks"]["schema"] == "applied", body
    assert len(checkouts) == 1, (
        f"this probe checked out {len(checkouts)} pooled connections; the "
        "budget the manifests assert covers one")


def test_no_authorization_answer_echoes_the_path_it_refused(
        client, mint_token) -> None:
    """`_require_role` runs BEFORE any act has looked at the identifier.

    It reads the project id straight off the request path, and the repository
    routes § 3.6 adds made that reachable with arbitrary text — so `GET
    /projects/user:secret@host/repository` returned the caller's value in a 403
    body, ahead of every redaction the acts apply to their own refusals
    (Copilot review of openDox-code#26, round 24).

    An authorization answer needs the SUBJECT and the RULE, not the object's
    name: the caller sent the path and gets back which rule refused it. The
    same rule is applied to the session/project mismatch one message over,
    where the STORED project is still named — that one is a row this runtime
    wrote — and the requested one is not.
    """
    import urllib.parse

    token = mint_token(subject="path-echo")
    secretish = "user:secret@host"
    quoted = urllib.parse.quote(secretish, safe="")
    for path in (f"/api/v1/projects/{quoted}",
                 f"/api/v1/projects/{quoted}/repository",
                 f"/api/v1/projects/{quoted}/repository/remote",
                 f"/api/v1/projects/{quoted}/repository/push"):
        for call in (client.get, client.post, client.put):
            response = call(path, headers=_auth(token))
            if response.status_code in (404, 405):
                continue
            assert "secret" not in response.text, (path, response.text)
            assert secretish not in response.text, (path, response.text)

    # AND THE REFUSAL IS STILL AN ANSWER: it names the rule.
    refused = client.get(f"/api/v1/projects/{quoted}", headers=_auth(token))
    assert refused.status_code in (403, 404), refused.text
    if refused.status_code == 403:
        assert refused.json()["detail"]["code"].startswith("authz."), refused.text


def test_a_failed_pool_checkout_is_not_masked_by_the_stores_teardown() -> None:
    """`close()` must not call `__exit__` on a manager that never entered.

    THE FINDING (Copilot review of openDox-code#25, round 29, suppressed):
    `_open()` assigned `self._exit` and THEN called `__enter__()`, so a pool
    checkout or `BEGIN` that raised left `_exit` non-None — and `get_store`'s
    cleanup calls `store.close(exc)` on the way out, which calls `__exit__` on
    a context manager whose `__enter__` never completed. Whatever that raises
    replaces the database error that is the real answer.

    The manager is held in a local until `__enter__` returns. This test drives
    the failure directly rather than through a route, because the property is
    the proxy's and not any endpoint's: `close()` after a failed open must be
    a no-op, and the original exception must be what the caller sees.
    """
    from opendox.runtime import app as app_module

    class _NeverEnters:
        exits = 0

        def __enter__(self):
            raise RuntimeError("the pool is exhausted")

        def __exit__(self, *exc_info):
            _NeverEnters.exits += 1
            raise AssertionError(
                "__exit__ ran on a manager whose __enter__ never completed")

    class _Database:
        @staticmethod
        def transaction():
            return _NeverEnters()

    store = app_module._LazyStore(_Database())
    with pytest.raises(RuntimeError, match="the pool is exhausted") as caught:
        store.projects()                       # any attribute opens the store

    # THE TEARDOWN THAT `get_store` PERFORMS, on the object it is holding.
    store.close(caught.value)
    assert _NeverEnters.exits == 0, (
        "the teardown called __exit__ on a manager that never entered; "
        "whatever that raises would replace the database error")


def test_an_anonymous_token_naming_a_key_of_the_wrong_type_is_401_not_500(
        database, postgres_dsn: str, rsa_key_pair, tmp_path: Path) -> None:
    """The end of A25-2, measured where it was reported: at the HTTP boundary.

    A realm publishing an RSA and an EC signing key — Keycloak, the moment a
    realm has an ES256 provider beside the default RS256 one — let ANY
    anonymous caller send `Authorization: Bearer <RS256-shaped token, kid=the
    EC key's>` and turn `GET /api/v1/users/me` into a 500: PyJWT's
    `RSAAlgorithm.prepare_key` raises a plain `TypeError`, which is not a
    `PyJWTError` and not an `OidcError`, so it passed `_decode`'s seven typed
    clauses and `get_principal`'s handler alike. Both `kid`s are public facts
    from the unauthenticated JWKS endpoint (independent adversarial review of
    openDox-code#25, A25-2).

    `raise_server_exceptions=False` so the 500 is OBSERVED as a response
    rather than re-raised into the test — the client gets the 500 either way.
    """
    import json
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    from fastapi.testclient import TestClient
    from jwt.algorithms import ECAlgorithm, RSAAlgorithm

    from opendox.runtime import oidc
    from opendox.runtime.config import PREFIX, load_settings
    from tests_runtime.conftest import TEST_AUDIENCE
    from opendox.runtime.app import create_app
    from opendox.runtime.db import Database

    private, public = rsa_key_pair
    rsa_jwk = json.loads(RSAAlgorithm.to_jwk(public))
    rsa_jwk.update({"kid": "rsa-1", "use": "sig", "alg": "RS256"})
    ec_jwk = json.loads(ECAlgorithm.to_jwk(
        ec.generate_private_key(ec.SECP256R1()).public_key()))
    ec_jwk.update({"kid": "ec-1", "use": "sig", "alg": "ES256"})
    path = tmp_path / "two-types.json"
    path.write_text(json.dumps({"keys": [rsa_jwk, ec_jwk]}), encoding="utf-8")

    settings = load_settings({
        PREFIX + "DATABASE_URL": postgres_dsn,
        PREFIX + "OIDC_ISSUER": TEST_ISSUER,
        PREFIX + "OIDC_AUDIENCE": TEST_AUDIENCE,
    })
    app = create_app(
        settings=settings,
        database=Database(postgres_dsn, schema=database.schema),
        verifier=oidc.TokenVerifier(
            issuer=TEST_ISSUER, audience=TEST_AUDIENCE,
            jwks=oidc.CachingJwks(oidc.FileJwksSource(str(path)),
                                  ttl_seconds=300)))

    now = int(time.time())
    forged = jwt.encode(
        {"sub": "anyone", "iss": TEST_ISSUER, "aud": TEST_AUDIENCE,
         "iat": now, "exp": now + 300},
        private, algorithm="RS256", headers={"kid": "ec-1"})

    with TestClient(app, raise_server_exceptions=False) as client:
        answer = client.get("/api/v1/users/me",
                            headers={"Authorization": f"Bearer {forged}"})
    assert answer.status_code == 401, answer.text
    # AND THE REFUSAL SAYS NOTHING ABOUT THE KEY SET: an anonymous caller
    # learns that the token is not acceptable, not which key it reached.
    assert "PEM" not in answer.text
    assert "ec-1" not in answer.text


def test_the_readiness_budget_bounds_the_total_and_not_each_statement(
        monkeypatch) -> None:
    """`SET LOCAL statement_timeout` is PER STATEMENT, and a phase is several.

    The first answer set the bound once before each phase — `select 1`, then
    `plan()`, then `drift()` — and called that a total. It is not, and the
    multiplier is MEASURED off the runner rather than argued: driving the real
    `MigrationRunner.plan(conn)` and `.drift(conn)` against a recording
    connection issues THREE statements each (`selected_schema`, the
    `to_regclass` ledger probe, the ledger read), so the probe issues seven in
    all under three bounds — a worst case of 7 x 1.5s = 10.5s against a
    declared 3.0s database budget, every one of them inside the probe's own
    25s `timeoutSeconds`, so nothing downstream would have reported it
    (Copilot review of openDox-code#25, at `48de5833`).

    THE WORST CASE IS DRIVEN, not argued: the clock advances by exactly the
    timeout each statement was granted, which is the slowest a statement can be
    without being cut off. The total then cannot exceed the budget plus one
    ceiling — the term `test_deploy_shape.py` adds to the checkout and JWKS
    budgets — however many statements the runner issues.
    """
    import contextlib

    from opendox.runtime import app as app_module

    ROOT = Path(__file__).resolve().parents[1]
    now = {"t": 1000.0}
    monkeypatch.setattr(app_module.time, "monotonic", lambda: now["t"])

    issued: list[str] = []

    class _Conn:
        def execute(self, sql, *args, **kwargs):
            issued.append(sql)
            if sql.startswith("set local statement_timeout = "):
                # The statement this bound is for runs for exactly as long as
                # it is allowed to: the worst case that is not a timeout.
                granted = int(sql.rsplit("= ", 1)[1]) / 1000
                now["t"] += granted
            return self

    budget = app_module.READINESS_DATABASE_BUDGET_SECONDS
    ceiling = app_module.READINESS_STATEMENT_TIMEOUT_SECONDS
    started = now["t"]
    bounded = app_module.WithinTheDeadline(_Conn(), started + budget)

    statements = 0
    with pytest.raises(TimeoutError) as spent:
        for _ in range(100):               # far more than the probe issues
            bounded.execute("select 1")
            statements += 1
    assert "budget" in str(spent.value)
    assert statements >= 2, "the budget must admit more than one statement"

    elapsed = now["t"] - started
    assert elapsed <= budget + ceiling + 1e-3, (
        f"{statements} statements consumed {elapsed}s against a {budget}s "
        f"budget and a {ceiling}s per-statement ceiling")

    # EVERY statement was preceded by its own bound, which is the granularity
    # the finding was about.
    bounds = [s for s in issued if s.startswith("set local statement_timeout")]
    others = [s for s in issued if not s.startswith("set local")]
    assert len(bounds) == len(others) == statements
    # AND EACH BOUND IS THE SMALLER OF THE CEILING AND WHAT REMAINED, so the
    # last statement cannot be granted the whole ceiling out of a spent budget.
    granted = [int(s.rsplit("= ", 1)[1]) / 1000 for s in bounds]
    assert granted[0] == ceiling
    assert granted[-1] <= ceiling
    assert sum(granted) <= budget + 1e-3

    # AND THE REAL PHASES, NOT ONLY THE SYNTHETIC LOOP: the same worst-case
    # clock driving the ACTUAL `plan()` and `drift()` through the wrapper —
    # the seven statements measured above — spends the budget and is REFUSED
    # partway, which is the whole difference. At HEAD's one-bound-per-phase
    # shape the same seven ran to 10.5s and `/readyz` answered late instead of
    # answering "not ready".
    from opendox.runtime import migrations as migrations_module

    class _Row(list):
        def fetchone(self): return self
        def fetchall(self): return []

    class _Recording:
        def __init__(self, cost: float) -> None:
            self._cost = cost

        def execute(self, sql, params=None):
            issued.append(sql)
            if sql.startswith("set local statement_timeout = "):
                granted = int(sql.rsplit("= ", 1)[1]) / 1000
                now["t"] += self._cost if self._cost is not None else granted
                return _Row([])
            if "to_regclass" in sql:
                return _Row([True])
            return _Row(["public", "public", "public"])

        @contextlib.contextmanager
        def transaction(self):
            yield self

    def _drive(cost):
        issued.clear()
        now["t"] = start = 2000.0
        runner = migrations_module.MigrationRunner(
            None, migrations_dir=str(ROOT / "migrations"))
        probe = app_module.WithinTheDeadline(_Recording(cost), start + budget)
        probe.execute("select 1")
        runner.plan(probe)
        runner.drift(probe)
        return now["t"] - start

    with pytest.raises(TimeoutError):
        _drive(None)                       # every statement takes all it may
    spent = now["t"] - 2000.0
    assert spent <= budget + 1e-3, (
        f"the real probe consumed {spent}s of a {budget}s budget")

    # AND AN ORDINARY DATABASE STILL ANSWERS: at 10ms a statement all seven
    # run, which is the half of this a per-statement bound must not break.
    elapsed = _drive(0.010)
    real = [s for s in issued if not s.startswith("set local")]
    assert len(real) == 7, real            # the measurement, pinned
    assert elapsed < budget

    # AND THE WRAPPER IS TRANSPARENT for everything else the runner uses, so
    # `plan()` and `drift()` see the connection contract they are written for.
    class _Rich:
        schema = "public"

        def execute(self, sql, *args, **kwargs):
            return self

        def transaction(self):
            return self
    rich = app_module.WithinTheDeadline(_Rich(), now["t"] + 10)
    assert rich.schema == "public"
    assert rich.transaction() is not None


def test_no_credential_ever_enters_or_leaves_the_remote_url_column(
        client, database, mint_token) -> None:
    """`project_repositories.remote_url` was free text with nothing judging it.

    `migrations/0001_identity_and_coordination.sql` declares the column and
    argues only its NULLABILITY — "a remote can be attached later" — and no
    layer between a caller and that column looked at the value, so
    `https://ci:hunter2@github.com/o/r.git` was a legal row: stored in the
    clear in a database RULING Q1 gives identity and coordination and NOT
    secrets, returned verbatim by `GET /api/v1/project-repositories` to every
    member of the project, present in every backup, and handed to `git` by
    § 3.6 (Copilot review of openDox-code#25, on that column's line).

    BOTH LAYERS ARE EXERCISED HERE, because either alone is a half-measure:
    the store REFUSES the value on the way in, and the JSON boundary REDACTS a
    row that got in some other way — an earlier build, a restore, `psql`.
    The row below is written with raw SQL for exactly that reason: it is the
    only way to produce the state the second layer exists for.
    """
    from opendox.runtime.identity import (
        CoordinationStore,
        ProjectRepository,
        RefusedError,
    )

    owner = mint_token(subject="remote-url-owner")
    project = client.post("/api/v1/projects",
                          json={"slug": "remote-url", "title": "Remote"},
                          headers=_auth(owner)).json()

    # -- layer one: the store refuses, at BOTH writers, without echoing ------
    with database.transaction() as conn:
        store = CoordinationStore(conn)
        for carrier in ("https://ci:hunter2@github.com/o/r.git",
                        "ci:hunter2@github.com:o/r.git",
                        # A PASSWORD CONTAINING `/`, which the first cut of
                        # the scp branch could not see: it truncated at the
                        # first `/` — the shape of an scp authority — so
                        # `ci:hun/ter2@…` was reduced to `ci:hun`, read as a
                        # username with no password and called clean (Copilot
                        # review of openDox-code#25, at `0968ff8b`). It is the
                        # same class as round 29 on the sibling PR, where a
                        # bound that excluded `/` was defeated by a password
                        # holding one.
                        "ci:hun/ter2@github.com:o/r.git",
                        "file://ci:hunter2@/srv/repos/r.git",
                        "https://github.com/o/r.git?access_token=hunter2"):
            with pytest.raises(RefusedError) as refused:
                store.create_project_repository(
                    project_id=project["id"], adapter="local-git",
                    location="/srv/repos/r.git", remote_url=carrier)
            assert "hunter2" not in str(refused.value), carrier
            assert "ter2" not in str(refused.value), carrier
            assert "remote_url carries" in str(refused.value)
        # AND NOTHING WAS WRITTEN — the refusal is before the statement, so a
        # refused call does not leave the map row behind without its remote.
        assert conn.execute(
            "select count(*) from project_repositories where project_id = %s",
            (project["id"],)).fetchone()[0] == 0

        # The ORDINARY remotes are not refused: an ssh URL's userinfo is a
        # username, and that is the form every real remote takes.
        made = store.create_project_repository(
            project_id=project["id"], adapter="local-git",
            location="/srv/repos/r.git",
            remote_url="ssh://git@github.com/o/r.git")
        assert made.remote_url == "ssh://git@github.com/o/r.git"
        assert store.attach_remote(
            project_id=project["id"],
            remote_url="git@github.com:o/r.git").remote_url == \
            "git@github.com:o/r.git"
        with pytest.raises(RefusedError) as attached:
            store.attach_remote(project_id=project["id"],
                                remote_url="https://ci:hunter2@h/o/r.git")
        assert "hunter2" not in str(attached.value)

    # -- layer two: a row written around the store is redacted on the way out
    with database.transaction() as conn:
        conn.execute(
            "update project_repositories set remote_url = %s "
            "where project_id = %s",
            ("https://ci:hunter2@github.com/o/r.git", project["id"]))

    listed = client.get("/api/v1/project-repositories",
                        headers=_auth(owner)).json()
    assert len(listed) == 1
    assert "hunter2" not in listed[0]["remote_url"]
    # THE WHOLE VALUE, not the userinfo alone. This asserted
    # `https://<redacted>@github.com/o/r.git` while the boundary called a
    # SECOND redactor living in `config`; that second implementation is gone
    # (it disagreed with this module's about three shapes), so a password in
    # the authority takes the adapter's answer — over-redaction, which is the
    # safe direction for a row that was never supposed to exist.
    assert listed[0]["remote_url"] == "<redacted-url>"
    one = client.get(f"/api/v1/project-repositories/{project['id']}",
                     headers=_auth(owner))
    assert "hunter2" not in one.text
    # THE WHOLE RESPONSE, not just the field: a credential in any other key
    # would be this test passing for the wrong reason.
    assert "hunter2" not in client.get("/api/v1/project-repositories",
                                       headers=_auth(owner)).text

    # -- and the object's own `repr`, which is what a log line or a failing
    # assertion prints. The store refuses these, so a row carrying one came
    # from outside — and that is exactly the object nothing else protects.
    carried = ProjectRepository(
        id="r1", project_id=project["id"], adapter="local-git",
        location="/srv/repos/r.git",
        remote_url="https://ci:hunter2@github.com/o/r.git",
        created_at=made.created_at)
    assert "hunter2" not in repr(carried)
    assert "<redacted-url>" in repr(carried)
    # AND AN ORDINARY ROW PRINTS UNCHANGED, so the redaction is not noise.
    assert "ssh://git@github.com/o/r.git" in repr(made)


def test_the_map_endpoints_redact_every_shape_a_legacy_row_can_carry(
        client, database, mint_token) -> None:
    """The merge of § 3.5 pointed this boundary at a SECOND redactor.

    `_repository_json` called `local_git_adapter.redact_remote_url` and began
    calling `config.redacted_remote_url`, for a real reason — the general
    redactor replaces the userinfo of an ordinary `git@github.com:o/r.git`,
    which is a username and not a secret. But `config`'s was written for BROKER
    URLs and a `remote_url` is free text: it knew neither the libpq
    keyword/value form nor the parameter name `pass`, so
    `host=db password=hunter2 dbname=x` and `https://host/r.git?pass=hunter2`
    were returned VERBATIM by both map endpoints to every member of the
    project — a credential exposure introduced by this branch's own merge
    (Copilot review of openDox-code#26, at `555a03c8`).

    THE SHARED KEY LIST THAT CLOSED THOSE FOUR DID NOT CLOSE THE NEXT THREE.
    Two implementations reading one list still disagreed three times at
    `fe421882`, and TWICE IN THIS DIRECTION: `?%2574oken=…` (decoded once by
    `config`, to a fixed point by the adapter) and a newline inside an scp-form
    userinfo (`config` declines to judge a value holding whitespace) were both
    MEASURED coming back from these endpoints in the clear. The third, `;`, ran
    the other way — `config` hid it and the adapter did not, which cost a 500
    at the attach route rather than a leak here. So there is ONE redactor now: `config.redacted_remote_url` is a
    CALL into `local_git_adapter.redact_remote_url`, carrying the single
    nuance this boundary needs as an argument, and the seven shapes below are
    one function's answers rather than an agreement between two.

    THEY ARE DRIVEN THROUGH THE REAL ENDPOINTS, not through a redactor: the
    defect was in WHICH redactor the boundary called, and a case that asked a
    redactor directly would have passed throughout both rounds.
    """
    from opendox.runtime import app as app_module

    owner = mint_token(subject="legacy-shapes-owner")
    project = client.post("/api/v1/projects",
                          json={"slug": "legacy-shapes", "title": "Shapes"},
                          headers=_auth(owner)).json()
    with database.transaction() as conn:
        from opendox.runtime.identity import CoordinationStore
        CoordinationStore(conn).create_project_repository(
            project_id=project["id"], adapter="local-git",
            location="/srv/repos/legacy-shapes.git")

    keeps_its_host, redacted_whole = "host survives", "whole value"
    shapes = (
        ("host=db password=hunter2 dbname=x", keeps_its_host),
        ("https://github.com/o/r.git?pass=hunter2", keeps_its_host),
        ("https://github.com/o/r.git?sslpassword=hunter2", keeps_its_host),
        ("host=db sslpassword=hunter2", keeps_its_host),
        # -- and the three a second implementation printed in the clear ------
        # A DOUBLE-ENCODED PARAMETER NAME. The decode runs to a fixed point
        # here, so `%2574oken` reads as `token`; `config` decoded once and
        # handed the value back.
        ("https://github.com/o/r.git?%2574oken=hunter2", keeps_its_host),
        # `;` AS A PARAMETER DELIMITER — the disagreement that ran the OTHER
        # way, which is why it is here as a guard and not as a repair: at
        # `fe421882` `config` hid this shape at these very endpoints and the
        # ADAPTER printed it (git's stderr, the push refusals, the CLI's
        # `pushed_to`). Its `carries_a_credential` answered False with it, so
        # `repository_act.attach_remote` accepted a value the store then
        # refused with an `identity.RefusedError` the route does not catch —
        # a 500, measured, asserted a 409 at the end of this case.
        ("https://github.com/o/r.git?mode=1;token=hunter2", keeps_its_host),
        # A NEWLINE INSIDE AN scp-FORM AUTHORITY takes the WHOLE value, on
        # purpose: a value this runtime cannot read as one line is not one it
        # should print a PART of — half of it on a log line is how a redacted
        # field becomes two forged ones. `config` declined to judge it at all,
        # so it came back entire.
        ("user:hun\nter2@github.com:o/r.git", redacted_whole),
    )
    for legacy, survival in shapes:
        # AROUND THE STORE, which is what a legacy row is: § 3.5 refuses these
        # at `identity.CoordinationStore` itself, and the row this boundary
        # exists for is the one written before any such rule.
        with database.transaction() as conn:
            conn.execute(
                "update project_repositories set remote_url = %s "
                "where project_id = %s", (legacy, project["id"]))

        listed = client.get("/api/v1/project-repositories",
                            headers=_auth(owner))
        one = client.get(f"/api/v1/project-repositories/{project['id']}",
                         headers=_auth(owner))
        for response in (listed, one):
            assert response.status_code == 200, response.text
            assert "hunter2" not in response.text, legacy
        redacted = one.json()["remote_url"]
        if survival is keeps_its_host:
            assert "<redacted>" in redacted, legacy
            # AND THE HOST SURVIVES, so the row stays readable for what it is
            # for: an operator has to be able to see WHICH endpoint it names.
            assert ("github.com" in redacted or "host=db" in redacted), legacy
        else:
            assert redacted == "<redacted-url>", legacy

    # THE ORDINARY REMOTE IS STILL RETURNED EXACTLY AS STORED, which is the
    # reason this boundary passes the redactor its flag at all.
    for ordinary in ("ssh://git@github.com/o/r.git", "git@github.com:o/r.git"):
        with database.transaction() as conn:
            conn.execute(
                "update project_repositories set remote_url = %s "
                "where project_id = %s", (ordinary, project["id"]))
        unchanged = client.get(
            f"/api/v1/project-repositories/{project['id']}",
            headers=_auth(owner)).json()
        assert unchanged["remote_url"] == ordinary

    # AND THE BOUNDARY IS THE FUNCTION, asked directly for every shape so a
    # future edit that stops calling it is not hidden by the route.
    from datetime import datetime

    from opendox.runtime import identity as identity_module
    for legacy, _ in shapes:
        row = identity_module.ProjectRepository(
            id="r", project_id=project["id"], adapter="local-git",
            location="/srv/repos/legacy-shapes.git", remote_url=legacy,
            created_at=datetime(2026, 9, 18))
        assert "hunter2" not in app_module._repository_json(row)["remote_url"]

    # -- the `;` shape ARRIVING, which used to be a 500 ----------------------
    # `attach_remote` of `…?mode=1;token=…` raised out of the boundary rather
    # than refusing, because the two readings of `;` disagreed about whether
    # there was a parameter there at all. It is one refusal now: 409, the
    # SHAPE named, the value absent — and a 500 would be the regression.
    attached = client.put(
        f"/api/v1/projects/{project['id']}/repository/remote",
        json={"remote_url": "https://github.com/o/r.git?mode=1;token=hunter2"},
        headers=_auth(owner))
    assert attached.status_code == 409, attached.text
    assert "hunter2" not in attached.text
    assert "credential-shaped query or fragment parameter" in attached.text

    # -- and the shape NEITHER READING SAW: whitespace in the authority ------
    # `user:pa ss@host:path`. Both classes exclude whitespace on purpose — the
    # refusal so it cannot start judging prose, the redactor so an unrelated
    # `user@host` three lines down git's stderr is not joined to the URL above
    # it — and between them sat an scp-form authority holding a SPACE, which
    # went through this boundary in the clear. MEASURED, then closed at the
    # one-URL entry point, where the caller knows it holds one value.
    with database.transaction() as conn:
        conn.execute(
            "update project_repositories set remote_url = %s "
            "where project_id = %s",
            ("user:hun ter2@github.com:o/r.git", project["id"]))
    spaced = client.get(f"/api/v1/project-repositories/{project['id']}",
                        headers=_auth(owner))
    assert spaced.status_code == 200, spaced.text
    assert "hun ter2" not in spaced.text
    assert spaced.json()["remote_url"] == "<redacted-url>"

    # AND NO WRITER CAN MAKE THAT ROW: the act refuses the shape, so the value
    # above is legacy by construction. (`identity.CoordinationStore`'s own
    # guard does NOT name it — `config._scp_like_userinfo` declines a
    # whitespace-bearing head — so a raw-SQL writer still can. That is a § 3.5
    # gap, landed, and it is registered on openDox-code#26 as a follow-up
    # rather than widened from here; this layer is what holds meanwhile.)
    refused = client.put(
        f"/api/v1/projects/{project['id']}/repository/remote",
        json={"remote_url": "user:hun ter2@github.com:o/r.git"},
        headers=_auth(owner))
    assert refused.status_code == 409, refused.text
    assert "hun ter2" not in refused.text


# -- the registered follow-ups, from #26's rounds -----------------------------


def test_a_map_row_deleted_under_an_act_is_a_404_and_not_a_500(
        client, database, mint_token, monkeypatch) -> None:
    """`_found` wrapped the PRE-CHECK, and the act is a second statement.

    Both repository routes read the map row with `_found(...)` and then call
    the act, which takes the row FOR UPDATE inside itself. Between those two
    statements the row can be deleted — by another owner, by a project being
    torn down — and `_local_git_row` then raises `identity.NotFoundError` past
    a handler that catches only `RepositoryActRefused`. The ordinary
    disappeared-row race therefore answered 500 where this API documents 404
    (Copilot review of openDox-code#26, at `db5197d0`, suppressed, registered
    there and built here). It is the same class as openDox-code#25's round 10
    on the draft-discard path, whose repair this follows: the translation
    belongs on the call that can raise, not on a read taken beforehand.

    THE RACE IS ARRANGED, NOT RACED: the deletion is driven from inside the
    act's own entry point, which is the only window where it matters, and it is
    a REAL delete on another connection — the shape the defect takes.
    """
    from opendox.runtime import repository_act

    owner = mint_token(subject="vanishing-row-owner")
    project = client.post("/api/v1/projects",
                          json={"slug": "vanishing", "title": "Vanishing"},
                          headers=_auth(owner)).json()

    def _delete_the_row() -> None:
        with database.transaction() as conn:
            conn.execute("delete from project_repositories where project_id = %s",
                         (project["id"],))

    for verb, call, act_name in (
            ("attach",
             lambda: client.put(
                 f"/api/v1/projects/{project['id']}/repository/remote",
                 # NO USERINFO AT ALL: the act refuses even a bare
                 # username in a remote it is asked to STORE, which is its own
                 # documented trade, and a 409 here would measure that rule
                 # instead of this race.
                 json={"remote_url": "https://github.com/o/r.git"},
                 headers=_auth(owner)),
             "attach_remote"),
            ("push",
             lambda: client.post(
                 f"/api/v1/projects/{project['id']}/repository/push",
                 headers=_auth(owner)),
             "push_to_remote")):
        with database.transaction() as conn:
            from opendox.runtime.identity import CoordinationStore
            CoordinationStore(conn).create_project_repository(
                project_id=project["id"], adapter="local-git",
                location="/srv/repos/vanishing.git")
        real = getattr(repository_act, act_name)

        def _delete_then_act(*args, _real=real, **kwargs):
            _delete_the_row()
            return _real(*args, **kwargs)

        monkeypatch.setattr(repository_act, act_name, _delete_then_act)
        response = call()
        monkeypatch.undo()
        assert response.status_code == 404, (verb, response.status_code,
                                             response.text)
        body = response.json()["detail"]
        assert body["code"] == "coordination.not_found", verb
        # AND THE MESSAGE IS THE STORE'S OWN, so an operator reading it learns
        # WHAT was not found rather than that something went wrong.
        assert "repository" in body["message"].lower(), body["message"]
