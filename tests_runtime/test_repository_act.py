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


def test_the_act_on_a_project_that_does_not_exist_is_a_404(
        client_with_repositories, mint_token) -> None:
    client = client_with_repositories
    token = mint_token(subject="api-owner-4")
    response = client.post("/api/v1/projects/no-such-project/repository",
                           headers=_auth(token))
    assert response.status_code == 404


# -- the review round's own assertions (Copilot review of openDox-code#26) ---


def test_the_map_records_an_absolute_location(store, project,
                                              tmp_path: Path) -> None:
    """A relative root in the durable map resolves against whatever working
    directory the next process happens to have."""
    relative = Path("var") / "projects"
    created = act.create_repository(store, project_id=project.id,
                                    root=relative, actor=ACTOR)
    try:
        assert Path(created.row.location).is_absolute()
        assert created.location.is_absolute()
    finally:
        import shutil
        shutil.rmtree(created.location.parent.parent, ignore_errors=True)


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
