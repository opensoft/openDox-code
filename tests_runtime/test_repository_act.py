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

import dataclasses
import os
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


#: The same hermetic environment `test_local_git_adapter.py` gives every `git`
#: it runs, and for the same reason: a case that takes its committer identity
#: (or any other setting) from the developer's GLOBAL config passes on a
#: workstation and fails on a runner, which has none. Both files point the
#: config files at nothing and supply an identity, so the two see one git.
_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "openDox tests",
    "GIT_AUTHOR_EMAIL": "tests@opendox.invalid",
    "GIT_COMMITTER_NAME": "openDox tests",
    "GIT_COMMITTER_EMAIL": "tests@opendox.invalid",
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True, env=_GIT_ENV).stdout.strip()


#: THE PROCESS'S OWN ENVIRONMENT, and not only `_git`'s. The mapping above is
#: passed to the `subprocess.run` in `_git`, which is this file's DIRECT use of
#: git — but the code under test runs git through `GitRunner`, which inherits
#: `os.environ` and builds its own environment from it. So the hermetic claim
#: was true of the assertions and false of the act they assert about: a
#: developer's global `url.<base>.insteadOf`, `init.templateDir` or
#: `protocol.*.allow` still reached every repository this suite creates,
#: configures and pushes (Copilot review of openDox-code#26, round 14,
#: suppressed). `monkeypatch.setenv` puts the same settings where the runner
#: will find them, and `GitRunner`'s sanitizer keeps them: it strips the
#: repository-SELECTING variables (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_CONFIG`…)
#: and never `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM`, which are the two that
#: make a workstation and a runner see one git.
@pytest.fixture(autouse=True)
def _hermetic_git_for_the_whole_process(
        monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _GIT_ENV.items():
        if name.startswith("GIT_"):
            monkeypatch.setenv(name, value)


def _legacy_remote_row(store, project_id: str, remote_url: str) -> None:
    """A map row written AROUND the store's own writers, which is what legacy means.

    These cases need a row carrying a value the act — and, since § 3.5's own
    batch, `identity.CoordinationStore` itself — refuses to write: a credential
    in the URL, a command transport, a joined pair, a URL `urlsplit` cannot
    read. `store.attach_remote` used to be the way to make one, and it is
    exactly the door that is now shut, so the row goes in the way a real legacy
    row got there: an UPDATE against the table, from a build or a `psql`
    session that had no such rule. The file already writes a legacy `location`
    this way; this is the same idiom for `remote_url`.
    """
    store._conn.execute(
        "update project_repositories set remote_url = %s where project_id = %s",
        (remote_url, project_id))


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
    # THE GIT HALF, which is where the invocation lives: round 16 bound the
    # act to an open directory, so `push_to_remote` now delegates to
    # `_push_to_remote_with` on a runner it holds.
    source = inspect.getsource(act._push_to_remote_with)
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
    _legacy_remote_row(store, project.id, legacy)
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


def test_the_api_never_hands_back_a_legacy_row_s_credential(
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
    # AROUND the store, which is what a legacy row is: § 3.5's batch made
    # `attach_remote` refuse this value, and the point of these cases is the
    # row that got in before any such rule existed.
    with database.transaction() as conn:
        conn.execute(
            "update project_repositories set remote_url = %s "
            "where project_id = %s", (legacy, project["id"]))
    _git(location, "remote", "add", act.REMOTE_NAME, legacy)

    mapped = client_with_repositories.get(
        f"/api/v1/project-repositories/{project['id']}", headers=_auth(token))
    assert mapped.status_code == 200, mapped.text
    assert "ghp_supersecret" not in mapped.text
    # THE SHAPE CHANGED WITH THE MERGE OF § 3.5, deliberately. This boundary
    # used to call `local_git_adapter.redact_remote_url`, which replaces the
    # WHOLE value with `<redacted-url>` — the right trade for git's stderr,
    # where over-redacting is safe. § 3.5 pairs a refusal at the store with
    # `config.redacted_remote_url`, which removes the secret and nothing else,
    # so an operator can still see WHICH endpoint the row names and an ordinary
    # `ssh://git@host/…` comes back exactly as stored. The secret is gone
    # either way, which is the assertion above.
    assert mapped.json()["remote_url"] == "https://<redacted>@example.invalid/x.git"

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
    # THE COUNT IS THE FINDING, and the configured values are NOT echoed:
    # `get-url --push --all` is read by LINE, so a stored URL holding a
    # newline arrives here as fragments and a redactor cannot see userinfo
    # that has been cut in half (Copilot review of openDox-code#26, round 30).
    # The map's own value is named, redacted as one value, and it is the one
    # an operator has to change.
    assert "2 destinations" in message, message
    assert "of-record.git" in message, message
    assert "unrecorded.git" not in message, (
        "a configured push URL is echoed; a newline in a legacy row makes "
        "that a leak the redactor cannot catch")
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
    _legacy_remote_row(store, project.id, hostile)
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
    #
    # ONLY THE RUNNER IS RESTORED. `monkeypatch.undo()` here reverted EVERY
    # patch this test holds — including the autouse fixture's
    # `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` and identity — so the second
    # attach ran under whatever git configuration the machine has, which is the
    # very asymmetry this module's `_GIT_ENV` exists to remove (Copilot review
    # of openDox-code#26, round 16, suppressed).
    monkeypatch.setattr(lga.GitRunner, "run", real_run)
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))


# -- Copilot's twelfth round on #26 ------------------------------------------


def test_any_remote_helper_spelling_is_refused_not_only_ext_and_fd(
        store, project, project_repository_root: Path) -> None:
    """`<name>::<address>` makes git resolve `git-remote-<name>` from `PATH`.

    So naming `ext` and `fd` was the narrow reading of a general mechanism: an
    installed helper — one the image ships, one a sibling package left there —
    is reachable through any spelling, and `protocol.ext.allow` governs `ext`
    alone (Copilot review of openDox-code#26, round 12).
    """
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    for url in ("evil::anything", "testgit::/tmp/x", "Helper::sh -c whoami"):
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.attach_remote(store, project_id=project.id, remote_url=url)
        assert "runs a command" in str(caught.value), url
    # A SINGLE colon is not this form and is unaffected: a URL, an SCP remote
    # and a Windows-style path all still attach.
    for url in ("https://example.invalid/x.git", "git@example.invalid:x.git",
                "/srv/projects/x.git"):
        act.refuse_command_executing_remote(url)


def test_a_legacy_helper_row_is_refused_before_the_push_runs_it(
        store, project, project_repository_root: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The attach rule cannot reach a row that predates it; this does.

    `-c protocol.ext.allow=never` covers `ext` and says nothing about
    `git-remote-evil`, so a legacy `evil::…` row still handed `git push` a
    helper to run (Copilot review of openDox-code#26, round 12). The row is
    asked the same question `attach_remote` asks, before anything is pushed.

    A REAL HELPER IS PLANTED ON `PATH` for this, so the old shape's failure is
    the helper RUNNING rather than an assertion about intent.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "HELPER-RAN"
    helper = bin_dir / "git-remote-evil"
    helper.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
    helper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    hostile = "evil::anything"
    _legacy_remote_row(store, project.id, hostile)
    _git(created.location, "remote", "add", act.REMOTE_NAME, hostile)

    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert "runs a command" in str(caught.value)
    assert not marker.exists(), (
        "the remote helper was executed by this runtime's own push")


# -- Copilot's twelfth round on #26, continued -------------------------------


def test_a_remote_carrying_only_a_push_url_is_still_repairable(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """The one repair this act offers has to reach the state that needs it.

    A repository carrying `remote.origin.pushurl` and NO `remote.origin.url` —
    legacy, or hand-edited — is exactly the state `push_to_remote` refuses, so
    `attach_remote` must be able to settle it (Copilot review of
    openDox-code#26, round 12, suppressed).

    THE FINDING'S PREMISE IS VERSION-DEPENDENT, AND IT IS MEASURED HERE RATHER
    THAN ASSUMED: on git 2.43.0 `git remote get-url origin` in that state exits
    0 and prints the literal `origin` (`git remote -v` shows an empty fetch
    URL), so the repair branch was already taken. A git that exits non-zero
    instead would have fallen through to `remote add`, which fails ("remote
    origin already exists"). The act now asks the CONFIG SECTION, so the repair
    does not depend on which of the two answers the local git gives — and this
    case asserts the OUTCOME, which is the same either way.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    stale = tmp_path / "stale.git"
    _git(created.location, "config", "remote.origin.pushurl", str(stale))
    assert _git(created.location, "config", "--get-regexp",
                "^remote[.]origin[.]"), "the premise is gone"

    destination = tmp_path / "destination.git"
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))

    assert _git(created.location, "remote", "get-url",
                "origin") == str(destination)
    assert _git(created.location, "remote", "get-url", "--push", "--all",
                "origin") == str(destination), (
        "the stale push URL survived the one repair this act offers")


def test_a_push_destination_rewritten_by_config_is_refused_not_followed(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`insteadOf` / `pushInsteadOf`, and the finding about them is FALSE here.

    The review's claim was that a rewrite can make the INSPECTED values equal
    the map row while `git push` sends the corpus somewhere else. Measured on
    git 2.43.0, the opposite is true — `get-url` and `get-url --push` are
    themselves rewritten, so a rewrite makes them DIFFER from the map and this
    act refuses:

        remote.origin.url            = <destination>
        url.<other>.insteadOf        = <destination's prefix>
        git remote get-url origin    -> <other>          (rewritten)
        git remote get-url --push --all origin -> <other> (rewritten)
        git push origin …            -> "failed to push some refs to '<other>'"

    The last two lines are the same value, which is the whole point: what this
    act inspects IS where the push would go. This case pins that, because a
    property held by git's behaviour is one a later git could change.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "destination.git"
    subprocess.run(["git", "init", "-q", "--bare", str(destination)],
                   check=True, capture_output=True, env=_GIT_ENV)
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))
    # A push with no rewrite in force is the control: it works.
    assert act.push_to_remote(store, project_id=project.id) == str(destination)

    elsewhere = tmp_path / "elsewhere.git"
    subprocess.run(["git", "init", "-q", "--bare", str(elsewhere)],
                   check=True, capture_output=True, env=_GIT_ENV)
    _git(created.location, "config", f"url.{elsewhere}.pushInsteadOf",
         str(destination))
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert "would push to" in str(caught.value)
    assert str(elsewhere) in str(caught.value), (
        "the refusal does not name the destination the rewrite would have used")
    # AND NOTHING WENT THERE.
    assert subprocess.run(["git", "-C", str(elsewhere), "rev-parse",
                           "--verify", "HEAD"], capture_output=True,
                          env=_GIT_ENV).returncode != 0


def test_the_helper_transport_refusal_names_the_helper_it_refuses(
) -> None:
    """`evil::anything` was refused with a message about `ext::` and `fd::`.

    The predicate covers every `<name>::<address>` form — round 12's own fix —
    and the message named the two spellings git ships, so an owner attaching
    `evil::anything` got a diagnosis about a transport they had not used
    (Copilot review of openDox-code#26, round 12, suppressed twice).
    """
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.refuse_command_executing_remote("evil::anything")
    message = str(caught.value)
    assert "`evil::`" in message and "git-remote-evil" in message, message
    assert "<name>::<address>" in message, (
        "the message does not describe the general form the predicate matches")


def test_a_pre_push_hook_in_a_project_repository_does_not_run(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`git push` runs the LOCAL `pre-push` hook before it contacts the remote.

    The repositories this service manages are WRITABLE by it, so a
    `hooks/pre-push` in one executed arbitrary code in the runtime's own
    process — and `protocol.ext.allow=never` says nothing about it, because a
    hook is not a transport (Copilot review of openDox-code#26, round 13).
    Every `git` this package runs now carries `-c core.hooksPath=/dev/null`.

    MEASURED BOTH WAYS on git 2.43.0 before it was written: a planted
    `hooks/pre-push` RAN on an ordinary push and did not run with the option,
    and the push succeeded either way. THE MARKER IS A REAL FILE the hook
    creates, so the old shape's failure is the hook RUNNING rather than an
    assertion about intent.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "destination.git"
    subprocess.run(["git", "init", "-q", "--bare", str(destination)],
                   check=True, capture_output=True, env=_GIT_ENV)
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))

    marker = tmp_path / "PRE-PUSH-RAN"
    hooks = created.location / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-push"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)

    assert act.push_to_remote(store, project_id=project.id) == str(destination)
    assert not marker.exists(), (
        "a hook in a project repository ran in the runtime's own process")
    # AND THE PUSH REALLY HAPPENED, so this is not a vacuous pass. The
    # destination's own HEAD is unborn (a bare `git init` names a branch it has
    # no commit on), so the ref the push moved is the one to ask about.
    assert _git(destination, "rev-parse", "--verify",
                f"refs/heads/{act.DEFAULT_BRANCH}") == _git(
                    created.location, "rev-parse", "HEAD")


def test_two_push_destinations_are_refused_by_COUNT_and_not_by_a_delimiter(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """A joined string is not an injective comparison.

    The effective push URLs were joined with `" and "` and compared against the
    map row, so a mapped local path that happens to LOOK like the join — `a and
    b` against push URLs `a` and `b` — satisfied the comparison while `git
    push` sent the corpus to two unrecorded destinations (Copilot review of
    openDox-code#26, round 13). The count is asked first now, and a delimiter
    decides nothing.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    first = tmp_path / "a"
    second = tmp_path / "b"
    joined = f"{first} and {second}"
    # The map records the string that USED to equal the join of the two.
    _legacy_remote_row(store, project.id, joined)
    _git(created.location, "config", "remote.origin.url", joined)
    _git(created.location, "config", "--add", "remote.origin.pushurl",
         str(first))
    _git(created.location, "config", "--add", "remote.origin.pushurl",
         str(second))

    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert "2 destinations" in str(caught.value), caught.value
    assert str(first) in str(caught.value) and str(second) in str(caught.value)


# -- Copilot's fourteenth round on #26 ---------------------------------------


def test_an_already_mapped_project_is_told_so_whatever_the_root_is_doing(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """The map is authoritative, and the ORDER is what makes that true.

    `repository_location` ran before the row was asked for, so a repeat create
    for an already-mapped project answered "the configured repository root
    could not be resolved" on a host whose `OPENDOX_PROJECT_REPOSITORY_ROOT`
    had since become unreadable and `ConflictError` on a host where it had not:
    the same act giving two answers about one durable fact (Copilot review of
    openDox-code#26, round 14). It is the `git_available` finding one step
    further up, and it gets the same fix.
    """
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    # A root nothing can resolve: a symlink pointing at itself. MEASURED on
    # python 3.12 — `Path.resolve()` raises `RuntimeError`, not `OSError`.
    broken = tmp_path / "loop"
    broken.symlink_to(broken)
    with pytest.raises(RuntimeError):
        broken.resolve()

    with pytest.raises(identity.ConflictError) as caught:
        act.create_repository(store, project_id=project.id, root=broken,
                              actor=ACTOR)
    assert project.id in str(caught.value)


def test_a_mapped_location_inside_another_repository_is_refused_by_the_acts(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`git -C` WALKS UP, and these are the acts that reconfigure and push.

    `_local_git_row` verified only the adapter LABEL, so a row whose directory
    had been removed — or written by hand as `checkout/subdir` — let
    `attach_remote` set `remote.origin.url` on the ENCLOSING checkout and
    `push_to_remote` push that checkout's branch to this project's remote
    (Copilot review of openDox-code#26, round 14). `LocalGitCorpus.resolve`
    already refuses exactly this shape (RULED 5714365086 Q-F3); the acts now
    ask the same question.
    """
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    enclosing = tmp_path / "enclosing"
    enclosing.mkdir()
    _git(enclosing, "init", "--initial-branch=main", ".")
    (enclosing / "a.md").write_text("a\n", encoding="utf-8")
    _git(enclosing, "add", "a.md")
    _git(enclosing, "commit", "-m", "first")
    inside = enclosing / "sub"
    inside.mkdir()
    # The legacy row this finding is about, written the way a legacy row is.
    store._conn.execute(
        "update project_repositories set location = %s where project_id = %s",
        (str(inside), project.id))

    with pytest.raises(act.RepositoryActRefused) as caught:
        act.attach_remote(store, project_id=project.id,
                          remote_url="https://example.invalid/r.git")
    assert "is INSIDE" in str(caught.value)
    assert str(enclosing.resolve()) in str(caught.value)
    # AND THE ENCLOSING REPOSITORY WAS NOT RECONFIGURED, which is the harm.
    configured = subprocess.run(
        ["git", "-C", str(enclosing), "config", "--get-regexp", "^remote\\."],
        capture_output=True, text=True, env=_GIT_ENV)
    assert configured.returncode == 1, configured.stdout
    assert configured.stdout == ""

    with pytest.raises(act.RepositoryActRefused):
        act.push_to_remote(store, project_id=project.id)


# -- Copilot's sixteenth round on #26 -----------------------------------------


def test_a_push_cannot_be_made_to_run_the_repository_s_own_receive_pack(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`git push` runs the DESTINATION's `receive-pack` — and for a local
    destination it runs it HERE, as a program the PUSHING repository's config
    chooses.

    `remote.<name>.receivepack` was therefore a command this runtime would
    execute on every push of a repository it manages — and these repositories
    are writable by the service and by whoever can reach their directory. It is
    the same class of defect as the `ext::` transport and the `pre-push` hook,
    and was covered by neither (Copilot review of openDox-code#26, round 16).
    `--receive-pack` on the command line outranks the config value.

    MEASURED BOTH WAYS by planting a real executable whose only job is to
    leave a file behind.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "governed.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(destination))
    marker = tmp_path / "receive-pack-ran"
    planted = tmp_path / "evil-receive-pack"
    planted.write_text(f"#!/bin/sh\ntouch {marker}\nexec git-receive-pack \"$@\"\n",
                       encoding="utf-8")
    planted.chmod(0o755)
    _git(created.location, "config", f"remote.{act.REMOTE_NAME}.receivepack",
         str(planted))

    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))
    assert act.push_to_remote(store, project_id=project.id) == str(destination)
    assert not marker.exists(), (
        "the repository's own `receivepack` config chose the program this "
        "push executed")

    # THE PREMISE, measured rather than assumed: without the pin, git runs it.
    subprocess.run(
        ["git", "-C", str(created.location), "push", act.REMOTE_NAME,
         f"refs/heads/{act.DEFAULT_BRANCH}:refs/heads/probe"],
        check=True, capture_output=True, env=_GIT_ENV)
    assert marker.exists(), (
        "this git does not honour `remote.<name>.receivepack` for a local "
        "destination, so the case above proves nothing on this platform")


def test_the_acts_are_bound_to_the_repository_they_verified(
        store, project, project_repository_root: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The root check proved a fact about a NAME and the git calls re-opened it.

    So a rename or a symlink swap between the check and the use could still
    send `remote set-url` or the push into another repository — the check and
    the use were two different objects (Copilot review of openDox-code#26,
    round 16). Both acts run on a runner bound to a descriptor opened
    `O_NOFOLLOW`, which is the binding `initialize_repository` already uses.

    The race is driven at the only moment it can happen: after the descriptor
    is open and before the act's first git call.
    """
    if not Path("/proc/self/fd").is_dir():
        pytest.skip("no /proc/self/fd on this platform, where the act "
                    "documents the pathname fallback as the weaker guarantee")
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    decoy = tmp_path / "decoy.git"
    subprocess.run(["git", "clone", "--bare", "-q", str(created.location),
                    str(decoy)], check=True, env=_GIT_ENV)
    real = act._attach_remote_with
    swapped = {"done": False}

    def _swap_then_attach(git, *args, **kwargs):
        if not swapped["done"]:
            swapped["done"] = True
            created.location.rename(tmp_path / "moved-aside")
            decoy.rename(created.location)
        return real(git, *args, **kwargs)

    monkeypatch.setattr(act, "_attach_remote_with", _swap_then_attach)
    act.attach_remote(store, project_id=project.id,
                      remote_url="https://example.invalid/r.git")
    assert swapped["done"], "the race this test drives did not happen"

    # The remote landed in the directory the act verified, not in the decoy
    # that took its name.
    moved = tmp_path / "moved-aside"
    assert _git(moved, "config", "--get",
                f"remote.{act.REMOTE_NAME}.url") == "https://example.invalid/r.git"
    configured = subprocess.run(
        ["git", "-C", str(created.location), "config", "--get",
         f"remote.{act.REMOTE_NAME}.url"],
        capture_output=True, text=True, env=_GIT_ENV)
    # The decoy is a CLONE, so it has an `origin` of its own — the clone
    # source. What it must not have is the URL this act attached.
    assert configured.stdout.strip() != "https://example.invalid/r.git", (
        "the decoy that took the name was reconfigured by this act")
    assert str(created.location) in configured.stdout, configured.stdout


# -- Copilot's twenty-first round on #26 --------------------------------------


def test_a_push_does_not_run_the_destinations_hooks(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """The client's `core.hooksPath` does not reach the RECEIVING process.

    `--receive-pack=git-receive-pack` pins the receiver's EXECUTABLE and says
    nothing about the destination's `pre-receive`, `update` or `post-receive`.
    For a local destination — which this act accepts by design — `git push`
    forks that receiver in this process tree, and it reads the DESTINATION's
    config and runs the destination's hooks here (Copilot review of
    openDox-code#26, round 21).

    MEASURED on git 2.43.0, three ways:

        plain push                                     pre-receive RAN
        `git -c core.hooksPath=/dev/null push`         pre-receive RAN
        the option carried on `--receive-pack`         did NOT run, push landed

    so the option has to travel as the RECEIVING command's own `-c`. The value
    is still one this act chooses rather than one the repository names, which
    is the property round 16 pinned and the case above still holds.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "governed.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(destination))
    marker = tmp_path / "pre-receive-ran"
    hook = destination / "hooks" / "pre-receive"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)

    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))
    assert act.push_to_remote(store, project_id=project.id) == str(destination)
    assert not marker.exists(), (
        "the destination's `pre-receive` ran in this process during the push")
    # And the push LANDED, so the guard did not buy the property with a
    # failure.
    assert subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{act.DEFAULT_BRANCH}"],
        capture_output=True, env=_GIT_ENV).returncode == 0

    # THE PREMISE, measured: this hook really does run on an ordinary push.
    subprocess.run(
        ["git", "-C", str(created.location), "push", act.REMOTE_NAME,
         f"refs/heads/{act.DEFAULT_BRANCH}:refs/heads/probe"],
        check=True, capture_output=True, env=_GIT_ENV)
    assert marker.exists(), (
        "this git does not run a destination `pre-receive` for a local push, "
        "so the case above proves nothing on this platform")


def test_a_repository_local_credential_helper_refuses_the_push(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """git runs a `!command` credential helper, and the repository can set one.

    `GIT_TERMINAL_PROMPT=0` and an empty `GIT_ASKPASS` refuse a PROMPT; they
    say nothing about a helper. These repositories are writable by this service
    and by whoever can reach their directory, so a `credential.helper` in the
    repository's OWN config was arbitrary code this runtime would execute
    during a push (Copilot review of openDox-code#26, round 21).

    MEASURED on git 2.43.0 against a local endpoint answering 401: a
    repository-local `credential.helper = !f() { touch MARKER; echo
    username=x; echo password=y; }; f` RAN during the push, and `-c
    credential.helper=` stopped it.

    REFUSED RATHER THAN OVERRIDDEN. `-c credential.helper=` resets the WHOLE
    list including the OPERATOR's global helper — the configuration this
    package deliberately preserves, and how a real destination authenticates at
    all. The value that cannot be trusted is the one in the repository this
    service writes to, so the check is scoped to that file.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "governed.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(destination))
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))

    marker = tmp_path / "helper-ran"
    _git(created.location, "config", "credential.helper",
         f"!f() {{ touch {marker}; echo username=x; echo password=y; }}; f")
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert "credential.helper" in str(caught.value), caught.value
    assert not marker.exists()
    # Nothing was pushed: the refusal is before the push, not after it.
    assert subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{act.DEFAULT_BRANCH}"],
        capture_output=True, env=_GIT_ENV).returncode != 0

    # AND THE OPERATOR'S OWN CONFIG IS NOT WHAT IS REFUSED: unset the local
    # one and the same push is made.
    _git(created.location, "config", "--unset-all", "credential.helper")
    assert act.push_to_remote(store, project_id=project.id) == str(destination)


def test_a_push_is_refused_when_it_names_a_repository_this_service_owns(
        store, project, project_repository_root: Path) -> None:
    """Nothing tied the destination to the project.

    `git push` to a local destination runs `git-receive-pack` against it with
    this service's own credentials, and this service owns every repository
    under `OPENDOX_PROJECT_REPOSITORY_ROOT` — so an owner could point `origin`
    at ANOTHER PROJECT'S repository and have the runtime write into it (Copilot
    review of openDox-code#26, round 21). The root is `location.parent` by
    construction, so this needs no new setting to know what it owns.

    Registered rather than implied: outside that root a local path is still
    accepted, because RULING C3 makes the move a push to a governed factory and
    an allowlist of governed destinations is a contract this act does not hold.
    What is closed is the one destination this service can reach with no
    operator credential at all: its own.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    sibling = Path(project_repository_root) / "another-project"
    _git(Path(project_repository_root), "init", "--bare",
         "--initial-branch=main", str(sibling))

    for aimed_at in (str(sibling), str(created.location),
                     str(project_repository_root),
                     "file://" + str(sibling)):
        act.attach_remote(store, project_id=project.id, remote_url=aimed_at)
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.push_to_remote(store, project_id=project.id)
        assert "this service owns" in str(caught.value), (aimed_at, caught.value)
    # And the sibling is untouched.
    assert subprocess.run(
        ["git", "-C", str(sibling), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{act.DEFAULT_BRANCH}"],
        capture_output=True, env=_GIT_ENV).returncode != 0


def test_a_project_id_that_is_not_one_path_component_is_refused(
        tmp_path: Path) -> None:
    """`/` is not the only separator a `Path` join honours.

    This module carries a Windows pathname fallback, so it says it is meant to
    run there — and on Windows `PureWindowsPath("C:/srv/projects") /
    "C:\\\\outside"` is `C:\\\\outside`: the root is discarded entirely, and
    `"..\\\\outside"` walks out of it (Copilot review of openDox-code#26, round
    21). MEASURED with `PureWindowsPath`, which is why the check asks that
    flavour on every host: the answer must not depend on where it runs.
    """
    # `"\\outside"` IS ROOT-RELATIVE AND NOT ABSOLUTE, which is why the
    # predicate asks `root` as well (Copilot review of openDox-code#26, round
    # 29). MEASURED on python 3.12: `PureWindowsPath(r"\\outside")` has
    # `drive=''`, `root='\\'` and `is_absolute() == False` — not absolute
    # because it names no drive — and `PureWindowsPath("C:/srv/projects") /
    # r"\\outside"` is `C:\\outside`, the configured parent discarded all the
    # same. A predicate reading only `drive`, `is_absolute()` and the part
    # count accepted it.
    for sent in ("..\\outside", "C:\\outside", "a\\b", "\\\\server\\share",
                 "\\outside", "\\"):
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.repository_location(tmp_path, sent)
        assert "single path component" in str(caught.value), (sent, caught.value)
        assert sent not in str(caught.value)
    # NOT an over-refusal.
    assert act.repository_location("/srv/projects", "9f2c-a-real-id") == \
        Path("/srv/projects/9f2c-a-real-id")


def test_a_repository_root_holding_a_nul_is_a_refusal_not_a_500(
) -> None:
    """`Path.resolve()` raises `ValueError`, which this handler did not catch.

    The same guard the project id already had, on the OTHER half of the join: a
    malformed `OPENDOX_PROJECT_REPOSITORY_ROOT` reached the API as a 500 in
    place of the named refusal this act promises for every reason it will not
    create a repository (Copilot review of openDox-code#26, round 21).
    MEASURED on python 3.12: `Path("/tmp/root\\x00x").expanduser().resolve()`
    raises `ValueError("embedded null byte")`.
    """
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.repository_location("/tmp/root\x00x", "a-project")
    assert "repository root could not be resolved" in str(caught.value)
    assert "ValueError" in str(caught.value)


def test_a_project_id_holding_a_control_character_is_refused(
        tmp_path: Path) -> None:
    """git terminates a pathname with a newline and `rev-parse` has no `-z`.

    So a location whose NAME contains one could not be read back
    unambiguously, and the root comparison every act makes is that read. The
    ambiguity is closed where the name is chosen rather than guessed at where
    it is parsed (Copilot review of openDox-code#26, round 22). It is the same
    predicate `refuse_command_executing_remote` uses.
    """
    for sent in ("project\nname", "project\rname", "a\x01b", "a‎b"):
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.repository_location(tmp_path, sent)
        assert "control character" in str(caught.value), (sent, caught.value)
        assert sent not in str(caught.value)
    # A SPACE IS NOT ONE, and must not become one: it is the legal id the case
    # above depends on.
    assert act.repository_location("/srv/projects", "project ") == \
        Path("/srv/projects/project ")


def test_the_owned_destination_check_reads_a_path_the_way_git_does(
        store, project, project_repository_root: Path) -> None:
    """Three ways past round 21's containment check, each a real one.

    * **`file://` is percent-decoded by git before it opens the path.** So
      `file:///…/projects%2Fanother.git` opens `…/projects/another.git` while
      an undecoded comparison sees ONE component and calls it a sibling outside
      the root. `%2e%2e` is the same trick for traversal.
    * **A Windows drive or a UNC share is a PATH, not `host:path`.** `C:` in
      the first component made `C:/…/sibling.git` look like scp syntax and
      skipped the check entirely — on the platform this module's own pathname
      fallback exists for.
    * **A relative destination is the REPOSITORY's, not this process's.** `git
      -C <location> push ../another.git` resolves against the mapped
      repository; the check resolved against whatever working directory the
      service happened to have.

    (Copilot review of openDox-code#26, round 23.) Each shape is driven
    through the real act here, and each is accepted against the previous head.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    sibling = Path(project_repository_root) / "another-project.git"
    _git(Path(project_repository_root), "init", "--bare",
         "--initial-branch=main", str(sibling))

    encoded = ("file://" + str(Path(project_repository_root)).rstrip("/")
               + "%2F" + sibling.name)
    traversal = ("file://" + str(created.location) + "/%2e%2e/"
                 + sibling.name)
    relative = "../" + sibling.name
    for aimed_at in (encoded, traversal, relative):
        act.attach_remote(store, project_id=project.id, remote_url=aimed_at)
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.push_to_remote(store, project_id=project.id)
        assert "this service owns" in str(caught.value), (aimed_at, caught.value)
    assert subprocess.run(
        ["git", "-C", str(sibling), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{act.DEFAULT_BRANCH}"],
        capture_output=True, env=_GIT_ENV).returncode != 0, (
        "one of those destinations was written to")

    # The classifier itself, on the shapes a POSIX host cannot exercise end to
    # end but a Windows one would — AND ON THE PLATFORM QUESTION, which is the
    # whole of round 29's finding here: the drive/UNC branch ran on every host,
    # so a POSIX runtime read `C:/repo.git` as a local path while git on POSIX
    # reads it as scp/SSH syntax. MEASURED on git 2.43.0 on Linux:
    #
    #   git ls-remote C:/repo.git
    #   ssh: Could not resolve hostname c: No address associated with hostname
    #
    # A destination classified local gets the hook-disabling `--receive-pack`,
    # which for a real remote host is this act DISABLING a governed factory's
    # own `pre-receive` — and an ownership comparison against a filesystem path
    # nothing would ever touch. So the branch is the platform's, and both
    # answers are asserted from here.
    classify = act._destination_as_a_local_path
    owned = str(Path(project_repository_root) / "p")
    for drive_shaped in ("C:/srv/projects/sibling.git", "C:\\srv\\x"):
        assert classify(drive_shaped, owned, windows=True) == \
            Path(drive_shaped), drive_shaped
        assert classify(drive_shaped, owned, windows=False) is None, (
            f"{drive_shaped!r} is an scp/SSH destination to the git this host "
            f"runs; classifying it local sends the hook guard to that remote")
    # A UNC SHARE IS THE OTHER ANSWER, and it is still git's. On Windows it is
    # an absolute path; on POSIX a backslash is an ordinary filename character,
    # so `\\server\share` is a RELATIVE path — which is what git does with it
    # too, and the own-root guard then refuses it for resolving under the root.
    unc = "\\\\server\\share"
    assert classify(unc, owned, windows=True) == Path(unc)
    assert classify(unc, owned, windows=False) == Path(owned) / unc
    # And a real host is still a host, on either platform.
    for host_shaped in ("https://host/x.git", "git@host:org/r.git"):
        assert classify(host_shaped, owned, windows=True) is None
        assert classify(host_shaped, owned, windows=False) is None
    # An absolute POSIX path that CONTAINS `://` is not a local path, and that
    # is git's own reading: `git push /tmp/x/../other://repo.git` answers
    # `fatal: protocol '/tmp/x/../other' is not supported`, so the destination
    # is unusable rather than unchecked (round 29's other half).
    assert classify("/srv/projects/other://repo.git", owned) is None
    assert classify("/srv/projects/other", owned) == Path("/srv/projects/other")


def test_the_hook_guard_is_for_a_local_destination_and_only_one(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`--receive-pack` is the command executed on the DESTINATION.

    Round 21 put `git -c core.hooksPath=<devnull> receive-pack` on every push,
    to stop a LOCAL destination's `pre-receive` running in this process. For a
    NETWORK destination that same option runs on the server, so it disabled a
    governed factory's own `pre-receive`/`update`/`post-receive` — the policy
    that destination exists to apply (Copilot review of openDox-code#26, round
    25). The guard and the sabotage are one string; what decides is whose
    process runs the hooks.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    local = tmp_path / "governed.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(local))

    assert act._receive_pack_for(str(local), created.location) == \
        "--receive-pack=git -c core.hooksPath=" + os.devnull + " receive-pack"
    assert act._receive_pack_for("file://" + str(local), created.location) == \
        "--receive-pack=git -c core.hooksPath=" + os.devnull + " receive-pack"
    for network in ("https://forge.test/org/repo.git",
                    "git@forge.test:org/repo.git",
                    "ssh://git@forge.test/org/repo.git"):
        assert act._receive_pack_for(network, created.location) == \
            "--receive-pack=git-receive-pack", network
    assert act._receive_pack_for(None, created.location) == \
        "--receive-pack=git-receive-pack"

    # And the local case still does what round 21 measured.
    marker = tmp_path / "pre-receive-ran"
    hook = local / "hooks" / "pre-receive"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    act.attach_remote(store, project_id=project.id, remote_url=str(local))
    assert act.push_to_remote(store, project_id=project.id) == str(local)
    assert not marker.exists()


def test_a_public_initialize_repository_refuses_a_nul_by_name(
        tmp_path: Path) -> None:
    """`Path.mkdir` raises `ValueError`, and this helper is PUBLIC.

    `create_repository` guards the project id, but a direct caller of
    `initialize_repository` does not come through it — and the preflight cannot
    catch a NUL either, because a path holding one reads as ABSENT. So the act
    promised a named refusal for every reason it will not create a repository
    and gave a raw `ValueError` (Copilot review of openDox-code#26, round 25).
    """
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.initialize_repository(tmp_path / "a\x00b", project_id="p",
                                  actor=ACTOR)
    assert "could not be created" in str(caught.value)
    assert "ValueError" in str(caught.value)
    assert sorted(tmp_path.iterdir()) == []
    # The premise, measured: the value this now translates does raise it.
    with pytest.raises(ValueError):
        (tmp_path / "a\x00b").mkdir()


def test_a_legacy_remote_that_cannot_be_parsed_is_a_refusal_not_a_500(
        store, project, project_repository_root: Path) -> None:
    """Only NEW attachments pass the validating path.

    A row written before `refuse_credential_bearing_remote` — or by any other
    caller of the store — can hold `file://[bad`, and `urlsplit` raises
    `ValueError` for it INSIDE the containment check, before that function's
    own translation. So the push leaked a raw exception and the API answered
    500 where this act promises a named refusal (Copilot review of
    openDox-code#26, round 25).
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    malformed = "file://[bad"
    # Written the way a LEGACY row is: through the store, not through the act.
    _legacy_remote_row(store, project.id, malformed)
    _git(created.location, "remote", "add", act.REMOTE_NAME, malformed)

    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert "ValueError" in str(caught.value) or "not a destination" in \
        str(caught.value), caught.value
    # The stored value is not echoed: this act has decided it cannot read it.
    assert malformed not in str(caught.value)


def test_a_platform_without_the_no_follow_walk_refuses_rather_than_degrades(
        store, project, project_repository_root: Path, monkeypatch) -> None:
    """No `O_DIRECTORY`, no `dir_fd` — no repository, and a named refusal.

    TWO FINDINGS IN ONE SHAPE (Copilot review of openDox-code#26, round 29).
    `open_no_follow_chain` is called unconditionally and uses `os.O_DIRECTORY`,
    which is NOT DEFINED on Windows: it raised `AttributeError` before any
    caller's refusal translation, so every read, write, attach and push failed
    with a traceback instead of an answer. And the creation path's non-`dir_fd`
    branch created the parents with `location.parent.mkdir(parents=True)` —
    which resolves the chain BY PATHNAME, so an EXISTING `<root>/link` pointing
    elsewhere is followed every time on every platform taking that branch. As
    the reviewer put it, "this is not just the documented race window".

    So the act refuses there. That is a policy change and this test is where it
    is stated: a platform without the primitives gets a named refusal and
    writes nothing, rather than a weaker guarantee that is not a guarantee.
    Both `deploy/` shapes and every CI runner are Linux.
    """
    monkeypatch.setattr(lga, "NO_FOLLOW_WALK_IS_AVAILABLE", False)
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.create_repository(store, project_id=project.id,
                              root=project_repository_root, actor=ACTOR)
    message = str(caught.value)
    # The caller's translation names the TYPE, which is how an operator learns
    # this is a platform answer and not a filesystem accident; the type's own
    # message says what is missing and that nothing was created.
    assert "PlatformCannotGuardPaths" in message, message
    assert isinstance(caught.value.__cause__, lga.PlatformCannotGuardPaths)
    cause = str(caught.value.__cause__)
    assert "dir_fd" in cause and "follow" in cause, cause
    assert not list(Path(project_repository_root).iterdir()), (
        "the refusal still wrote into the repository root")


def test_the_push_names_a_destination_it_holds_open(
        store, project, project_repository_root: Path, tmp_path: Path,
        monkeypatch) -> None:
    """The swap is driven BETWEEN the ownership check and the open.

    THE FINDING, TWICE (Copilot review of openDox-code#26, rounds 29 and 30).
    Round 29: the containment check resolved a permitted local destination and
    discarded the object; the push reopened the URL, so a symlink could be
    repointed in between. Round 30, on the fix: `_bound_local_destination`
    RESOLVED THE NAME AGAIN, so the same window simply moved — "if a symlink
    remote is outside the service root during
    `_refuse_a_destination_this_service_owns` and is repointed into a sibling
    before this helper runs, `resolved` becomes that sibling and the open
    descriptor is then pushed to it". And round 30 on the first version of THIS
    test: it repointed the link before `push_to_remote` started, so the
    ownership check refused immediately and the race was never exercised.

    So the swap happens where it has to: the real check runs, and the link is
    repointed the instant it returns. The containment question is asked again
    of the OPEN OBJECT — `/proc/self/fd/<n>` resolves, in this process, to the
    directory the handle refers to — so the answer cannot be stale by
    construction, and the refusal is what a repoint buys.

    Two runs, and the second is what makes the first mean anything: with no
    swap the push lands in the governed destination through that same handle.
    """
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    outside = tmp_path / "governed.git"
    subprocess.run(["git", "init", "-q", "--bare", str(outside)], check=True,
                   env=_GIT_ENV)
    sibling = Path(project_repository_root) / "another-project"
    subprocess.run(["git", "init", "-q", "--bare", str(sibling)], check=True,
                   env=_GIT_ENV)
    link = tmp_path / "destination"
    link.symlink_to(outside, target_is_directory=True)
    act.attach_remote(store, project_id=project.id, remote_url=str(link))

    # THE RACE, DRIVEN. The real check runs against the link pointing OUTSIDE
    # — it must pass — and the link is repointed at the sibling the moment it
    # returns, which is the window the finding describes.
    checked: list[str] = []
    real_check = act._refuse_a_destination_this_service_owns

    def _check_then_swap(destinations, location):
        # THE REAL CHECK'S ANSWER IS RETURNED, because it is one: the guard
        # reports the IDENTITY of each destination it approved, and the push
        # carries that to the open. A harness that dropped it would be testing
        # a push with the identity guard disabled.
        answer = real_check(destinations, location)
        checked.append(os.readlink(link))
        link.unlink()
        link.symlink_to(sibling, target_is_directory=True)
        return answer

    monkeypatch.setattr(act, "_refuse_a_destination_this_service_owns",
                        _check_then_swap)
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert checked == [str(outside)], (
        "the guard did not run against the destination outside the root, so "
        "this test measured a refusal it would have made anyway")
    # THE IDENTITY GUARD ANSWERS FIRST, and says the more precise thing: the
    # object opened is not the object checked. The containment re-check on the
    # open object stays as the backstop for a caller that does not carry the
    # identity, and the case below drives it directly.
    assert "another when it was opened" in str(caught.value), caught.value
    assert subprocess.run(
        ["git", "-C", str(sibling), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{act.DEFAULT_BRANCH}"],
        capture_output=True, env=_GIT_ENV).returncode != 0, (
        "the push reached the sibling the link was repointed at")

    # AND WITHOUT THE SWAP the push lands in the governed destination, through
    # the handle — so the refusal above is the race and not the mechanism.
    monkeypatch.setattr(act, "_refuse_a_destination_this_service_owns",
                        real_check)
    link.unlink()
    link.symlink_to(outside, target_is_directory=True)
    act.push_to_remote(store, project_id=project.id)
    assert subprocess.run(
        ["git", "-C", str(outside), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{act.DEFAULT_BRANCH}"],
        capture_output=True, env=_GIT_ENV).returncode == 0, (
        "the push did not reach the destination it was given")


def test_a_local_destination_that_cannot_be_resolved_is_refused(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """A containment check that cannot be made is a refusal, not a pass.

    THE FINDING (Copilot review of openDox-code#26, round 29): the loop's
    `continue` made the service-owned-destination guard FAIL OPEN — "if a local
    remote cannot be resolved because of a permission, symlink, or
    malformed-path error, the code proceeds to `git push` without proving that
    it is outside the service's repository root".

    A symlink loop is the reachable form: `Path.resolve()` raises
    `RuntimeError` for one on python 3.12 (measured by this act in round 20),
    which was one of the three types that `continue` swallowed.
    """
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    loop = tmp_path / "loop"
    other = tmp_path / "other"
    loop.symlink_to(other)
    other.symlink_to(loop)

    act.attach_remote(store, project_id=project.id, remote_url=str(loop))
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    message = str(caught.value)
    assert "cannot" in message and "prove" in message or "open" in message, (
        message)
    assert str(loop) not in message, "the refusal echoed the stored value"


# -- Copilot's rounds 31 and 32 on #26 ---------------------------------------


def test_a_remote_helper_planted_in_the_repositorys_own_config_is_refused(
        store, project, project_repository_root: Path, tmp_path: Path,
        monkeypatch) -> None:
    """`remote.<name>.vcs` names a program while the URL stays ordinary.

    The URL predicate looks for `::` and finds none; `-c protocol.ext.allow=
    never` covers the `ext` transport and says nothing about a helper chosen by
    config. MEASURED on git 2.43.0 with a `git-remote-evil` on PATH and a bare
    destination: `git config remote.origin.vcs evil` then `git push origin` ran
    `git-remote-evil origin <destination>` — and it ran with
    `-c protocol.ext.allow=never` passed as well (Copilot review of
    openDox-code#26, round 32).

    `--get-all` on a fixed key cannot see a key whose middle segment the
    repository chooses, so the scan asks `--get-regexp`.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "governed.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(destination))
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))

    planted = tmp_path / "bin"
    planted.mkdir()
    marker = tmp_path / "helper-ran"
    helper = planted / "git-remote-evil"
    helper.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
    helper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{planted}{os.pathsep}{os.environ['PATH']}")

    # THE SHAPE IT FORBIDS, RUN FIRST — in a repository this act does not own,
    # so what is measured is git's behaviour and not this act's. Without the
    # refusal the helper runs; that is the finding.
    elsewhere = tmp_path / "unguarded"
    _git(tmp_path, "init", "--initial-branch=main", str(elsewhere))
    (elsewhere / "f").write_text("x", encoding="utf-8")
    _git(elsewhere, "add", "f")
    _git(elsewhere, "commit", "-m", "x")
    _git(elsewhere, "remote", "add", "origin", str(destination))
    _git(elsewhere, "config", "remote.origin.vcs", "evil")
    subprocess.run(["git", "-C", str(elsewhere), "-c",
                    "protocol.ext.allow=never", "push", "origin",
                    "HEAD:refs/heads/main"],
                   # `_GIT_ENV` IS A SNAPSHOT TAKEN AT IMPORT, so the
                   # monkeypatched PATH has to be put back over it or the
                   # planted helper is not on the one git searches.
                   capture_output=True,
                   env={**_GIT_ENV, "PATH": os.environ["PATH"]})
    assert marker.exists(), (
        "git did not run the planted helper, so this environment cannot "
        "reproduce the finding and the refusal below would be untested")
    marker.unlink()

    _git(created.location, "config", "remote.origin.vcs", "evil")
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert "remote.origin.vcs" in str(caught.value), caught.value
    assert not marker.exists(), "the helper ran despite the refusal"
    assert subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{act.DEFAULT_BRANCH}"],
        capture_output=True, env=_GIT_ENV).returncode != 0

    # AND `url.<prefix>.insteadOf` REWRITES THE DESTINATION before the
    # transport is chosen, which reaches the same helper by another key.
    _git(created.location, "config", "--unset", "remote.origin.vcs")
    _git(created.location, "config", "url.evil::.insteadOf",
         str(destination))
    with pytest.raises(act.RepositoryActRefused) as second:
        act.push_to_remote(store, project_id=project.id)
    assert "insteadof" in str(second.value).lower(), second.value
    assert not marker.exists()
    # THE VALUE IS NOT ECHOED — an `insteadOf` prefix can be credential-shaped,
    # which is why the scan asks for `--name-only`.
    assert str(destination) not in str(second.value)

    # AND THE ORDINARY PUSH IS UNAFFECTED once neither key is set.
    _git(created.location, "config", "--unset-all",
         "url.evil::.insteadOf")
    assert act.push_to_remote(store, project_id=project.id) == str(destination)


def test_a_credential_in_scp_userinfo_is_refused_even_with_a_colon_in_it(
) -> None:
    """`user:secret@host:path` is the credential shape this rule exists for.

    The scp class required the pre-`@` half to hold no colon, so the one form
    that actually carries a password slipped past it — and `git remote add`
    persists the string in `.git/config` and in the map row every signed-in
    caller can read (Copilot review of openDox-code#26, round 31, suppressed).
    """
    for refused in ("user:secret@host:path",
                    "git:ghp_supersecrettoken@example.invalid:x.git",
                    "user@host:path"):
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.refuse_credential_bearing_remote(refused)
        assert "secret" not in str(caught.value).lower() or "ghp_" not in str(
            caught.value), caught.value

    # AND THE WIDENED USER CLASS STILL CANNOT CLAIM A URL: `[^/@]+` cannot
    # cross the `//` of a scheme, so an ordinary https remote is judged by the
    # URL rule and a plain path by neither.
    act.refuse_credential_bearing_remote("https://example.invalid/x.git")
    act.refuse_credential_bearing_remote("/srv/projects/other.git")
    act.refuse_credential_bearing_remote("host:path")


def test_a_map_row_whose_location_cannot_be_opened_refuses_by_name(
        store, project, project_repository_root: Path) -> None:
    """A `ValueError` out of `open()` is this act's refusal, not a 500.

    A legacy or hand-written row can hold a location with an embedded NUL, and
    `open()` raises `ValueError` before any syscall — which the binding
    handler did not name, so attach and push answered with a traceback instead
    of the act's own named refusal (Copilot review of openDox-code#26, round
    32, suppressed).
    """
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    _legacy_remote_row(store, project.id, str(project_repository_root / "d.git"))
    row = act._local_git_row(store, project.id)
    broken = dataclasses.replace(row, location=str(row.location) + "\0x")
    with pytest.raises(act.RepositoryActRefused) as caught:
        with act._bound_to_mapped_repository(broken, "git"):
            pass
    assert "without following a link" in str(caught.value), caught.value
    assert "ValueError" in str(caught.value), caught.value


def test_a_successful_push_of_a_legacy_row_still_redacts_its_credential(
        client_with_repositories, mint_token, database, tmp_path: Path
) -> None:
    """The 200 path was the one the other case could not reach.

    The legacy-row case beside this one uses an UNREACHABLE remote, so it
    exercises the 409 and leaves `push_to_remote`'s success response — the one
    place a credential-bearing row is echoed back — covered by nothing. A
    regression there would keep the suite green (Copilot review of
    openDox-code#26, round 32, suppressed).

    MEASURED, git 2.43.0: `file://user:token@/abs/path.git` pushes; git ignores
    the authority for a `file://` URL. So a reachable legacy row is a real
    shape and not a contrivance.
    """
    token = mint_token(subject="api-legacy-push-owner")
    project = client_with_repositories.post(
        "/api/v1/projects", json={"slug": "legacy-push", "title": "Legacy"},
        headers=_auth(token)).json()
    created = client_with_repositories.post(
        f"/api/v1/projects/{project['id']}/repository", headers=_auth(token))
    assert created.status_code == 201, created.text
    location = Path(created.json()["location"])

    destination = tmp_path / "reachable.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(destination))
    legacy = f"file://someone:ghp_supersecret@{destination}"
    # AROUND the store, which is what a legacy row is: § 3.5's batch made
    # `attach_remote` refuse this value, and the point of these cases is the
    # row that got in before any such rule existed.
    with database.transaction() as conn:
        conn.execute(
            "update project_repositories set remote_url = %s "
            "where project_id = %s", (legacy, project["id"]))
    _git(location, "remote", "add", act.REMOTE_NAME, legacy)

    pushed = client_with_repositories.post(
        f"/api/v1/projects/{project['id']}/repository/push",
        headers=_auth(token))
    assert pushed.status_code == 200, pushed.text
    # THE PUSH REALLY HAPPENED — a 200 for a push that did nothing would make
    # the redaction assertion below vacuous.
    assert subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{act.DEFAULT_BRANCH}"],
        capture_output=True, env=_GIT_ENV).returncode == 0
    assert "ghp_supersecret" not in pushed.text
    assert "someone" not in pushed.text
    assert pushed.json()["pushed_to"] == "<redacted-url>"


def test_the_first_commit_cannot_be_forged_by_a_project_id_or_a_display_name(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`initialize_repository` is public and does not go through the map's validation.

    The project id and the actor are both interpolated into the repository's
    FIRST and permanent commit message, and the API hands `actor` an
    authenticated DISPLAY NAME — so a newline in either wrote extra lines into
    a record a reader cannot tell from the act's own (Copilot review of
    openDox-code#26, round 33: one thread and one "previously missed").
    """
    for project_id, actor in (("p1\nCreated-By: somebody-else", ACTOR),
                              ("p1", "Ann\nAdapter: forged")):
        with pytest.raises(act.RepositoryActRefused) as caught:
            act.initialize_repository(tmp_path / "forged.git",
                                      project_id=project_id, actor=actor)
        assert "control character" in str(caught.value), caught.value
        assert "nothing is created" in str(caught.value)
    assert not (tmp_path / "forged.git" / "HEAD").exists()

    # AND AN ORDINARY CREATE IS UNAFFECTED, and its message carries the two
    # values it is supposed to.
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    message = _git(created.location, "log", "-1", "--format=%B")
    assert f"Created-By: {ACTOR}" in message
    assert str(project.id) in message


def test_the_ownership_recheck_answers_inside_the_refusal_boundary(
        store, project, project_repository_root: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A check that cannot complete is a check that did not pass.

    The bind re-asks containment of the OPEN object, and that question calls
    `Path(location).parent.resolve()` — which raises `OSError` or
    `RuntimeError` for a parent renamed, replaced by a symlink loop or made
    unreachable after the bind. `push_to_remote` translates only
    `GitCommandFailed`, so the API answered 500 instead of the act's named
    refusal (Copilot review of openDox-code#26, round 33, suppressed).

    `_bound_local_destination` IS ENTERED DIRECTLY, because the destination
    check one function up asks the same question and already translates it —
    driving this through `push_to_remote` would measure that handler and not
    this one.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "governed.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(destination))

    real_resolve = Path.resolve

    def exploding(self: Path, *args: object, **kwargs: object) -> Path:
        if self == Path(created.location).parent:
            raise RuntimeError("Symlink loop while resolving")
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", exploding)
    with pytest.raises(act.RepositoryActRefused) as caught:
        act._bound_local_destination(str(destination), created.location)
    assert "could not be resolved" in str(caught.value), caught.value
    assert "RuntimeError" in str(caught.value)
    assert "refused rather than made unchecked" in str(caught.value)

    # AND WITHOUT THE FAULT the same bind is made and nothing is refused.
    monkeypatch.undo()
    handle, bound = act._bound_local_destination(str(destination),
                                                 created.location)
    try:
        assert handle is not None and bound
    finally:
        os.close(handle)


# -- the independent adversarial review: A26-1, A26-3, A26-5 -----------------


def test_an_include_path_cannot_hide_an_executed_key_from_the_push_guard(
        store, project, project_repository_root: Path, tmp_path: Path) -> None:
    """`git config --local` does not follow `include.path`; git's reader does.

    `--includes` DEFAULTS TO OFF when a config FILE is named — `--local`,
    `--worktree`, `--global`, `--file` — and ON only when git searches all of
    them, while the config READER always follows an include. So a repository
    whose `.git/config` holds nothing but `[include] path = extra.cfg` hid
    every key this guard exists to refuse, and git still ran them during the
    push (independent adversarial review of openDox-code#26, A26-1).

    MEASURED, git 2.43.0, the probe's exact argv:

        $ git config --local --get-all credential.helper
        (exit 1, no output)                  <- what the guard saw
        $ git config --local --includes --get-all credential.helper
        !f() { … }; f                        <- what git runs

    This guard is the WHOLE attack surface by design: `GitRunner` deliberately
    keeps the operator's global and system config, so the repository-local file
    is the only one this act judges — and an include was a hole straight
    through it.
    """
    created = act.create_repository(store, project_id=project.id,
                                    root=project_repository_root, actor=ACTOR)
    destination = tmp_path / "governed.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(destination))
    act.attach_remote(store, project_id=project.id,
                      remote_url=str(destination))

    config = Path(created.location) / "config"
    included = Path(created.location) / "extra.cfg"
    original = config.read_text(encoding="utf-8")

    # EVERY FIXED KEY, one at a time, through the include.
    for key in act._EXECUTED_LOCAL_KEYS:
        section, _, name = key.partition(".")
        included.write_text(f'[{section}]\n\t{name} = "!f() {{ :; }}; f"\n',
                            encoding="utf-8")
        config.write_text(original + "[include]\n\tpath = extra.cfg\n",
                          encoding="utf-8")
        # THE PREMISE: the probe without `--includes` finds nothing, which is
        # what made this invisible. Asserted, so an environment where git
        # behaves differently cannot make the case vacuous.
        assert subprocess.run(
            ["git", "-C", str(created.location), "config", "--local",
             "--get-all", key], capture_output=True, env=_GIT_ENV
        ).returncode != 0, f"{key} is visible without --includes here"
        assert subprocess.run(
            ["git", "-C", str(created.location), "config", "--local",
             "--includes", "--get-all", key], capture_output=True,
            env=_GIT_ENV).returncode == 0

        with pytest.raises(act.RepositoryActRefused) as caught:
            act.push_to_remote(store, project_id=project.id)
        assert key in str(caught.value), (key, str(caught.value))

    # AND A PATTERN KEY THROUGH THE SAME DOOR, since the second probe is a
    # separate call with its own flags.
    included.write_text("[remote \"origin\"]\n\tvcs = evil\n", encoding="utf-8")
    with pytest.raises(act.RepositoryActRefused) as pattern:
        act.push_to_remote(store, project_id=project.id)
    assert "remote.origin.vcs" in str(pattern.value)

    # AND THE ORDINARY PUSH IS UNAFFECTED once the include is gone.
    included.unlink()
    config.write_text(original, encoding="utf-8")
    assert act.push_to_remote(store, project_id=project.id) == str(destination)


def test_what_this_act_refuses_to_store_is_what_it_refuses_to_print() -> None:
    """The two halves of the credential rule asked two different questions.

    `names_a_secret_parameter`'s docstring called itself "THE ONE PLACE THE
    QUESTION IS ASKED, by both halves of the rule" — and the redactor applies
    THREE patterns while the refusal consulted one of them, the positionally
    anchored `_ANY_PARAMETER_ANCHORED`. So `host=db password=hunter2 dbname=x`
    was ACCEPTED and written verbatim into `project_repositories.remote_url` —
    the column whose own refusal text says it is stored durably with nothing to
    rotate it — while every read-back of it was dutifully redacted (independent
    adversarial review of openDox-code#26, A26-3).

    THE INVARIANT IS THE TEST: this act refuses to STORE exactly what it
    refuses to PRINT. A corpus, not a key list — the key list was already
    shared and could not see this.
    """
    carries = (
        "password=hunter2",
        "host=db password=hunter2 dbname=x",
        "/srv/projects/x.git password=hunter2",
        "host=db sslpassword=hunter2",
        "https://host/r.git?token=ghp_supersecret",
        "https://host/r.git#api_key=abc",
        "https://user:pw@host/r.git",
        "user:pw@host:path/r.git",
        "https://host/r.git?%74oken=ghp_supersecret",
    )
    clean = (
        "https://example.invalid/x.git",
        "/srv/projects/other.git",
        "host:path",
        "git@github.com:opensoft/x.git".replace("git@", ""),
        "https://host/r.git?a+b=1",
        "https://host/r.git?ref=main",
        "../sibling.git",
    )
    for value in carries:
        assert lga.redact_credentials(value) != value, value
        with pytest.raises(act.RepositoryActRefused):
            act.refuse_credential_bearing_remote(value)
    for value in clean:
        assert lga.redact_credentials(value) == value, value
        act.refuse_credential_bearing_remote(value)

    # AND THE BICONDITIONAL ITSELF, over both lists at once, because that is
    # the sentence the docstring made and could not keep.
    for value in carries + clean:
        changed = lga.redact_credentials(value) != value
        try:
            act.refuse_credential_bearing_remote(value)
            refused = False
        except act.RepositoryActRefused:
            refused = True
        assert refused == changed, (value, refused, changed)


def test_the_repository_tree_is_not_readable_by_whatever_the_umask_allows(
        tmp_path: Path) -> None:
    """`os.mkdir`'s default mode is the ambient umask, and nothing declared one.

    So the mode of the configured root, of the project's repository and of
    everything `git init` makes under it was a property of whatever umask the
    process inherited: MEASURED `0755` at umask 022, `0775` at 002, and `0777`
    with `config` at `0666` at umask 000. The shipped Kubernetes shape is safe
    today because the pod runs as a single uid with a private volume — which
    makes the answer accidental rather than decided, in a store whose own
    compose comment says losing it is losing documents (independent
    adversarial review of openDox-code#26, A26-5).

    RUN AT `umask 0`, which is the shape the finding forbids: an explicit
    `mode=` is still masked by the umask, so the `fchmod` through the held
    descriptor is what makes the answer the same everywhere, and `--shared` is
    what makes it the same for the files `git init` creates.
    """
    import stat

    previous = os.umask(0o000)
    try:
        location = tmp_path / "root" / "proj-1"
        act.initialize_repository(location, project_id="proj-1", actor=ACTOR)
    finally:
        os.umask(previous)

    def mode(path: Path) -> int:
        return stat.S_IMODE(path.stat().st_mode)

    directories = [location.parent, location, location / "objects",
                   location / "refs", location / "hooks"]
    for path in directories:
        assert mode(path) & 0o077 == 0, (
            f"{path.name} is {oct(mode(path))} at umask 000; the store is "
            "readable and writable by anything sharing the uid's group")
        assert mode(path) == act.REPOSITORY_DIRECTORY_MODE or path != location
    for path in (location / "config", location / "HEAD"):
        assert mode(path) & 0o077 == 0, (path, oct(mode(path)))

    # AND THE REPOSITORY STILL WORKS, which an over-tight mode would break:
    # the act's own first commit is there and readable by this process.
    assert _git(location, "log", "-1", "--format=%s").startswith(
        "Create the repository for project")


def test_the_push_refuses_a_swap_between_two_places_it_does_not_own(
        store, project, project_repository_root: Path, tmp_path: Path,
        monkeypatch) -> None:
    """A→B, with BOTH outside the root — the case containment cannot answer.

    Round 30's fix re-asks the containment question of the OPEN object, which
    closes the swap into a path this service owns. It cannot close a swap
    between two places it does NOT own: external repository A and external
    repository B are both outside the root, so the check passes at the name
    and passes again at the descriptor, and the push lands in B while the map
    row and the API response both name A — a corpus delivered to a destination
    of nobody's choosing, reported as success (Copilot review of
    openDox-code#26, at `cec91c08`).

    The answer is IDENTITY and not containment: the guard reports `(st_dev,
    st_ino)` for what it approved, and `os.fstat` on the descriptor the push
    will actually write through reports what was opened. A descriptor cannot
    be raced — it refers to an object, not to a name.
    """
    act.create_repository(store, project_id=project.id,
                          root=project_repository_root, actor=ACTOR)
    first = tmp_path / "governed-a.git"
    second = tmp_path / "governed-b.git"
    for where in (first, second):
        subprocess.run(["git", "init", "-q", "--bare", str(where)], check=True,
                       env=_GIT_ENV)
    link = tmp_path / "destination"
    link.symlink_to(first, target_is_directory=True)
    act.attach_remote(store, project_id=project.id, remote_url=str(link))

    # BOTH DESTINATIONS ARE OUTSIDE THE ROOT, which is the premise: measured,
    # not assumed, because a test whose premise is false measures nothing.
    root = Path(project_repository_root).resolve()
    for where in (first, second):
        assert root not in where.resolve().parents

    seen: list[str] = []
    real_check = act._refuse_a_destination_this_service_owns

    def _check_then_swap(destinations, location):
        answer = real_check(destinations, location)
        seen.append(os.readlink(link))
        link.unlink()
        link.symlink_to(second, target_is_directory=True)
        return answer

    monkeypatch.setattr(act, "_refuse_a_destination_this_service_owns",
                        _check_then_swap)
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.push_to_remote(store, project_id=project.id)
    assert seen == [str(first)], (
        "the guard did not run against the first destination, so the swap "
        "was not the thing this test measured")
    assert "another when it was opened" in str(caught.value), caught.value
    # AND THE REFUSAL NAMES NEITHER PLACE, because a value that changed under
    # the act is not one a refusal can honestly quote.
    assert str(second) not in str(caught.value)

    # NOTHING REACHED EITHER REPOSITORY. `second` is the one the link pointed
    # at when the push would have run; `first` is the one of record.
    for where in (first, second):
        assert subprocess.run(
            ["git", "-C", str(where), "rev-parse", "--verify", "--quiet",
             f"refs/heads/{act.DEFAULT_BRANCH}"],
            capture_output=True, env=_GIT_ENV).returncode != 0, where

    # AND THE ROW IS AS IT WAS — the refusal is before the push and before any
    # write, so the map still records the destination it recorded.
    assert store.repository_for_project(project.id).remote_url == str(link)

    # WITHOUT THE SWAP the same link, the same guard and the same handle push
    # into the destination of record, so the refusal above is the race and not
    # the mechanism.
    monkeypatch.setattr(act, "_refuse_a_destination_this_service_owns",
                        real_check)
    link.unlink()
    link.symlink_to(first, target_is_directory=True)
    act.push_to_remote(store, project_id=project.id)
    assert subprocess.run(
        ["git", "-C", str(first), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{act.DEFAULT_BRANCH}"],
        capture_output=True, env=_GIT_ENV).returncode == 0
    assert subprocess.run(
        ["git", "-C", str(second), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{act.DEFAULT_BRANCH}"],
        capture_output=True, env=_GIT_ENV).returncode != 0


def test_a_directory_that_appears_after_the_preflight_is_not_adopted(
        store, project, project_repository_root: Path,
        monkeypatch) -> None:
    """The exclusive `mkdir` DETECTED the race and the code then ignored it.

    `refuse_unusable_location` allows two states — an empty directory this act
    may adopt, and nothing at all — and `FileExistsError` from the exclusive
    `mkdir` means something different in each. The branch treated both as the
    first, so for a location the preflight found ABSENT another process could
    create an ordinary empty directory in the window, and this act opened it,
    passed the emptiness check and initialized a repository in a directory it
    did not create: the documented exclusive-create guarantee quietly not kept
    (Copilot review of openDox-code#26, at `cec91c08`).

    THE WINDOW IS DRIVEN: `os.mkdir` is replaced by one that really creates the
    directory — as the other process would — and then raises the error the
    kernel gives the loser. Nothing else can reach that window from a test.
    """
    import errno

    location = Path(project_repository_root) / project.id
    assert not location.exists(), "the preflight must find this absent"

    real_mkdir = os.mkdir

    def _somebody_else_creates_it(path, mode=0o777, *, dir_fd=None):
        if path == location.name and dir_fd is not None:
            real_mkdir(path, 0o755, dir_fd=dir_fd)
            raise FileExistsError(errno.EEXIST, "File exists", str(path))
        return real_mkdir(path, mode, dir_fd=dir_fd)

    # `os.supports_dir_fd` is a membership test on the FUNCTION OBJECT, and
    # the act refuses a platform whose `mkdir` is not in it — so the double
    # has to be declared capable, or this case would measure the
    # platform refusal instead of the race.
    monkeypatch.setattr(os, "supports_dir_fd",
                        set(os.supports_dir_fd) | {_somebody_else_creates_it})
    monkeypatch.setattr(os, "mkdir", _somebody_else_creates_it)
    with pytest.raises(act.RepositoryActRefused) as caught:
        act.create_repository(store, project_id=project.id,
                              root=project_repository_root, actor=ACTOR)
    assert "created it while this repository was being made" in str(caught.value)

    # NOTHING WAS INITIALIZED IN IT — the intruder's directory is still an
    # ordinary empty directory and not a repository.
    assert location.is_dir()
    assert list(location.iterdir()) == [], location
    # The map row goes back with the CALLER'S transaction, which is this act's
    # documented contract and is what the refusal says in terms.
    assert "rolled back with the caller's transaction" in str(caught.value), (
        "the refusal must say what becomes of the row, like every other "
        "refusal this act makes after the row is written")

    # AND THE DOCUMENTED CASE IS UNTOUCHED: a directory that was ALREADY there
    # and empty when the preflight looked is still adopted, `FileExistsError`
    # and all. A second project, because the row above is only rolled back by
    # a caller this test is standing in for.
    monkeypatch.undo()
    other = store.create_project(slug="second", title="Second",
                                 created_by=project.created_by)
    store.create_membership(user_id=project.created_by, project_id=other.id,
                            role="owner")
    waiting = Path(project_repository_root) / other.id
    waiting.mkdir(parents=True)
    row = act.create_repository(store, project_id=other.id,
                                root=project_repository_root, actor=ACTOR)
    assert Path(row.location) == waiting
    assert (waiting / "HEAD").is_file(), "the repository was not initialized"
