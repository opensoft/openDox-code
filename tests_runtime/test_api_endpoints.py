"""The six collections, exercised end to end against a real Postgres.

An in-process client over the real application, the real `TokenVerifier`
(local key set) and the real migrated schema — so what is measured here is what
a deployed runtime does, not what a stub agrees to.

DB-BACKED — runs in the `runtime` CI job; skipped, with the reason printed,
where no `OPENDOX_TEST_DATABASE_URL` is reachable.
"""

from __future__ import annotations

import pytest

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
    assert "password" not in body and "token" not in body

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
