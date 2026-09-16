"""openDox CREATES A REPOSITORY AS A FIRST-CLASS ACT
(`split-opendox-two-layer-product` § 3.6).

§ 3.6, verbatim: "**openDox CREATES A REPOSITORY AS A FIRST-CLASS ACT**, or the
origin complaint returns one level down: RULING Q1 answers *'no good place to
store my projects'* with its coordination half while the specs still land in a
repository. Includes RULING C3's standalone shape — a PLAIN LOCAL GIT
REPOSITORY per project, commits as the write path, a remote attachable later —
as the trivial conformant adapter implementation, not as a mode."

Design § D5 names the failure this file exists to prevent: "Q1 answers 'no good
place to store my projects' with its COORDINATION half … while the specs still
land in a repository. So **openDox must be able to CREATE that repository as a
first-class act**, or the complaint returns one level down. Nothing in the
rulings says who creates it; `tasks.md` § 3.6 makes it an openDox-side task
rather than leaving it implied."

## The act, in one sentence

`create_repository` writes the project-to-repository MAP ROW and creates the
REPOSITORY, and a caller that does one without the other has not performed the
act.

## Two systems, one act, and the order is a decision

The map row is a database write and the repository is a directory on a
filesystem; no transaction spans both. The row is written FIRST, inside the
caller's transaction, and the repository is created second:

  * a repository that fails to initialize raises before the transaction
    commits, so no row survives pointing at nothing — the failure a consumer
    could not detect;
  * the opposite order would leave a repository nothing maps to on a database
    failure, which is invisible until the next act tries the same directory.

The remaining window is real and is NOT papered over: a process killed between
`git init` and the transaction's commit leaves a directory with no row. The
next `create_repository` for that project REFUSES and names it, with the two
remedies, rather than initializing over it or adopting it silently — adopting a
directory nobody can account for is how a project ends up pointed at somebody
else's history.

Within the act the ROW is also checked first, because it holds the
authoritative fact: a project that already has a repository is refused as
"already mapped" rather than as "there is a directory here", which is only the
symptom. Nothing has touched the filesystem at that point, so either refusal
leaves the disk as it found it.

## What this module does NOT do

It does not write documents. The first document arrives through
`LocalGitCorpus.write_back`, which is the adapter's operation and the corpus's
declared governed write path. The act creates the repository and its first
commit, and that first commit is EMPTY on purpose: a README this act invented
would be content the project's owner did not write, in the one place the
product's promise is that documents are theirs.

It also does not create a checkout. The repository is BARE — see
`local_git_adapter`'s header for the argument, and `initialize_repository`
below for the line.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from opendox.corpus_adapter import CorpusRef
from opendox.runtime import identity
from opendox.runtime.local_git_adapter import (
    ADAPTER_NAME,
    DEFAULT_BRANCH,
    GitCommandFailed,
    GitRunner,
    git_available,
    git_identity,
    repository_lock,
)

__all__ = [
    "ADAPTER_NAME",
    "CreatedRepository",
    "RepositoryActRefused",
    "attach_remote",
    "corpus_ref_for",
    "create_repository",
    "initialize_repository",
    "push_to_remote",
    "repository_location",
]


class RepositoryActRefused(Exception):
    """The act could not be performed, named. Carries no secret material."""


@dataclass(frozen=True)
class CreatedRepository:
    """What the act produced: the map row, and the corpus it addresses."""

    row: Any               #: an `identity.ProjectRepository`
    ref: CorpusRef         #: what to hand `LocalGitCorpus.resolve`
    location: Path
    initial_commit: str


def repository_location(root: str | os.PathLike[str], project_id: str) -> Path:
    """`<OPENDOX_PROJECT_REPOSITORY_ROOT>/<project id>`.

    ONE DIRECTORY PER PROJECT ID, and the id rather than the slug: a slug is a
    human name that a rename would move, and a repository that moved when its
    project was renamed would make every `location` in the map a statement with
    a shelf life.
    """
    if not project_id or "/" in project_id or project_id in {".", ".."}:
        raise RepositoryActRefused(
            f"{project_id!r} is not a usable project id for a directory name")
    return Path(root).expanduser().resolve() / project_id


def _require_local_git(row: Any, *, project_id: str) -> Any:
    if row.adapter != ADAPTER_NAME:
        raise RepositoryActRefused(
            f"project {project_id} maps to adapter {row.adapter!r}, not "
            f"{ADAPTER_NAME!r}; this act mutates only RULING C3's plain local "
            "git repository")
    return row


def _current_head_ref(git: GitRunner) -> str:
    completed = git.run("symbolic-ref", "HEAD")
    if completed.returncode != 0:
        raise GitCommandFailed(("symbolic-ref", "HEAD"), completed)
    return completed.stdout.decode().strip()


def _display_remote_url(remote_url: str) -> str:
    parts = urlsplit(remote_url)
    if parts.scheme and parts.netloc:
        host = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, parts.query,
                           parts.fragment))
    if "@" in remote_url and ":" in remote_url.split("@", 1)[1]:
        return remote_url.split("@", 1)[1]
    return remote_url


def corpus_ref_for(row: Any, *, name: str | None = None) -> CorpusRef:
    """The `CorpusRef` a map row addresses, for `LocalGitCorpus.resolve`.

    `name` is the caller's name for the corpus and defaults to the project id,
    which is what `DocumentId.corpus` then carries.
    """
    return CorpusRef(name=name or row.project_id, location=row.location)


def create_repository(store: Any, *, project_id: str,
                      root: str | os.PathLike[str], actor: str,
                      branch: str = DEFAULT_BRANCH,
                      executable: str = "git") -> CreatedRepository:
    """Create this project's plain local git repository, and map the project to it.

    `store` is an `identity.CoordinationStore` over the CALLER'S transaction,
    so the row and everything else the caller writes commit together.
    """
    location = repository_location(root, project_id)

    try:
        row = store.repository_for_project(project_id)
    except identity.NotFoundError:
        row = None
    if row is not None:
        raise identity.ConflictError(
            f"project {project_id!r} already maps to a repository at "
            f"{row.location!r}; the map is one row per project (RULING C3: a "
            "plain local git repository PER PROJECT)")

    if not git_available(executable):
        raise RepositoryActRefused(
            f"{executable!r} is not on PATH; RULING C3's repository is a plain "
            "local git repository and this act creates it by running git")

    # THE ROW FIRST, inside the caller's transaction, and first also because it
    # holds the AUTHORITATIVE fact: a project that is already mapped is refused
    # as "already mapped" (the store's `ConflictError`) and not as "there is a
    # directory here", which is a symptom. Measured, not assumed — with the
    # checks the other way round, `test_a_second_act_on_the_same_project_is_
    # refused` got the directory's message for a project whose real problem was
    # its map row.
    row = store.create_project_repository(
        project_id=project_id, adapter=ADAPTER_NAME, location=str(location))

    # THEN the orphan check, and still before any filesystem mutation: nothing
    # below has run, so a refusal here leaves the disk untouched and the row is
    # rolled back with the caller's transaction.
    if location.exists() and (not location.is_dir() or any(location.iterdir())):
        raise RepositoryActRefused(
            f"{location} already exists and is not empty. Either a previous "
            "act was interrupted between creating the repository and "
            "committing its map row, or this directory belongs to something "
            "else. Remove it, or map the project to it deliberately — this "
            "act will not adopt a directory nobody can account for.")

    commit = initialize_repository(location, project_id=project_id, actor=actor,
                                   branch=branch, executable=executable)
    return CreatedRepository(row=row, ref=corpus_ref_for(row),
                             location=location, initial_commit=commit)


def initialize_repository(location: str | os.PathLike[str], *, project_id: str,
                          actor: str, branch: str = DEFAULT_BRANCH,
                          executable: str = "git") -> str:
    """Create the repository itself and its first commit; return that commit.

    SEPARATE FROM `create_repository` and public, for two callers rather than
    one: the act above, and anything that needs a conformant corpus without a
    database — `split-opendox-two-layer-product` § 3.7's conformance corpus and
    this leg's own hermetic suites, which run in the REQUIRED `validate` job
    where psycopg is not installed. The act is still the pair; this is the half
    of it that touches the filesystem.
    """
    location = Path(location).expanduser().resolve()
    git = GitRunner(location, executable)
    try:
        location.mkdir(parents=True, exist_ok=True)
        # BARE, and it is the decision `local_git_adapter`'s header argues in
        # full: this repository is storage openDox MANAGES (RULING C3's own
        # verb), the corpus is its history, and a checkout beside it would be a
        # second answer to "what does this project contain" that the adapter is
        # forbidden to keep up to date. A human who wants a checkout clones it;
        # `push_to_remote` below works from a bare repository unchanged.
        git.out("init", "--bare", f"--initial-branch={branch}", ".")
        # The first commit, through plumbing and over the EMPTY TREE: no file
        # is written, so the repository's whole content is what its owner puts
        # there through the adapter's write path.
        empty_tree = git.out("hash-object", "-t", "tree", "-w", "--stdin",
                             stdin=b"").decode().strip()
        message = (
            f"Create the repository for project {project_id}\n"
            "\n"
            "openDox creates a repository as a first-class act "
            "(split-opendox-two-layer-product § 3.6); the repository is a "
            "plain local git repository and commits are the write path "
            "(RULING C3, opensoft/openxFactory#656 comment 5544381563). This "
            "commit is empty: every document arrives through the corpus "
            "adapter's write path.\n"
            "\n"
            f"Created-By: {actor}\n"
            f"Adapter: {ADAPTER_NAME}\n")
        commit = git.out("commit-tree", empty_tree, "-m", message,
                         env=git_identity(actor)).decode().strip()
        git.out("update-ref", f"refs/heads/{branch}", commit, "")
    except (GitCommandFailed, OSError) as failed:
        raise RepositoryActRefused(
            f"the repository at {location} could not be created ({failed}); "
            "the map row is rolled back with the caller's transaction"
        ) from failed
    return commit


def attach_remote(store: Any, *, project_id: str, remote_url: str,
                  remote_name: str = "origin",
                  executable: str = "git") -> Any:
    """RULING C3's "a remote can be attached later", as one act.

    Updates the map row's `remote_url` and configures the remote in the
    repository. It writes NO object and moves NO ref: attaching a remote
    changes where this repository can push and changes nothing it contains —
    which is what makes the eventual move "a push, not a migration".
    """
    if remote_name != "origin":
        raise RepositoryActRefused(
            f"remote name {remote_name!r} is not supported; this act stores and "
            "pushes one attached remote named 'origin'")
    row = _require_local_git(store.repository_for_project(project_id),
                             project_id=project_id)
    git = GitRunner(Path(row.location), executable)
    stored_remote_url = _display_remote_url(remote_url)
    try:
        with repository_lock(git):
            existing = git.run("remote", "get-url", remote_name)
            previous = (existing.stdout.decode().strip()
                        if existing.returncode == 0 else None)
            if existing.returncode == 0:
                git.out("remote", "set-url", remote_name, remote_url)
            else:
                git.out("remote", "add", remote_name, remote_url)
            try:
                return store.attach_remote(project_id=project_id,
                                           remote_url=stored_remote_url)
            except Exception:
                if previous is None:
                    git.out("remote", "remove", remote_name)
                else:
                    git.out("remote", "set-url", remote_name, previous)
                raise
    except GitCommandFailed as failed:
        raise RepositoryActRefused(
            f"the remote {remote_name!r} could not be attached to "
            f"{row.location} ({failed})") from failed


def push_to_remote(store: Any, *, project_id: str,
                   branch: str | None = None, remote_name: str = "origin",
                   executable: str = "git") -> str:
    """Move the project into a governed factory. RULING C3: this is a PUSH.

    "moving a student or lab-assistant project into a governed factory is a
    push, not a migration." Nothing is converted, exported or re-created: the
    same objects the local repository already holds are sent to the remote the
    previous act attached, and the local repository keeps serving reads through
    the same adapter afterwards.
    """
    if remote_name != "origin":
        raise RepositoryActRefused(
            f"remote name {remote_name!r} is not supported; this act pushes the "
            "attached remote named 'origin'")
    row = _require_local_git(store.repository_for_project(project_id),
                             project_id=project_id)
    if not row.remote_url:
        raise RepositoryActRefused(
            f"project {project_id} has no attached remote; attach one first "
            "(RULING C3: a remote can be attached later, and the move is then "
            "a push)")
    git = GitRunner(Path(row.location), executable)
    try:
        with repository_lock(git):
            head_ref = _current_head_ref(git)
            target = branch or head_ref.rsplit("/", 1)[-1]
            git.out("push", remote_name, f"{head_ref}:refs/heads/{target}")
    except GitCommandFailed as failed:
        raise RepositoryActRefused(
            f"the push to {row.remote_url} failed ({failed}); the project "
            f"is unchanged and is still served from {row.location}") from failed
    return row.remote_url
