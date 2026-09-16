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
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opendox.corpus_adapter import CorpusRef
from opendox.runtime.local_git_adapter import (
    ADAPTER_NAME,
    DEFAULT_BRANCH,
    GitCommandFailed,
    GitRunner,
    git_available,
    git_identity,
    names_a_secret_parameter,
    redact_credentials,
)

#: The ONE remote this runtime configures and pushes to. A constant and not a
#: parameter: `project_repositories` has a single `remote_url` column, so a
#: second remote would be a name the map cannot record and the push cannot find.
REMOTE_NAME = "origin"

#: How long a push may take before it is a refusal. The push runs inside the
#: caller's database transaction, so an unbounded one holds a connection and a
#: row lock for as long as the network does.
PUSH_TIMEOUT_SECONDS = 120.0

#: A remote URL carrying USERINFO — `https://user:token@host/...` or
#: `user@host:path` — is refused. `project_repositories.remote_url` is
#: serialized by the repository endpoints to any authenticated caller, so a
#: credential embedded here is a credential disclosed to every signed-in user
#: of the install, and it is also written into the durable map where nothing
#: will ever rotate it (Copilot review of openDox-code#26). Credentials for a
#: remote belong in the environment git already reads them from — a credential
#: helper, an `ssh` key, a `.netrc` — never in a row.
_URL_USERINFO = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://[^/@]*@")
_SCP_USERINFO = re.compile(r"^[^/:@]+@[^/:@]+:")


#: Query or fragment keys that carry a secret. USERINFO IS NOT THE ONLY PLACE:
#: `https://host/repo.git?token=…` keeps the token out of the userinfo and puts
#: it in the map row and in every API response just the same (Copilot review of
#: openDox-code#26).
#: ONE KEY LIST, IMPORTED. This refusal and `redact_credentials` are two
#: halves of one rule — what may not be stored, and what must not be printed if
#: it was stored before the rule existed — and they drifted apart once already:
#: the refusal rejected `?token=…` while the redaction saw straight through it
#: (Copilot review of openDox-code#26). Sharing the vocabulary is what keeps a
#: key added to one from being missing in the other.
#: AND THE NAME IS DECODED BEFORE IT IS JUDGED. This was a raw-text regex over
#: the URL, so `https://host/x.git?%74oken=ghp_secret` contained no literal
#: `token`, was accepted, and was stored verbatim in a column the repository
#: endpoints read back to every project member (Copilot review of
#: openDox-code#26, round 5). The question is asked by
#: `local_git_adapter.names_a_secret_parameter` — ONE predicate for both
#: halves, so the storing rule and the printing rule cannot answer it
#: differently, which is the same defect the shared key list was introduced to
#: close.


def refuse_credential_bearing_remote(remote_url: str) -> None:
    """Refuse a remote URL with a credential in it, and a URL that will not parse.

    The message NEVER echoes the URL: it is the thing that might be a secret.

    A MALFORMED URL IS REFUSED HERE TOO. `urlsplit` (and `parts.port`) raise
    `ValueError` on values like `https://[bad`, and that escaped as an
    unhandled 500 rather than as this act's named refusal.
    """
    if not remote_url.strip():
        raise RepositoryActRefused("the remote URL is empty")
    # SURROUNDING WHITESPACE IS REFUSED BEFORE ANYTHING ELSE, and this is the
    # hole it closes: both credential checks below are ANCHORED (`^`), while
    # `urllib.parse.urlsplit` accepts and silently discards leading whitespace.
    # `" https://user:token@example.invalid/x.git"` therefore passed every
    # check and was persisted VERBATIM into `project_repositories.remote_url`,
    # which the repository endpoints read back to every authenticated caller —
    # the exact disclosure this function exists to prevent (Copilot review of
    # openDox-code#26). REFUSED rather than trimmed: this act stores what the
    # caller gave it, so quietly rewriting the value would mean the row and the
    # request disagree about what was attached, and a caller with a stray space
    # would never learn that its URL was edited.
    if remote_url != remote_url.strip():
        raise RepositoryActRefused(
            "the remote URL has leading or trailing whitespace. It is not "
            "echoed here because a value that would not parse may still "
            "contain a secret; send the URL with no surrounding whitespace.")
    try:
        parts = urllib.parse.urlsplit(remote_url)
        _ = parts.port          # `port` parses lazily and is where it raises
    except ValueError as exc:
        raise RepositoryActRefused(
            f"the remote URL could not be parsed ({type(exc).__name__}); it is "
            "not echoed here because a malformed value may still contain a "
            "secret") from exc
    if _URL_USERINFO.match(remote_url) or _SCP_USERINFO.match(remote_url):
        raise RepositoryActRefused(
            "the remote URL carries user information before the host. "
            "`project_repositories.remote_url` is read back by the repository "
            "endpoints to every authenticated caller and is stored durably "
            "with nothing to rotate it, so a credential must not be part of "
            "it. Use a credential helper, an ssh key or a .netrc, and give "
            "this act the URL alone.")
    if names_a_secret_parameter(remote_url):
        raise RepositoryActRefused(
            "the remote URL carries a credential-shaped query or fragment "
            "parameter. Userinfo is not the only place a secret hides, and "
            "this column is read back to every authenticated caller; give "
            "this act the URL alone and let git's own credential machinery "
            "supply the rest.")

__all__ = [
    "ADAPTER_NAME",
    "REMOTE_NAME",
    "CreatedRepository",
    "RepositoryActRefused",
    "attach_remote",
    "corpus_ref_for",
    "create_repository",
    "initialize_repository",
    "PUSH_TIMEOUT_SECONDS",
    "refuse_credential_bearing_remote",
    "refuse_unusable_location",
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
    # ABSOLUTE, ALWAYS. `OPENDOX_PROJECT_REPOSITORY_ROOT` defaults to the
    # RELATIVE `var/projects`, and a relative path written into the durable map
    # resolves against whatever working directory the next process happens to
    # have — so the API and the CLI, or the same API after a restart under a
    # different unit, would read one row as two different places and the
    # repository would look absent or, worse, be the wrong tree (Copilot review
    # of openDox-code#26). `resolve()` also collapses `..` and a symlinked
    # root, so the row records one canonical name for one directory.
    return (Path(root).expanduser().resolve() / project_id)


def refuse_unusable_location(location: Path) -> None:
    """Refuse a path that is not an empty (or absent) directory, BY NAME.

    Two different refusals with one rule: a path collision (`location` is a
    regular file, which made `iterdir()` raise `NotADirectoryError` and reach
    the API as a 500) and a directory nobody can account for — left, for
    instance, by a process killed between `git init` and the transaction's
    commit. Adopting such a directory is how a project ends up pointed at
    somebody else's history.
    """
    # A SYMLINK IS REFUSED BEFORE ANYTHING ELSE, because every check below
    # FOLLOWS it: a symlink pointing at an empty directory passes the emptiness
    # guard and `git init --bare` then writes through it into somebody else's
    # tree, which is precisely the adoption this function exists to refuse
    # (Copilot review of openDox-code#26). `lexists` so a dangling one is
    # refused too rather than silently replaced.
    if location.is_symlink() or (os.path.lexists(location)
                                 and not location.exists()):
        raise RepositoryActRefused(
            f"{location} is a symbolic link. A repository is created at a real "
            "directory this act owns; writing through a link would put the "
            "project's history wherever the link points, which is a directory "
            "nobody accounted for.")
    if location.exists() and not location.is_dir():
        raise RepositoryActRefused(
            f"{location} exists and is not a directory, so this project's "
            "repository cannot be created there. Remove it, or point "
            "OPENDOX_PROJECT_REPOSITORY_ROOT somewhere else.")
    if location.is_dir():
        # THE EMPTINESS CHECK IS INSIDE THE ERROR TRANSLATION. `iterdir()` on a
        # directory the service can `stat` but not READ raises
        # `PermissionError`, and this call sat outside every `try`, so it
        # escaped as an API 500 instead of the named `RepositoryActRefused`
        # this act promises for every reason it will not create a repository
        # (Copilot review of openDox-code#26).
        try:
            occupied = any(location.iterdir())
        except OSError as exc:
            raise RepositoryActRefused(
                f"{location} exists and could not be inspected "
                f"({type(exc).__name__}); this act will not create a "
                "repository at a directory it cannot read, because it cannot "
                "tell an empty one from somebody else's history") from exc
        if occupied:
            raise RepositoryActRefused(
                f"{location} already exists and is not empty. Either a "
                "previous act was interrupted between creating the repository "
                "and committing its map row, or this directory belongs to "
                "something else. Remove it, or map the project to it "
                "deliberately — this act will not adopt a directory nobody "
                "can account for.")


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

    # THE ROW FIRST, inside the caller's transaction, and first also because it
    # holds the AUTHORITATIVE fact: a project that is already mapped is refused
    # as "already mapped" (the store's `ConflictError`) and not as "there is a
    # directory here", which is a symptom. Measured, not assumed — with the
    # checks the other way round, `test_a_second_act_on_the_same_project_is_
    # refused` got the directory's message for a project whose real problem was
    # its map row.
    row = store.create_project_repository(
        project_id=project_id, adapter=ADAPTER_NAME, location=str(location))

    # THE DEPENDENCY CHECK COMES AFTER THE MAP, and the order is the finding's
    # (Copilot review of openDox-code#26): with `git_available` first, a repeat
    # create for an ALREADY-MAPPED project answered "git is not on PATH" on a
    # host without git and `ConflictError` on a host with it — the same act
    # giving two different answers about the same durable fact. The map row is
    # authoritative; the environment is checked once the map has spoken.
    if not git_available(executable):
        raise RepositoryActRefused(
            f"{executable!r} is not on PATH; RULING C3's repository is a plain "
            "local git repository and this act creates it by running git")

    # THEN the orphan check, and still before any filesystem mutation: nothing
    # below has run, so a refusal here leaves the disk untouched and the row is
    # rolled back with the caller's transaction.
    refuse_unusable_location(location)

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
    location = Path(location)
    # THE ORPHAN GUARANTEE IS THIS FUNCTION'S TOO, not only `create_repository`'s.
    # It is public and § 3.7's corpus setup calls it directly, so a direct
    # caller could otherwise `git init --bare` over a non-empty, unaccounted
    # directory and mix the two (Copilot review of openDox-code#26). The checks
    # are cheap and idempotent, so making them twice costs nothing and makes
    # the guarantee a property of the function rather than of one caller.
    refuse_unusable_location(location)
    try:
        # INSIDE the `try`: a permission error or a non-directory parent from
        # `mkdir` used to escape as `PermissionError`/`NotADirectoryError` and
        # reach the API as a 500, instead of the act's named refusal (Copilot
        # review of openDox-code#26).
        location.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RepositoryActRefused(
            f"the directory {location} could not be created ({exc}); the map "
            "row is rolled back with the caller's transaction") from exc
    git = GitRunner(location, executable)
    try:
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
    except GitCommandFailed as failed:
        raise RepositoryActRefused(
            f"the repository at {location} could not be created ({failed}); "
            "the map row is rolled back with the caller's transaction"
        ) from failed
    return commit


def _local_git_row(store: Any, project_id: str) -> Any:
    """The map row, REFUSED unless this adapter is the one that owns it.

    The map carries an `adapter` column precisely so a project can be served by
    something other than a plain local git repository, and these acts ignored
    it: a row belonging to a governed factory's adapter would have had `git
    remote set-url` and `git push` run against its opaque `location` (Copilot
    review of openDox-code#26). A row this adapter does not own is somebody
    else's to act on.
    """
    row = store.repository_for_project(project_id)
    if row.adapter != ADAPTER_NAME:
        raise RepositoryActRefused(
            f"project {project_id} is mapped to the {row.adapter!r} adapter, "
            f"not {ADAPTER_NAME!r}; this act runs git against a plain local "
            "repository and must not touch another adapter's corpus")
    return row


def attach_remote(store: Any, *, project_id: str, remote_url: str,
                  executable: str = "git") -> Any:
    """RULING C3's "a remote can be attached later", as one act.

    Updates the map row's `remote_url` and configures the remote in the
    repository. It writes NO object and moves NO ref: attaching a remote
    changes where this repository can push and changes nothing it contains —
    which is what makes the eventual move "a push, not a migration".

    THE REMOTE IS ALWAYS `origin` AND IS NO LONGER A PARAMETER. It was one, and
    only the URL was persisted: `attach_remote(..., remote_name="upstream")`
    succeeded and `push_to_remote` then looked for `origin` and found nothing
    (Copilot review of openDox-code#26). The map has one `remote_url` column,
    so the runtime has one remote; a name the map cannot record is a name the
    push cannot find.
    """
    refuse_credential_bearing_remote(remote_url)
    row = _local_git_row(store, project_id)
    remote_name = REMOTE_NAME
    # THE DURABLE FACT IS WRITTEN FIRST, INSIDE THE CALLER'S TRANSACTION, and
    # git is configured after it. The order was the other way round, which left
    # a window in which git's `origin` pointed at the new destination while the
    # map still held the old URL or none: a later push would then have gone to
    # one place and REPORTED another (Copilot review of openDox-code#26). This
    # way the only surviving window is the opposite one — the row committed and
    # git not yet reconfigured — which `push_to_remote` REFUSES by name and a
    # repeat of this act repairs, because a `git` failure here raises and the
    # caller's transaction rolls the row back with it.
    updated = store.attach_remote(project_id=project_id, remote_url=remote_url)
    git = GitRunner(Path(row.location), executable)
    try:
        existing = git.run("remote", "get-url", remote_name)
        if existing.returncode == 0:
            git.out("remote", "set-url", remote_name, remote_url)
        else:
            git.out("remote", "add", remote_name, remote_url)
    except GitCommandFailed as failed:
        raise RepositoryActRefused(
            f"the remote {remote_name!r} could not be attached to "
            f"{row.location} ({failed})") from failed
    return updated


def _configured_remote_url(git: GitRunner, remote_name: str, *,
                           for_push: bool = False) -> str | None:
    """What git has under `<remote_name>`, or None when it has no such remote.

    `for_push` asks for the EFFECTIVE PUSH URL. `git push` uses
    `remote.<name>.pushurl` when one is configured and falls back to the fetch
    URL when none is, so the fetch URL alone is not the destination: a stale or
    hand-added `pushurl` passed the map comparison and sent the corpus
    somewhere else while the API reported the mapped URL (Copilot review of
    openDox-code#26, round 5). `--push` is git's own answer to "where would a
    push go", so this asks git rather than reimplementing the fallback.
    """
    arguments = ("remote", "get-url", "--push", remote_name) if for_push else (
        "remote", "get-url", remote_name)
    existing = git.run(*arguments)
    if existing.returncode != 0:
        return None
    return existing.stdout.decode("utf-8", "replace").strip() or None


def _pushable_branch(git: GitRunner, location: str) -> str:
    """The branch this repository's HEAD names — not an assumed `main`.

    `create_repository` and `initialize_repository` both accept a branch and
    the adapter serves a repository whose HEAD is `master` without complaint,
    while this push hard-coded `refs/heads/main` and neither the API nor the
    CLI exposed a branch. A repository created on any other branch was
    therefore servable and unpushable (Copilot review of openDox-code#26).
    Asking HEAD is the same answer `LocalGitCorpus._served_ref` gives for the
    write path, so the two acts agree about which branch the project is.
    """
    symbolic = git.run("symbolic-ref", "--quiet", "HEAD")
    if symbolic.returncode != 0:
        raise RepositoryActRefused(
            f"HEAD in {location} is detached, so there is no branch to push; "
            "point HEAD at a branch first")
    ref = symbolic.stdout.decode("utf-8", "replace").strip()
    if not ref.startswith("refs/heads/"):
        raise RepositoryActRefused(
            f"HEAD in {location} names {ref!r}, which is not a branch")
    return ref[len("refs/heads/"):]


def push_to_remote(store: Any, *, project_id: str,
                   executable: str = "git") -> str:
    """Move the project into a governed factory. RULING C3: this is a PUSH.

    "moving a student or lab-assistant project into a governed factory is a
    push, not a migration." Nothing is converted, exported or re-created: the
    same objects the local repository already holds are sent to the remote the
    previous act attached, and the local repository keeps serving reads through
    the same adapter afterwards.
    """
    row = _local_git_row(store, project_id)
    if not row.remote_url:
        raise RepositoryActRefused(
            f"project {project_id} has no attached remote; attach one first "
            "(RULING C3: a remote can be attached later, and the move is then "
            "a push)")
    git = GitRunner(Path(row.location), executable)

    # THE MAP IS THE DESTINATION OF RECORD, AND GIT IS ASKED WHETHER IT AGREES.
    # This pushed to whatever `origin` happened to be configured as and never
    # looked, so a manual `git remote set-url`, or an `attach_remote` that
    # failed between its two halves, could send the corpus somewhere the map
    # and the success response both misnamed — the one error a push must not
    # make quietly (Copilot review of openDox-code#26). Refused rather than
    # silently reconciled: re-running `attach_remote` is the act that changes a
    # destination, and it is one line for an operator.
    # BOTH URLs, because `git push` does not use the one `get-url` reports:
    # `remote.origin.pushurl` wins when it is set, and a stale or hand-added
    # one passed a fetch-URL comparison while sending the corpus elsewhere
    # (Copilot review of openDox-code#26, round 5).
    configured = _configured_remote_url(git, REMOTE_NAME)
    if configured is None:
        raise RepositoryActRefused(
            f"the map records a remote for project {project_id} but the "
            f"repository at {row.location} has no {REMOTE_NAME!r}; re-attach "
            "the remote so the two agree before pushing")
    effective = _configured_remote_url(git, REMOTE_NAME, for_push=True)
    for what, found in (("fetches from", configured),
                        ("would push to", effective)):
        if found != row.remote_url:
            raise RepositoryActRefused(
                f"the repository at {row.location} {what} "
                f"{redact_credentials(found or '(nothing)')} under "
                f"{REMOTE_NAME!r} while the map records "
                f"{redact_credentials(row.remote_url)}. Nothing is pushed: the "
                "destination of record and the destination git would use are "
                "not the same place. Re-attach the remote to settle it.")

    # THE BRANCH IS THE REPOSITORY'S OWN AND IS NOT A PARAMETER. It was a
    # caller-supplied override defaulting to HEAD's branch, and nothing exposed
    # it — but `push_to_remote(..., branch="other")` would have pushed
    # `refs/heads/other` while HEAD, `LocalGitCorpus` and every read served
    # `main`, then reported success for a history the project is not (Copilot
    # review of openDox-code#26, round 5). It is the same reason `remote_name`
    # is a constant: a push destination the map cannot record is not a push
    # this act can make.
    branch = _pushable_branch(git, str(row.location))
    try:
        # THE ONE OPERATION THAT TOUCHES A NETWORK, and the only one with a
        # wall-clock bound: a stalled remote used to hold the request, the
        # repository and the caller's DATABASE TRANSACTION for as long as it
        # liked. `out_bounded` also refuses every interactive prompt, so a
        # remote that wants a password fails instead of waiting for one that is
        # never coming.
        git.out_bounded("push", REMOTE_NAME,
                        f"refs/heads/{branch}:refs/heads/{branch}",
                        timeout=PUSH_TIMEOUT_SECONDS)
    except GitCommandFailed as failed:
        # THE STORED URL IS REDACTED IN THE REFUSAL. A row written before
        # `refuse_credential_bearing_remote` existed can still carry a
        # credential, and this message reaches an API response (Copilot review
        # of openDox-code#26).
        raise RepositoryActRefused(
            f"the push to {redact_credentials(row.remote_url)} failed "
            f"({failed}); the project is unchanged and is still served from "
            f"{row.location}") from failed
    return row.remote_url
