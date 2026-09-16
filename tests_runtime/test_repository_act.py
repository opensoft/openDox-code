"""§ 3.6's act, against a real database and a real git.

"openDox CREATES A REPOSITORY AS A FIRST-CLASS ACT, or the origin complaint
returns one level down" — `split-opendox-two-layer-product` § 3.6. So what is
measured here is the PAIR: the map row and the repository, together or not at
all, and then the two successors RULING C3 names — a remote attached later, and
a move that is a push.

DB-BACKED — runs in the `runtime` CI job. The adapter's own conformance is
proved hermetically in `test_local_git_adapter.py`, in the REQUIRED job.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from opendox import corpus_adapter as ca
from opendox.runtime import identity
from opendox.runtime import local_git_adapter as lga
from opendox.runtime import repository_act as act

pytestmark = pytest.mark.skipif(
    not lga.git_available(),
    reason="`git` is not on PATH, so RULING C3's repository cannot be created")

ACTOR = "Student One"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.fixture()
def owner(store) -> identity.User:
    return store.upsert_user(issuer="https://broker.test/realms/opendox",
                             subject="student-1", display_name=ACTOR)


@pytest.fixture()
def project(store, owner: identity.User) -> identity.Project:
    project = store.create_project(slug="first", title="First",
                                   created_by=owner.id)
    store.create_membership(user_id=owner.id, project_id=project.id,
                            role="owner")
    return project


# -- the act -----------------------------------------------------------------


def test_the_act_writes_the_map_row_and_creates_the_repository(
        store, project, project_repository_root: Path) -> None:
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    assert created.row.project_id == project.id
    assert created.row.adapter == lga.ADAPTER_NAME
    assert created.row.remote_url is None
    assert created.location == project_repository_root / project.id
    assert created.location.is_dir()

    # The row the API reads and the repository on disk are the same thing.
    row = store.repository_for_project(project.id)
    assert row.location == str(created.location)
    assert _git(created.location, "rev-parse", "HEAD") == created.initial_commit


def test_the_created_repository_resolves_through_the_adapter(
        store, project, project_repository_root: Path) -> None:
    """The act's product and § 3.7's subject are the same object."""
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    adapter = lga.LocalGitCorpus()
    corpus = adapter.resolve(created.ref)
    assert corpus.revision == created.initial_commit
    assert corpus.write_path == lga.WRITE_PATH
    assert adapter.list_documents(corpus) == ()


def test_a_second_act_on_the_same_project_is_refused(
        store, project, project_repository_root: Path) -> None:
    """The map is one row per project — RULING C3's "per project"."""
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    with pytest.raises(identity.ConflictError) as caught:
        act.create_repository(store, project_id=project.id,
                              root=project_repository_root, actor=ACTOR)
    assert project.id in str(caught.value)


def test_a_directory_nobody_can_account_for_is_refused_and_the_row_rolls_back(
        database, project_repository_root: Path) -> None:
    """The window the act cannot close, refused rather than adopted — AND the
    pairing, proved over real transactions rather than asserted in a docstring.

    A process killed between `git init` and the transaction's commit leaves a
    directory with no row. Initializing over it, or adopting it, is how a
    project ends up pointed at somebody else's history. The act writes the row
    first, so this test also has to show the row does not survive the refusal:
    it runs the act inside `database.transaction()` and then asks a FRESH
    connection whether anything was committed.
    """
    with database.transaction() as conn:
        store = identity.CoordinationStore(conn)
        owner = store.upsert_user(issuer="https://broker.test/realms/opendox",
                                  subject="orphan-owner", display_name=ACTOR)
        project = store.create_project(slug="orphaned", title="Orphaned",
                                       created_by=owner.id)
        store.create_membership(user_id=owner.id, project_id=project.id,
                                role="owner")

    orphan = project_repository_root / project.id
    orphan.mkdir(parents=True)
    (orphan / "something").write_text("left behind\n", encoding="utf-8")

    with pytest.raises(act.RepositoryActRefused) as caught:
        with database.transaction() as conn:
            act.create_repository(identity.CoordinationStore(conn),
                                  project_id=project.id,
                                  root=project_repository_root, actor=ACTOR)
    assert "already exists and is not empty" in str(caught.value)
    assert "will not adopt" in str(caught.value)

    with database.connection() as conn:
        with pytest.raises(identity.NotFoundError):
            identity.CoordinationStore(conn).repository_for_project(project.id)
    # And the directory is exactly as it was: the act refuses before it writes.
    assert sorted(p.name for p in orphan.iterdir()) == ["something"]


def test_a_repository_that_cannot_be_created_leaves_no_row_behind(
        database, project_repository_root: Path, monkeypatch) -> None:
    """The other half of the pairing: git fails, and the row goes with it."""
    with database.transaction() as conn:
        store = identity.CoordinationStore(conn)
        owner = store.upsert_user(issuer="https://broker.test/realms/opendox",
                                  subject="failing-owner", display_name=ACTOR)
        project = store.create_project(slug="failing", title="Failing",
                                       created_by=owner.id)
        store.create_membership(user_id=owner.id, project_id=project.id,
                                role="owner")

    with pytest.raises(act.RepositoryActRefused):
        with database.transaction() as conn:
            act.create_repository(identity.CoordinationStore(conn),
                                  project_id=project.id,
                                  root=project_repository_root, actor=ACTOR,
                                  # A git that is on PATH and refuses every
                                  # command: `false` exits 1 for anything.
                                  executable="false")

    with database.connection() as conn:
        with pytest.raises(identity.NotFoundError):
            identity.CoordinationStore(conn).repository_for_project(project.id)


def test_the_repository_is_addressed_by_project_id_and_not_by_slug(
        store, project, project_repository_root: Path) -> None:
    """A slug is a human name a rename would move; a location must not."""
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    assert created.location.name == project.id
    assert project.slug not in str(created.location)


# -- a write is a commit, through the act's product --------------------------


def test_a_document_written_through_the_adapter_is_a_commit(
        store, project, project_repository_root: Path) -> None:
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    adapter = lga.LocalGitCorpus()
    corpus = adapter.resolve(created.ref)
    receipt = adapter.write_back(
        corpus, ca.DocumentId(project.id, "ideation/first.md"), b"# one\n",
        actor=ACTOR, basis_revision=corpus.revision or "",
        reason="the first save")
    assert _git(created.location, "cat-file", "-t",
                receipt.correlation_id) == "commit"
    assert _git(created.location, "rev-list", "--count", "HEAD") == "2"
    # And the map row is untouched: a write is not an act on the map.
    row = store.repository_for_project(project.id)
    assert row.location == str(created.location)
    assert row.remote_url is None


# -- a remote attached later -------------------------------------------------


def test_attaching_a_remote_changes_no_local_content(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """RULING C3: "a remote can be attached later" — and nothing else moves."""
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    adapter = lga.LocalGitCorpus()
    corpus = adapter.resolve(created.ref)
    adapter.write_back(corpus, ca.DocumentId(project.id, "ideation/first.md"),
                       b"# one\n", actor=ACTOR,
                       basis_revision=corpus.revision or "")

    before_head = _git(created.location, "rev-parse", "HEAD")
    before_tree = _git(created.location, "ls-tree", "-r", "HEAD")
    before_refs = _git(created.location, "show-ref")
    before_objects = _git(created.location, "count-objects", "-v")

    remote = tmp_path / "governed-factory.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main",
                    str(remote)], check=True, capture_output=True)
    row = act.attach_remote(store, project_id=project.id,
                            remote_url=str(remote))

    assert row.remote_url == str(remote)
    assert store.repository_for_project(project.id).remote_url == str(remote)
    assert _git(created.location, "remote", "get-url", "origin") == str(remote)
    assert _git(created.location, "rev-parse", "HEAD") == before_head
    assert _git(created.location, "ls-tree", "-r", "HEAD") == before_tree
    assert _git(created.location, "show-ref") == before_refs
    assert _git(created.location, "count-objects", "-v") == before_objects


def test_attaching_a_second_time_replaces_the_url_rather_than_failing(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    first = tmp_path / "one.git"
    second = tmp_path / "two.git"
    act.attach_remote(store, project_id=project.id, remote_url=str(first))
    row = act.attach_remote(store, project_id=project.id, remote_url=str(second))
    assert row.remote_url == str(second)


# -- the move is a push ------------------------------------------------------


def test_moving_into_a_governed_factory_is_a_push_not_a_migration(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """RULING C3's last clause, executed.

    Nothing is converted, exported or re-created: the same objects the local
    repository holds arrive at the remote, and the local repository keeps
    serving reads through the same adapter afterwards.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    adapter = lga.LocalGitCorpus()
    corpus = adapter.resolve(created.ref)
    receipt = adapter.write_back(
        corpus, ca.DocumentId(project.id, "ideation/first.md"), b"# one\n",
        actor=ACTOR, basis_revision=corpus.revision or "")

    remote = tmp_path / "governed-factory.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main",
                    str(remote)], check=True, capture_output=True)
    act.attach_remote(store, project_id=project.id, remote_url=str(remote))

    local_head_before = _git(created.location, "rev-parse", "HEAD")
    pushed_to = act.push_to_remote(store, project_id=project.id)

    assert pushed_to == str(remote)
    # The SAME commit is now at the factory, by sha — not a re-created one.
    assert _git(remote, "rev-parse", "refs/heads/main") == receipt.correlation_id
    assert _git(remote, "ls-tree", "-r", "--name-only",
                "refs/heads/main") == "ideation/first.md"
    # And the project is unchanged and still served from where it was.
    assert _git(created.location, "rev-parse", "HEAD") == local_head_before
    assert store.repository_for_project(project.id).location == str(
        created.location)
    after = adapter.resolve(created.ref)
    assert adapter.read(after, ca.DocumentId(project.id, "ideation/first.md")
                        ).content == b"# one\n"


def test_a_push_with_no_attached_remote_is_refused_by_name(
        store, project, project_repository_root: Path) -> None:
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert "no attached remote" in str(caught.value)


# -- the act over the API ----------------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_the_act_is_a_verb_on_the_api_and_only_an_owner_may_perform_it(
        client_with_repositories, mint_token, project_repository_root: Path
) -> None:
    client = client_with_repositories
    owner = mint_token(subject="api-owner")
    stranger = mint_token(subject="api-stranger")
    project = client.post("/api/v1/projects",
                          json={"slug": "api-first", "title": "API first"},
                          headers=_auth(owner)).json()

    refused = client.post(f"/api/v1/projects/{project['id']}/repository",
                          headers=_auth(stranger))
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "authz.not_a_member"

    created = client.post(f"/api/v1/projects/{project['id']}/repository",
                          headers=_auth(owner))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["adapter"] == lga.ADAPTER_NAME
    assert body["remote_url"] is None
    location = Path(body["location"])
    assert location == project_repository_root / project["id"]
    assert _git(location, "rev-parse", "HEAD") == body["initial_commit"]

    # The map now answers for this project, where a moment ago it did not.
    mapped = client.get(f"/api/v1/project-repositories/{project['id']}",
                        headers=_auth(owner))
    assert mapped.status_code == 200
    assert mapped.json()["location"] == body["location"]


def test_the_api_refuses_a_second_repository_for_one_project(
        client_with_repositories, mint_token) -> None:
    client = client_with_repositories
    owner = mint_token(subject="api-owner-2")
    project = client.post("/api/v1/projects",
                          json={"slug": "api-second", "title": "API second"},
                          headers=_auth(owner)).json()
    assert client.post(f"/api/v1/projects/{project['id']}/repository",
                       headers=_auth(owner)).status_code == 201
    again = client.post(f"/api/v1/projects/{project['id']}/repository",
                        headers=_auth(owner))
    assert again.status_code == 409


def test_the_api_attaches_a_remote_and_then_pushes(
        client_with_repositories, mint_token, tmp_path: Path) -> None:
    client = client_with_repositories
    owner = mint_token(subject="api-owner-3")
    project = client.post("/api/v1/projects",
                          json={"slug": "api-push", "title": "API push"},
                          headers=_auth(owner)).json()
    created = client.post(f"/api/v1/projects/{project['id']}/repository",
                          headers=_auth(owner)).json()

    pushed_too_early = client.post(
        f"/api/v1/projects/{project['id']}/repository/push", headers=_auth(owner))
    assert pushed_too_early.status_code == 409
    assert "no attached remote" in pushed_too_early.json()["detail"]["message"]

    remote = tmp_path / "factory.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main",
                    str(remote)], check=True, capture_output=True)
    attached = client.put(f"/api/v1/projects/{project['id']}/repository/remote",
                          json={"remote_url": str(remote)}, headers=_auth(owner))
    assert attached.status_code == 200
    assert attached.json()["remote_url"] == str(remote)

    pushed = client.post(f"/api/v1/projects/{project['id']}/repository/push",
                         headers=_auth(owner))
    assert pushed.status_code == 200, pushed.text
    assert pushed.json()["pushed_to"] == str(remote)
    assert _git(remote, "rev-parse", "refs/heads/main") == created["initial_commit"]


def test_the_act_on_a_project_that_does_not_exist_is_the_non_members_refusal(
        client_with_repositories, mint_token) -> None:
    """AND IT IS THE SAME REFUSAL A NON-MEMBER OF A REAL PROJECT GETS.

    This asserted a 404, which meant the route read the project BEFORE it
    asked about the membership — so a stranger could tell a project that does
    not exist (404) from one it may not act on (403) and walk the id space
    (Copilot review of openDox-code#26, round 6). `read_project` already asked
    in the other order for exactly this reason; the three repository verbs ask
    in that order now, and the two cases are one answer.
    """
    client = client_with_repositories
    token = mint_token(subject="api-owner-4")
    absent = client.post("/api/v1/projects/no-such-project/repository",
                         headers=_auth(token))
    assert absent.status_code == 403
    assert absent.json()["detail"]["code"] == "authz.not_a_member"

    owner = mint_token(subject="api-owner-4-real")
    real = client.post("/api/v1/projects",
                       json={"slug": "oracle-check", "title": "Oracle check"},
                       headers=_auth(owner)).json()
    hidden = client.post(f"/api/v1/projects/{real['id']}/repository",
                         headers=_auth(token))
    assert hidden.status_code == absent.status_code
    assert hidden.json() == absent.json() or (
        hidden.json()["detail"]["code"] == absent.json()["detail"]["code"]), (
        "the two refusals differ, so the route still answers which projects "
        "exist")


def test_every_repository_verb_is_owner_gated_before_it_touches_git(
        client_with_repositories, mint_token, tmp_path: Path) -> None:
    """The negative test covered CREATE alone.

    Attach and push were exercised only with the owner, so removing
    `_require_role` from either would have left the suite green against the
    stated contract that all three verbs are owner-gated (Copilot review of
    openDox-code#26, round 6). Each verb is asked twice here: by a stranger,
    who is no member at all, and by a READER, who is a member with the wrong
    role — and the refusal must arrive before any git side effect.
    """
    client = client_with_repositories
    owner = mint_token(subject="gate-owner")
    stranger = mint_token(subject="gate-stranger")
    reader = mint_token(subject="gate-reader")
    project = client.post("/api/v1/projects",
                          json={"slug": "gated", "title": "Gated"},
                          headers=_auth(owner)).json()
    reader_me = client.get("/api/v1/users/me", headers=_auth(reader)).json()
    client.post("/api/v1/memberships",
                json={"user_id": reader_me["id"], "project_id": project["id"],
                      "role": "reader"}, headers=_auth(owner))

    destination = tmp_path / "gated-factory.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(destination)],
                   check=True)
    base = f"/api/v1/projects/{project['id']}/repository"
    calls = (
        ("post", base, None),
        ("put", base + "/remote", {"remote_url": str(destination)}),
        ("post", base + "/push", None),
    )
    for method, url, body in calls:
        for token, code in ((stranger, "authz.not_a_member"),
                            (reader, "authz.role_insufficient")):
            call = getattr(client, method)
            response = (call(url, json=body, headers=_auth(token)) if body
                        else call(url, headers=_auth(token)))
            assert response.status_code == 403, (method, url, response.text)
            assert response.json()["detail"]["code"] == code, (method, url)
    # And nothing git-shaped happened: no repository row, and no refs at the
    # destination the refused attach named.
    assert client.get(f"/api/v1/project-repositories/{project['id']}",
                      headers=_auth(owner)).status_code == 404
    assert subprocess.run(["git", "--git-dir", str(destination),
                           "rev-parse", "--verify", "--quiet", "HEAD"],
                          capture_output=True).returncode != 0


# -- the review round's own assertions (Copilot review of openDox-code#26) ---


def test_the_map_records_an_absolute_location(store, project, tmp_path: Path,
                                              monkeypatch) -> None:
    """A relative root in the durable map resolves against whatever working
    directory the next process happens to have.

    THE RELATIVE PATH IS RESOLVED UNDER `tmp_path`, and the working directory
    is moved there for the test rather than the assertion being softened. The
    first cut passed `Path("var")/"projects"` and let it resolve against
    pytest's own working directory — the checkout — and then cleaned up with
    `rmtree(created.location.parent.parent)`, which is the checkout's `var/`:
    a developer with anything under `var/` lost it to a test whose subject is a
    path (Copilot review of openDox-code#26). `monkeypatch.chdir` keeps the
    relative-root property being measured and puts the resolution somewhere
    this test owns.
    """
    monkeypatch.chdir(tmp_path)
    relative = Path("var") / "projects"
    created = act.create_repository(store, project_id=project.id,
                                    root=relative, actor=ACTOR)
    assert Path(created.row.location).is_absolute()
    assert created.location.is_absolute()
    # ...and it resolved under the directory this test owns, which is the half
    # of the property the `is_absolute()` assertions cannot see.
    assert created.location.is_relative_to(tmp_path.resolve())


def test_an_already_mapped_project_is_refused_the_same_way_with_or_without_git(
        store, project, project_repository_root: Path) -> None:
    """The map is the authoritative fact; the environment is checked after it.

    With `git_available` first, a repeat create answered "git is not on PATH"
    on a host without git and `ConflictError` on a host with it — the same act
    giving two different answers about the same durable fact.
    """
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    with pytest.raises(identity.ConflictError):
        act.create_repository(store, project_id=project.id,
                              root=project_repository_root, actor=ACTOR,
                              executable="git-that-is-not-installed")


def test_a_path_collision_is_a_named_refusal_and_not_a_notadirectoryerror(
        store, project, project_repository_root: Path) -> None:
    (project_repository_root / project.id).write_text("in the way\n",
                                                      encoding="utf-8")
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.create_repository(store, project_id=project.id,
                              root=project_repository_root, actor=ACTOR)
    assert "is not a directory" in str(caught.value)


def test_a_row_owned_by_another_adapter_is_never_touched(
        store, project, tmp_path: Path) -> None:
    """The map carries an `adapter` column precisely so a project can be served
    by something else; these acts ignored it and would have run `git remote
    set-url` and `git push` against another adapter's opaque location."""
    store.create_project_repository(project_id=project.id,
                                    adapter="governed-factory",
                                    location=str(tmp_path / "not-ours"))
    for call in (
            lambda: act.attach_remote(store, project_id=project.id,
                                      remote_url="https://example.invalid/x.git"),
            lambda: act.push_to_remote(store, project_id=project.id)):
        with pytest.raises(act.RepositoryActRefused) as caught:
            call()
        assert "governed-factory" in str(caught.value)
        assert "must not touch another adapter's corpus" in str(caught.value)


def test_a_remote_url_carrying_a_credential_is_refused_without_echoing_it(
        store, project, project_repository_root: Path) -> None:
    """`remote_url` is read back by the repository endpoints to any
    authenticated caller, and is stored durably with nothing to rotate it."""
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    for url in ("https://someone:ghp_supersecrettoken@example.invalid/x.git",
                "git@github.com:opensoft/x.git",
                "ssh://user:pw@example.invalid/x.git"):
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.attach_remote(store, project_id=project.id, remote_url=url)
        message = str(caught.value)
        assert "user information" in message
        assert url not in message, "the refusal echoed the URL back"
        assert "supersecrettoken" not in message
    # ...and a URL with no userinfo is accepted.
    row = act.attach_remote(store, project_id=project.id,
                            remote_url="https://example.invalid/x.git")
    assert row.remote_url == "https://example.invalid/x.git"


def test_the_remote_this_runtime_attaches_is_the_one_it_pushes_to(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`attach_remote` took a `remote_name` the map could not record, so
    `attach_remote(..., remote_name="upstream")` succeeded and the push then
    looked for `origin` and found nothing."""
    import inspect

    assert "remote_name" not in inspect.signature(act.attach_remote).parameters
    assert "remote_name" not in inspect.signature(act.push_to_remote).parameters
    assert act.REMOTE_NAME == "origin"

    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    remote = tmp_path / "factory.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main",
                    str(remote)], check=True, capture_output=True)
    act.attach_remote(store, project_id=project.id, remote_url=str(remote))
    assert _git(created.location, "remote", "get-url",
                act.REMOTE_NAME) == str(remote)
    act.push_to_remote(store, project_id=project.id)
    assert _git(remote, "rev-parse", "refs/heads/main") == created.initial_commit


def test_a_credential_in_a_query_or_fragment_is_refused_too(
        store, project, project_repository_root: Path) -> None:
    """Userinfo is not the only place a secret hides."""
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    for url in ("https://example.invalid/x.git?token=ghp_supersecrettoken",
                "https://example.invalid/x.git?a=1&access_key=abc",
                "https://example.invalid/x.git#password=hunter2"):
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.attach_remote(store, project_id=project.id, remote_url=url)
        message = str(caught.value)
        assert "credential-shaped query or fragment" in message
        assert "supersecrettoken" not in message
        assert "hunter2" not in message


def test_a_url_that_will_not_parse_is_a_named_refusal_and_not_a_500(
        store, project, project_repository_root: Path) -> None:
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    for url in ("https://[bad", "http://[::1", "   "):
        with pytest.raises(act.RepositoryActRefused):
            act.attach_remote(store, project_id=project.id, remote_url=url)


def test_a_failed_git_remote_never_carries_the_url_into_the_refusal(
        store, project, project_repository_root: Path) -> None:
    """`GitCommandFailed` formatted its whole argv.

    A failed `git remote add <url>` therefore put the caller's URL — and any
    credential in it — into the message the API and the CLI return verbatim,
    defeating the guarantee the successful path keeps.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    # A remote name git refuses, so `git remote add` fails with the URL in argv.
    git = lga.GitRunner(created.location)
    with pytest.raises(lga.GitCommandFailed) as caught:
        git.out("remote", "add", "not a valid remote name",
                "https://someone:ghp_supersecrettoken@example.invalid/x.git")
    message = str(caught.value)
    assert "supersecrettoken" not in message, message
    assert "<redacted-url>" in message or "example.invalid" not in message
    # ...and the argv is still available to a debugger.
    assert "remote" in caught.value.args_run


def test_a_push_is_bounded_and_never_waits_for_a_password(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """The push runs inside the caller's database transaction.

    An unbounded, interactive push held the request, the repository and that
    transaction for as long as the network — or a password prompt nobody was
    there to answer — wanted.
    """
    import inspect

    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    source = inspect.getsource(act.push_to_remote)
    assert "out_bounded" in source
    assert "PUSH_TIMEOUT_SECONDS" in source
    assert act.PUSH_TIMEOUT_SECONDS > 0

    # A remote that does not exist fails promptly and by name, rather than
    # blocking on a prompt.
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(tmp_path / "there-is-no-repository-here"))
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert "push" in str(caught.value)
    assert created.location.is_dir()


def test_initialize_repository_keeps_the_orphan_guarantee_on_its_own(
        tmp_path: Path) -> None:
    """It is public and § 3.7's corpus setup calls it directly.

    Only `create_repository` checked, so a direct caller could `git init
    --bare` over a non-empty, unaccounted directory and mix the two.
    """
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "somebody-elses-file").write_text("!", encoding="utf-8")
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.initialize_repository(occupied, project_id="p", actor=ACTOR)
    assert "will not adopt" in str(caught.value)

    collision = tmp_path / "collision"
    collision.write_text("not a directory\n", encoding="utf-8")
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.initialize_repository(collision, project_id="p", actor=ACTOR)
    assert "is not a directory" in str(caught.value)


def test_a_symlink_at_the_project_location_is_refused(tmp_path: Path) -> None:
    """Every other guard FOLLOWS the link.

    A symlink pointing at an empty directory passed the emptiness check, and
    `git init --bare` then wrote through it into somebody else's tree — the
    adoption these refusals exist to prevent, arriving by the one route they
    did not look at.
    """
    elsewhere = tmp_path / "somebody-elses-empty-directory"
    elsewhere.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(elsewhere)
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.initialize_repository(link, project_id="p", actor=ACTOR)
    assert "symbolic link" in str(caught.value)
    assert list(elsewhere.iterdir()) == [], "the act wrote through the link"

    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "there-is-nothing-here")
    with pytest.raises(act.RepositoryActRefused):
        act.initialize_repository(dangling, project_id="p", actor=ACTOR)


def test_a_failed_push_redacts_the_stored_remote(store, project,
                                                 project_repository_root: Path,
                                                 tmp_path: Path) -> None:
    """A row written before the credential rule existed can still carry one."""
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    legacy = "https://someone:ghp_supersecrettoken@example.invalid/x.git"
    # Written straight into the map AND into git's config, which is the state a
    # row predating `refuse_credential_bearing_remote` actually leaves behind:
    # the old act wrote both. `push_to_remote` now checks that the two agree
    # before it sends anything, so a legacy row is only reachable when they do.
    store.attach_remote(project_id=project.id, remote_url=legacy)
    _git(created.location, "remote", "add", act.REMOTE_NAME, legacy)
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert "supersecrettoken" not in str(caught.value)
    assert "<redacted-url>" in str(caught.value)


# -- Copilot's fourth round on #26 -------------------------------------------


def test_whitespace_does_not_smuggle_a_credential_past_the_refusal() -> None:
    """`urlsplit` accepts leading whitespace; both checks below it are anchored.

    `" https://user:token@example.invalid/x.git"` therefore passed every check
    and was persisted VERBATIM into `project_repositories.remote_url`, which
    the repository endpoints read back to every authenticated caller — the
    exact disclosure the refusal exists to prevent (Copilot review of
    openDox-code#26).
    """
    smuggled = (
        " https://someone:ghp_supersecret@example.invalid/x.git",
        "https://someone:ghp_supersecret@example.invalid/x.git ",
        "\thttps://someone:ghp_supersecret@example.invalid/x.git",
        "\n https://example.invalid/x.git?token=ghp_supersecret",
    )
    for url in smuggled:
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.refuse_credential_bearing_remote(url)
        # The refusal never echoes the value it refused.
        assert "ghp_supersecret" not in str(caught.value), url

    # And a clean URL with surrounding whitespace is refused too, by name,
    # rather than being silently trimmed into a row the caller never sent.
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.refuse_credential_bearing_remote(" https://example.invalid/x.git")
    assert "whitespace" in str(caught.value)


def test_a_location_that_cannot_be_read_is_a_refusal_and_not_a_500(
        tmp_path: Path) -> None:
    """`iterdir()` on a stat-able, unreadable directory raises `PermissionError`.

    The emptiness check sat outside every `try`, so that escaped to the API as
    a 500 instead of the named `RepositoryActRefused` this act promises for
    every reason it will not create a repository (Copilot review of
    openDox-code#26).
    """
    import os

    if os.geteuid() == 0:
        pytest.skip("running as root: a mode-less directory is still readable")
    location = tmp_path / "unreadable"
    location.mkdir(mode=0o300)          # --wx: stat yes, list no
    try:
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.refuse_unusable_location(location)
        assert "could not be inspected" in str(caught.value)
        assert "PermissionError" in str(caught.value)
    finally:
        location.chmod(0o700)


def test_a_push_refuses_when_git_and_the_map_name_different_destinations(
        store, project, project_repository_root: Path) -> None:
    """The map is the destination of record, and git is asked whether it agrees.

    The push sent to whatever `origin` happened to be and never looked, so a
    manual `git remote set-url`, or an `attach_remote` interrupted between its
    two halves, could send the corpus one place while the map and the success
    response named another (Copilot review of openDox-code#26).
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    act.attach_remote(store, project_id=project.id,
                      remote_url="https://example.invalid/of-record.git")

    # Somebody moves the remote behind the map's back.
    _git(created.location, "remote", "set-url", act.REMOTE_NAME,
         "https://elsewhere.invalid/not-of-record.git")
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    message = str(caught.value)
    assert "of-record.git" in message and "not-of-record.git" in message
    assert "Nothing is pushed" in message

    # Re-attaching is the act that settles it, and it does.
    act.attach_remote(store, project_id=project.id,
                      remote_url="https://example.invalid/of-record.git")
    assert _git(created.location, "remote", "get-url", act.REMOTE_NAME) == (
        "https://example.invalid/of-record.git")

    # The other half of the same rule: the map names a remote git has not got.
    _git(created.location, "remote", "remove", act.REMOTE_NAME)
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert "has no 'origin'" in str(caught.value)


def test_a_repository_created_on_another_branch_is_pushable(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`create_repository` accepts any branch; the push hard-coded `main`.

    A repository created with `branch="master"` was servable by the adapter and
    unpushable through every surface, because neither the API nor the CLI
    exposes a branch (Copilot review of openDox-code#26). The push now asks the
    repository's own HEAD, which is the same question `_served_ref` asks for
    the write path.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR,
                                    branch="master")
    assert _git(created.location, "symbolic-ref", "HEAD") == "refs/heads/master"

    # A real destination, so the push is measured and not merely attempted.
    destination = tmp_path / "governed-factory.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(destination)],
                   check=True)
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))
    assert act.push_to_remote(store, project_id=project.id) == str(destination)
    assert _git(destination, "rev-parse", "refs/heads/master") == (
        created.initial_commit)


def test_the_api_never_hands_back_a_legacy_rows_credential(
        client_with_repositories, mint_token, database) -> None:
    """A row written before the credential rule can still carry one.

    This PR keeps such a row working on purpose, so a SUCCESSFUL push of one
    was the single path that returned the embedded credential verbatim while
    the CLI and every failure path redacted it — and the map read-back handed
    it to every member of the project besides (Copilot review of
    openDox-code#26).
    """
    token = mint_token(subject="api-legacy-owner")
    project = client_with_repositories.post(
        "/api/v1/projects", json={"slug": "legacy", "title": "Legacy"},
        headers=_auth(token)).json()
    created = client_with_repositories.post(
        f"/api/v1/projects/{project['id']}/repository", headers=_auth(token))
    assert created.status_code == 201, created.text
    location = Path(created.json()["location"])

    legacy = "https://someone:ghp_supersecret@example.invalid/x.git"
    with database.transaction() as conn:
        identity.CoordinationStore(conn).attach_remote(
            project_id=project["id"], remote_url=legacy)
    _git(location, "remote", "add", act.REMOTE_NAME, legacy)

    mapped = client_with_repositories.get(
        f"/api/v1/project-repositories/{project['id']}", headers=_auth(token))
    assert mapped.status_code == 200, mapped.text
    assert "ghp_supersecret" not in mapped.text
    assert mapped.json()["remote_url"] == "<redacted-url>"

    pushed = client_with_repositories.post(
        f"/api/v1/projects/{project['id']}/repository/push",
        headers=_auth(token))
    # The remote is unreachable, so this is the refusal path — and it, too,
    # says nothing it should not.
    assert "ghp_supersecret" not in pushed.text


# -- Copilot's fifth round on #26 --------------------------------------------


def test_a_push_url_behind_the_maps_back_is_refused(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`git push` does not use the URL `git remote get-url` reports.

    `remote.origin.pushurl` wins when it is set, so the fetch-URL comparison
    passed while the corpus went somewhere else entirely and the API reported
    the mapped URL (Copilot review of openDox-code#26, round 5). The check now
    asks git where a push WOULD go — `get-url --push`, git's own answer,
    rather than a reimplementation of the fallback.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "of-record.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(destination)],
                   check=True)
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))

    elsewhere = tmp_path / "somewhere-else.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(elsewhere)],
                   check=True)
    # The fetch URL still agrees with the map; only the push URL is moved.
    _git(created.location, "remote", "set-url", "--push", act.REMOTE_NAME,
         str(elsewhere))
    assert _git(created.location, "remote", "get-url",
                act.REMOTE_NAME) == str(destination)

    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    message = str(caught.value)
    assert "would push to" in message
    assert "somewhere-else.git" in message and "of-record.git" in message
    assert "Nothing is pushed" in message
    # And nothing arrived at either end.
    for bare in (destination, elsewhere):
        assert subprocess.run(["git", "--git-dir", str(bare), "rev-parse",
                               "--verify", "--quiet", "refs/heads/main"],
                              capture_output=True).returncode != 0, bare


def test_the_push_takes_no_branch_override_at_all(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`push_to_remote(..., branch="other")` pushed a history the project is not.

    Nothing exposed the parameter — the API and the CLI both call with a
    project id alone — but it defaulted to HEAD's branch rather than requiring
    it, so a caller could push `refs/heads/other` while HEAD, `LocalGitCorpus`
    and every read served `main`, and get a success back (Copilot review of
    openDox-code#26, round 5). It is gone, for the same reason `remote_name`
    is: a push this act cannot record is not a push it can make.
    """
    import inspect

    assert "branch" not in inspect.signature(act.push_to_remote).parameters

    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    # A second branch with its own commit, which is what the override could
    # have sent in place of the served one.
    _git(created.location, "branch", "other", created.initial_commit)
    destination = tmp_path / "governed.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(destination)],
                   check=True)
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))
    with pytest.raises(TypeError):
        act.push_to_remote(store, project_id=project.id,   # type: ignore[call-arg]
                           branch="other")
    act.push_to_remote(store, project_id=project.id)
    assert _git(destination, "rev-parse", "refs/heads/main") == (
        created.initial_commit)
    assert subprocess.run(["git", "--git-dir", str(destination), "rev-parse",
                           "--verify", "--quiet", "refs/heads/other"],
                          capture_output=True).returncode != 0, (
        "the push sent a branch the repository does not serve")


def test_a_second_push_url_is_refused_even_when_the_first_one_matches(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`git remote get-url --push` prints ONE url; git permits several.

    A push is sent to EVERY configured `remote.origin.pushurl`, so an extra one
    left the first matching the map while the corpus also went to an
    unrecorded destination (Copilot review of openDox-code#26, round 6). The
    check asks for `--all` and compares the whole list, so a second URL can
    never equal the single mapped one and names itself in the refusal.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "of-record.git"
    elsewhere = tmp_path / "unrecorded.git"
    for bare in (destination, elsewhere):
        subprocess.run(["git", "init", "--quiet", "--bare", str(bare)],
                       check=True)
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))
    # The mapped URL FIRST, so a check that reads only the first one passes.
    _git(created.location, "remote", "set-url", "--push", act.REMOTE_NAME,
         str(destination))
    _git(created.location, "remote", "set-url", "--push", "--add",
         act.REMOTE_NAME, str(elsewhere))

    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    message = str(caught.value)
    assert "unrecorded.git" in message and "of-record.git" in message
    assert "Nothing is pushed" in message
    for bare in (destination, elsewhere):
        assert subprocess.run(["git", "--git-dir", str(bare), "rev-parse",
                               "--verify", "--quiet", "refs/heads/main"],
                              capture_output=True).returncode != 0, bare


def test_attaching_clears_a_stale_push_url_so_the_repair_repairs(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`git remote set-url` writes the FETCH url alone.

    A repository carrying a legacy or hand-added `remote.origin.pushurl` — the
    very state `push_to_remote` refuses — kept it through `attach_remote`, so
    re-attaching could not repair the destination of record, which is the one
    repair this act offers (Copilot review of openDox-code#26, round 6).
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "of-record.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(destination)],
                   check=True)
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))
    _git(created.location, "remote", "set-url", "--push", act.REMOTE_NAME,
         str(tmp_path / "somewhere-else.git"))
    with pytest.raises(act.RepositoryActRefused):
        act.push_to_remote(store, project_id=project.id)

    # The repair this act offers, re-run — and it now repairs.
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))
    assert act.push_to_remote(store, project_id=project.id) == str(destination)
    assert _git(destination, "rev-parse", "refs/heads/main") == (
        created.initial_commit)


def test_the_push_locks_the_map_row_it_checked(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """The check and the push are ONE act, or the destination can move.

    `push_to_remote` compared the map with git's configured remote and then
    pushed; a concurrent `attach_remote` between the two sent the corpus to the
    newly attached destination while the response named the stale one (Copilot
    review of openDox-code#26, round 6). Both acts take `select … for update`
    on the map row, inside the caller's transaction.
    """
    import inspect

    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    source = inspect.getsource(act.push_to_remote)
    assert "for_update=True" in source, (
        "the push reads the map row without locking it")
    assert "for_update=True" in inspect.getsource(act.attach_remote), (
        "the attach does not take the lock the push waits on")

    # And the store really emits the lock, rather than accepting the argument.
    statements: list[str] = []
    real_execute = type(store._conn).execute

    def _record(self, statement, *args, **kwargs):
        statements.append(str(statement))
        return real_execute(self, statement, *args, **kwargs)

    try:
        type(store._conn).execute = _record
        store.repository_for_project(project.id, for_update=True)
    finally:
        type(store._conn).execute = real_execute
    assert any("for update" in s for s in statements), statements


# -- Copilot's tenth round on #26 --------------------------------------------


def test_a_bracketed_ipv6_scp_remote_is_refused_like_any_other_userinfo(
) -> None:
    """A PIN, not a fix: this round's finding here is measurably wrong.

    The review reports that the SCP detector "excludes `:` from the host, so a
    valid bracketed-IPv6 SCP remote such as `user@[::1]:repo` bypasses the
    userinfo refusal". Measured on the landed pattern, it does not: the host
    class matches the `[`, and the very next character is the `:` the SCP form
    requires, so the match succeeds and the URL is refused. Every bracketed
    IPv6 literal opens with a hex group or a colon, so no shape of it can avoid
    the pattern — and the redacting half matches for the same reason
    (`test_a_bracketed_ipv6_scp_remote_is_redacted_like_any_other_userinfo`).

    No code changed for that finding. This test is here because a property held
    BY LUCK is one the next edit can lose.
    """
    for url in ("someone@[::1]:repo.git",
                "git@[2001:db8::1]:opensoft/openDox.git",
                "user@[fe80::1]:r.git"):
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.refuse_credential_bearing_remote(url)
        assert "user information" in str(caught.value), url
        assert url not in str(caught.value), url


def test_a_space_inside_the_url_no_longer_hides_a_credential_parameter(
) -> None:
    """`urlsplit` accepts a raw space inside a URL; the parameter class did not.

    `https://host/x? token=ghp_secret` parses as a query carrying `token`, and
    the shared predicate saw no parameter at all — so the value was stored in
    `remote_url` and read back to every authenticated caller (Copilot review of
    openDox-code#26, round 10). The patterns step over spaces and tabs around a
    name now.
    """
    for url in ("https://example.invalid/x.git? token=ghp_supersecret",
                "https://example.invalid/x.git?token =ghp_supersecret",
                "https://example.invalid/x.git?a=1& access_token=ghp_secret"):
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.refuse_credential_bearing_remote(url)
        assert "query or fragment parameter" in str(caught.value), url
        assert "ghp_" not in str(caught.value), url


def test_a_control_character_is_refused_and_a_plain_space_is_not() -> None:
    """A newline in a remote URL forges a second line in `.git/config`.

    A tab or a carriage return hides the rest of the value from every
    line-oriented reader of the row. None of them can appear in a URL that was
    percent-encoded, so they are refused — while a SPACE is not, because the
    one destination this act deliberately leaves unconstrained is a local path
    (RULING C3's "a push, not a migration" in a single-node install), and
    `/srv/my repos/x.git` is a legal one.
    """
    for url in ("https://example.invalid/x.git\nurl = https://evil.invalid/y",
                "https://example.invalid/x.git\ttoken=ghp_supersecret",
                "https://example.invalid/x.git\rmore"):
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.refuse_credential_bearing_remote(url)
        assert "control character" in str(caught.value), url
        assert "ghp_" not in str(caught.value), url

    # A local path with a space in it is still attachable.
    act.refuse_credential_bearing_remote("/srv/my repos/project.git")


def test_a_remote_url_longer_than_the_bound_is_refused_unread() -> None:
    """The credential predicate decodes each name to a fixed point.

    That is quadratic in the name, and `remote_url` is caller-controlled, so a
    nested `%2525…` chain is work an attacker chooses for this process (Copilot
    review of openDox-code#26, round 10, suppressed). The bound is stated where
    the value enters.
    """
    long_url = "https://example.invalid/x.git?a=" + ("%25" * 4000)
    assert len(long_url) > act.MAX_REMOTE_URL_CHARS
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.refuse_credential_bearing_remote(long_url)
    assert str(act.MAX_REMOTE_URL_CHARS) in str(caught.value)
    assert "%25" not in str(caught.value)
    # And a URL at the bound is still measured rather than refused by length.
    act.refuse_credential_bearing_remote(
        "https://example.invalid/" + "a" * (act.MAX_REMOTE_URL_CHARS - 25))


def test_a_transport_that_runs_a_command_is_refused_where_it_is_stored(
        store, project, project_repository_root: Path) -> None:
    """`ext::<command>` is a git transport that EXECUTES its argument.

    In the pushing process — this runtime's own. An owner attaching one would
    be choosing a command for a server to run, which is not a destination the
    map can mean (Copilot review of openDox-code#26, round 10).
    """
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    for url in ("ext::sh -c whoami", "EXT::sh -c whoami", "fd::7/repo"):
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.attach_remote(store, project_id=project.id, remote_url=url)
        assert "runs a command" in str(caught.value), url
    # And the map is untouched by a refused attach.
    assert store.repository_for_project(project.id).remote_url is None


def test_a_legacy_command_transport_row_is_not_executed_by_the_push(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """The refusal above covers what is STORED; this covers what is PUSHED.

    A row written before that rule — or by a future caller of the store — still
    reaches the push, and git's `ext::` transport is gated by a CONFIG VALUE
    the host sets. Measured on git 2.43.0: with `protocol.ext.allow=user` in
    the repository's own config the helper is executed, and a command-line
    `-c protocol.ext.allow=never` refuses it (Copilot review of
    openDox-code#26, round 10). The push carries the policy now instead of
    assuming it of the machine.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    marker = tmp_path / "EXECUTED"
    helper = tmp_path / "remote-helper.sh"
    helper.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
    helper.chmod(0o755)
    hostile = f"ext::{helper}"

    # A row that predates the refusal, written through the store directly.
    store.attach_remote(project_id=project.id, remote_url=hostile)
    _git(created.location, "remote", "add", act.REMOTE_NAME, hostile)
    # The ambient policy this runtime must not depend on.
    _git(created.location, "config", "protocol.ext.allow", "user")

    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert "ext" in str(caught.value)
    assert not marker.exists(), (
        "the ext:: transport was executed by this runtime's own push")


def test_attach_repairs_a_remote_that_carries_two_fetch_urls(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`git remote set-url` cannot write a remote that has several urls.

    Measured on git 2.43.0: it exits non-zero with "could not set
    'remote.origin.url': has multiple values". So a repository in that state —
    a legacy remote, a hand-edited config — could not be repaired by the one
    repair this act offers, while every push was refused because
    `get-url --push --all` returned two destinations (Copilot review of
    openDox-code#26, round 10, suppressed twice).
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "of-record.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "--initial-branch=main",
                    str(destination)], check=True)
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))
    # The state: somebody added a second fetch URL by hand.
    _git(created.location, "config", "--add", f"remote.{act.REMOTE_NAME}.url",
         str(tmp_path / "somewhere-else.git"))
    with pytest.raises(act.RepositoryActRefused):
        act.push_to_remote(store, project_id=project.id)

    # The repair this act offers, re-run — and it now repairs.
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))
    assert _git(created.location, "config", "--get-all",
                f"remote.{act.REMOTE_NAME}.url") == str(destination)
    assert act.push_to_remote(store, project_id=project.id) == str(destination)


def test_a_pushurl_that_cannot_be_cleared_fails_the_attach(
        store, project, project_repository_root: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Only ONE non-zero status means "there was nothing to unset".

    This ignored every failure, so a locked config, a read-only file or a
    malformed section left a stale `pushurl` in place while the map row
    committed and the attach reported success — after which the next push goes
    to the wrong destination or is refused, which is the state that line exists
    to clear (Copilot review of openDox-code#26, round 10, suppressed twice).
    """
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "of-record.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(destination)],
                   check=True)
    real_run = lga.GitRunner.run

    def _failing_unset(self, *args: str, **kwargs):
        if args[:2] == ("config", "--unset-all"):
            return subprocess.CompletedProcess(
                ["git", *args], returncode=4, stdout=b"",
                stderr=b"error: could not lock config file .git/config")
        return real_run(self, *args, **kwargs)

    monkeypatch.setattr(lga.GitRunner, "run", _failing_unset)
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.attach_remote(store, project_id=project.id,
                          remote_url=str(destination))
    assert "could not be attached" in str(caught.value)
    # And the `5` that means "no such key" is still not a failure.
    monkeypatch.undo()
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))
