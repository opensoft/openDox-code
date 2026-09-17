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
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opendox.corpus_adapter import CorpusRef
from opendox.runtime.identity import NotFoundError
from opendox.runtime.local_git_adapter import (
    ADAPTER_NAME,
    DEFAULT_BRANCH,
    GitCommandFailed,
    GitRunner,
    carries_a_control_character,
    git_available,
    git_identity,
    names_a_secret_parameter,
    open_no_follow_chain,
    redact_remote_url,
    runner_bound_to,
)

#: The ONE remote this runtime configures and pushes to. A constant and not a
#: parameter: `project_repositories` has a single `remote_url` column, so a
#: second remote would be a name the map cannot record and the push cannot find.
REMOTE_NAME = "origin"

#: `git config --unset-all`'s exit status for a key that is not there.
#: Measured on git 2.43.0, and it is the ONLY non-zero status this module reads
#: as success: every other one is a config that could not be written.
_GIT_CONFIG_KEY_ABSENT = 5

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
#: A BRACKETED IPv6 HOST ALREADY MATCHES, measured rather than assumed (Copilot
#: review of openDox-code#26, round 10, which reported that it does not): the
#: host class excludes `:` so the pattern cannot mistake a `scheme://` for
#: userinfo, and in `user@[::1]:repo` it matches the `[` and the very next
#: character is the `:` this form requires. Every bracketed IPv6 literal begins
#: with a hex group or a colon, so the form cannot avoid it.
#: `test_a_bracketed_ipv6_scp_remote_is_refused_like_any_other_userinfo` pins
#: it, because a property held by luck is one a later edit can lose.
_SCP_USERINFO = re.compile(r"^[^/:@]+@[^/:@]+:")

#: A remote URL longer than this is refused. NOT a style rule: the credential
#: predicate decodes each parameter name to a fixed point, which is quadratic
#: in the name's length, and `remote_url` is caller-controlled — so a nested
#: `%2525…` chain of unbounded length is work an attacker chooses for this
#: process (Copilot review of openDox-code#26, round 10, suppressed). Two
#: kilobytes is the conventional URL ceiling and is far above any real remote;
#: the bound is stated here, where the value enters, rather than inside the
#: predicate, which also reads git's own bounded stderr.
MAX_REMOTE_URL_CHARS = 2048

#: Transports whose "URL" is a COMMAND. `ext::<command>` runs it, and
#: `git-remote-<name>` helpers are resolved off PATH; git gates them behind
#: `protocol.<name>.allow`, whose default this runtime must not depend on —
#: measured on git 2.43.0: a direct `git push` to an `ext::` remote is refused
#: by default AND is executed when the repository or the host sets
#: `protocol.ext.allow=user` (Copilot review of openDox-code#26, round 10). So
#: the shape is refused where it would be stored, and the push also carries
#: `-c protocol.ext.allow=never` so an ambient policy cannot re-enable it for a
#: row written before this rule.
#: EVERY `<name>::<address>` FORM, not only the two built-ins. Git treats any
#: such URL as a REMOTE HELPER and resolves `git-remote-<name>` from `PATH`, so
#: `evil::anything` runs an installed `git-remote-evil` and
#: `protocol.ext.allow=never` says nothing about it (Copilot review of
#: openDox-code#26, round 12). Naming `ext` and `fd` alone was the narrow
#: reading of a general mechanism. A single colon — `https://…`, `host:path`,
#: `C:\repo` — is not this form and is unaffected.
#: MEASURED ON GIT 2.43.0 RATHER THAN READ OFF THE URL GRAMMAR, because the two
#: differ and the difference was a bypass. The review reported
#: `evil_helper::anything` as one (Copilot review of openDox-code#26, round
#: 13); it is NOT — git parses that as SSH to a host named `evil_helper`,
#: because `_` is not a scheme character. What IS one is a name beginning with
#: a DIGIT, which this pattern required to be a letter:
#:
#:     evil::anything          -> git: 'remote-evil' is not a git command
#:     9evil::anything         -> git: 'remote-9evil' is not a git command   <- MISSED
#:     ::anything              -> git: 'remote-' is not a git command        <- MISSED
#:     +evil::x .evil::x ev~il::x ev%il::x evil_helper::x -> ssh, not a helper
#:     -evil::x                -> git refuses it as an option
#:
#: So the helper route is taken for a prefix of `[A-Za-z0-9+.-]` whose FIRST
#: character is alphanumeric, and for the empty prefix. That is the predicate
#: now, and the table above is the evidence for each end of it.
_COMMAND_TRANSPORT = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9+.\-]*)?::")


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
    if len(remote_url) > MAX_REMOTE_URL_CHARS:
        raise RepositoryActRefused(
            f"the remote URL is longer than {MAX_REMOTE_URL_CHARS} characters "
            "and is refused unread; a remote this long is not a remote, and "
            "the credential check below is quadratic in what it is given")
    # A CONTROL CHARACTER IS REFUSED, A PLAIN SPACE IS NOT. A newline in a
    # remote URL is written into `.git/config` by `git remote add` and can
    # forge a second configuration line there, and a tab or a carriage return
    # hides the rest of a value from every line-oriented reader of this row —
    # none of them can appear in a URL that was percent-encoded. A SPACE can
    # legally appear in the one destination this act deliberately supports
    # unconstrained, a local path (`/srv/my repos/x.git`), so it is not refused
    # here; `local_git_adapter`'s parameter patterns step over whitespace
    # instead, which is what closes `…/x? token=…` for both halves of the
    # credential rule (Copilot review of openDox-code#26, round 10).
    # AND `isspace()` IS NOT "IS A CONTROL CHARACTER". ESC, DEL, NUL and the
    # rest of the C0/C1 sets are not whitespace, so they passed this check and
    # were stored in `remote_url` and written into `.git/config` — after which
    # a terminal reading the map's response interprets them and an ESC sequence
    # can rewrite what an operator sees (Copilot review of openDox-code#26,
    # round 13). The question is asked of the Unicode CATEGORY now: `Cc`
    # (control) and `Cf` (format — the bidirectional overrides, which reorder a
    # URL on screen without changing it), with the plain space kept legal
    # because a local path may contain one.
    # ONE PREDICATE, in the adapter, because the other half of this rule is
    # there: `redact_remote_url` refuses to PRINT a legacy value that answers
    # it, and two spellings of "control character" could disagree about the
    # same stored row (Copilot review of openDox-code#26, round 14).
    if carries_a_control_character(remote_url):
        raise RepositoryActRefused(
            "the remote URL contains a control character (a newline, tab, "
            "escape, or another C0/C1 or format character). It is not echoed "
            "here; percent-encode it or send the URL alone.")
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


def refuse_command_executing_remote(remote_url: str) -> None:
    """Refuse a remote whose "URL" is a COMMAND this process would run.

    `ext::sh -c …` is a git transport that EXECUTES its argument, in the
    process that pushes — this runtime's own — and `fd::` hands git a
    descriptor of the caller's choosing. Neither is a destination the map can
    mean, and an owner attaching one would be choosing a command for a server
    to run (Copilot review of openDox-code#26, round 10).

    AND IT IS THE WHOLE FORM, not those two names. `<name>::<address>` makes
    git resolve `git-remote-<name>` from `PATH`, so an installed helper — one
    the image ships, one a sibling package left there — is reachable through
    any spelling, and the `protocol.ext.allow` setting governs `ext` alone
    (Copilot review of openDox-code#26, round 12). `push_to_remote` asks this
    question again about the ROW it is about to push, because a row written
    before this rule is exactly the case the rule cannot reach.

    THE AMBIENT POLICY IS NOT THE GUARD. Measured on git 2.43.0: a direct `git
    push` to an `ext::` remote is refused by default, AND is executed the
    moment the repository or the host sets `protocol.ext.allow=user`. A
    runtime whose safety depends on a config value it does not set has no
    safety, so this refuses the shape where it would be stored and
    `push_to_remote` passes `-c protocol.ext.allow=never` for rows written
    before this rule existed.
    """
    if _COMMAND_TRANSPORT.match(remote_url.strip()):
        helper = remote_url.strip().split("::", 1)[0]
        raise RepositoryActRefused(
            f"the remote URL names a transport that runs a command: "
            f"`{helper}::` makes git resolve and execute `git-remote-{helper}` "
            "from PATH. Every `<name>::<address>` form does — `ext::` and "
            "`fd::` are only the two that ship with git — and this act "
            "attaches a destination, never an executable; use a URL or a "
            "filesystem path.")

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
    "refuse_command_executing_remote",
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
    # A NUL IS REFUSED HERE, not by `ValueError` three calls down. `Path`,
    # `os.open` and `os.mkdir` raise `ValueError` — NOT `OSError` — for an
    # embedded NUL, so this act's translation did not catch it and a malformed
    # project id reached the API as a 500 in place of the named refusal it
    # promises for every reason it will not create a repository (Copilot review
    # of openDox-code#26, round 17, suppressed). It is the same guard
    # `write_back` puts on `DocumentId.key`, one module over.
    if (not project_id or "/" in project_id or "\0" in project_id
            or project_id in {".", ".."}):
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
    #
    # AND IT IS TRANSLATED. `expanduser()` and `resolve()` both raise for a
    # root that cannot be read — a symlink loop, an ancestor that is not
    # searchable, a `~` with no home — and this line is reached by
    # `create_repository` before anything else, so a misconfigured
    # `OPENDOX_PROJECT_REPOSITORY_ROOT` reached the API as a 500 instead of the
    # named refusal this act promises for every reason it will not create a
    # repository (Copilot review of openDox-code#26, round 12, suppressed).
    # `RuntimeError` AS WELL AS `OSError`, and it is not defensive: MEASURED on
    # python 3.12, `Path.resolve()` turns a symlink LOOP into
    # `RuntimeError("Symlink loop from …")` rather than letting `ELOOP`
    # through, so an `except OSError` would have missed the very case this
    # translation is for. (The same measurement corrected the adapter's
    # `resolve`, which had the identical handler.)
    try:
        return (Path(root).expanduser().resolve() / project_id)
    except (OSError, RuntimeError) as exc:
        raise RepositoryActRefused(
            f"the configured repository root could not be resolved "
            f"({type(exc).__name__}); set OPENDOX_PROJECT_REPOSITORY_ROOT to a "
            "directory this process can read") from exc


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
    # AND THE PROBES THEMSELVES ARE TRANSLATED. `is_symlink()`, `lexists()`
    # and `exists()` all raise `PermissionError` for a path whose parent has
    # stopped being searchable, and `OSError` for a symlink loop — and they sat
    # OUTSIDE every handler, so a location this act could not inspect escaped
    # as a raw filesystem error where both callers translate only
    # `RepositoryActRefused` (Copilot review of openDox-code#26, round 12,
    # suppressed twice). The whole preflight asks its questions inside one
    # translation now, and a path that cannot be inspected is refused for
    # exactly the reason the emptiness check below is: this act cannot tell an
    # empty directory from somebody else's history.
    try:
        linked = location.is_symlink() or (os.path.lexists(location)
                                           and not location.exists())
        present = location.exists()
        a_directory = location.is_dir()
    except (OSError, RuntimeError) as exc:
        raise RepositoryActRefused(
            f"{location} could not be inspected ({type(exc).__name__}); this "
            "act will not create a repository at a path it cannot read, "
            "because it cannot tell an empty directory from somebody else's "
            "history") from exc
    if linked:
        raise RepositoryActRefused(
            f"{location} is a symbolic link. A repository is created at a real "
            "directory this act owns; writing through a link would put the "
            "project's history wherever the link points, which is a directory "
            "nobody accounted for.")
    if present and not a_directory:
        raise RepositoryActRefused(
            f"{location} exists and is not a directory, so this project's "
            "repository cannot be created there. Remove it, or point "
            "OPENDOX_PROJECT_REPOSITORY_ROOT somewhere else.")
    if a_directory:
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


def _mapped_repository(store: Any, project_id: str) -> Any:
    """This project's map row, or `None` where it has none.

    ONLY "no such row" IS CAUGHT. The first cut caught `Exception`, on the
    argument that any other store failure would be raised again by the
    `create_project_repository` on the very next line — which is true of THIS
    store and is not a property of a collaborator typed `Any`: a connection
    error would have been reported as "not mapped", and a non-transactional
    store could then have written a map row without ever having read the
    authoritative one (Copilot review of openDox-code#26, round 16). The
    store's own `NotFoundError` is imported instead; `opendox.runtime.identity`
    is stdlib-only by this package's import-weight contract, which
    `tests_runtime/test_runtime_surface.py` measures, so naming it here costs
    this module nothing it does not already carry.
    """
    try:
        return store.repository_for_project(project_id)
    except NotFoundError:
        return None


def create_repository(store: Any, *, project_id: str,
                      root: str | os.PathLike[str], actor: str,
                      branch: str = DEFAULT_BRANCH,
                      executable: str = "git") -> CreatedRepository:
    """Create this project's plain local git repository, and map the project to it.

    `store` is an `identity.CoordinationStore` over the CALLER'S transaction,
    so the row and everything else the caller writes commit together.
    """
    # THE MAP IS ASKED BEFORE THE PATH IS EVEN COMPUTED, and the reason is the
    # one this act has already applied twice below: the row holds the
    # AUTHORITATIVE fact, so a project that is already mapped must be refused
    # as "already mapped" (the store's `ConflictError`) rather than by a
    # symptom. `repository_location` is a symptom in exactly that sense — it
    # refuses an unreadable `OPENDOX_PROJECT_REPOSITORY_ROOT`, and an id that
    # cannot be a directory name — so a repeat create for a mapped project
    # answered "the configured repository root could not be resolved" on a host
    # whose root had since become unreadable and `ConflictError` on a host
    # where it had not: the same act giving two answers about one durable fact
    # (Copilot review of openDox-code#26, round 14). It is the `git_available`
    # finding one step further up, and it is the same fix.
    #
    # THE INSERT STILL DECIDES. This read is not a substitute for it: two
    # concurrent creates both see no row here, and the store's unique
    # constraint — which `create_project_repository` raises `ConflictError` out
    # of — is what settles the race. A row seen here can only make the refusal
    # arrive earlier, never make an insert unnecessary.
    mapped = _mapped_repository(store, project_id)
    location = (Path(mapped.location) if mapped is not None
                else repository_location(root, project_id))

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
        #
        # THE PARENTS MAY EXIST; THE LEAF IS CREATED EXCLUSIVELY. `exist_ok=True`
        # on the leaf made the check above a CHECK AND THE CREATE A SEPARATE
        # ACT: another process could replace the path with a symlink in
        # between, and `mkdir` would then succeed by following it — `git init
        # --bare .` writing the project's history into whatever the link
        # points at, which is the adoption `refuse_unusable_location` exists
        # to refuse (Copilot review of openDox-code#26, round 8). An exclusive
        # `mkdir` cannot follow a symlink: it fails with `FileExistsError`
        # whether the thing in the way is a link or a directory.
        #
        # AND THE MISSING PARENTS ARE CREATED THE SAME WAY THEY ARE OPENED.
        # `location.parent.mkdir(parents=True, exist_ok=True)` resolved the
        # chain BY PATHNAME, which follows every link in it: for
        # `/root/link/new/<id>` where `link` points outside the configured
        # root, that call created `<outside>/new` and only THEN did the
        # no-follow walk refuse — a refused act that had already written
        # directories into a tree nobody accounted for (Copilot review of
        # openDox-code#26, round 14, suppressed). `_open_no_follow_chain(...,
        # create=True)` makes each missing component with `dir_fd` inside the
        # component it has already opened with `O_NOFOLLOW`, so the first link
        # in the chain fails with `ELOOP` before anything is created.
        # THE LEAF IS CREATED AND OPENED RELATIVE TO A HELD PARENT DESCRIPTOR,
        # and the descriptor that is opened is the ONE this function then uses.
        # The first cut checked emptiness through a no-follow handle, CLOSED
        # it, and opened the path again for the run: a directory removed and
        # replaced between those two opens was described by both `fstat` and
        # `stat`, so the inode comparison compared the replacement with itself
        # and passed (Copilot review of openDox-code#26, round 12). One handle
        # from the check to the use is the only shape that has no such window.
        if os.mkdir in os.supports_dir_fd:
            # THE LEAF IS CREATED AND OPENED RELATIVE TO A HELD PARENT
            # DESCRIPTOR, and the descriptor that is opened is the ONE this
            # function then uses. The first cut checked emptiness through a
            # no-follow handle, CLOSED it, and opened the path again for the
            # run: a directory removed and replaced between those two opens was
            # described by both `fstat` and `stat`, so the inode comparison
            # compared the replacement with itself and passed (Copilot review
            # of openDox-code#26, round 12). One handle from the check to the
            # use is the only shape that has no such window.
            #
            # EXCLUSIVE, because an exclusive `mkdir` cannot follow a symlink:
            # it fails with `FileExistsError` whether the thing in the way is a
            # link or a directory (round 8). `dir_fd` means the lookup happens
            # in the directory this call holds rather than by re-walking a path
            # another process can re-point (round 12).
            parent = _open_no_follow_chain(location.parent, create=True)
            try:
                leaf = location.name
                try:
                    os.mkdir(leaf, dir_fd=parent)
                except FileExistsError:
                    pass
                owned = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY
                                | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
            finally:
                os.close(parent)
        else:
            # A PLATFORM WITHOUT `dir_fd`, and the weaker guarantee is stated
            # rather than assumed. `os.supports_dir_fd` excludes `mkdir` and
            # `open` on Windows, where they raise `NotImplementedError`; every
            # place this runtime is deployed (both `deploy/` shapes) and every
            # runner its CI uses is Linux, where both are supported. Where they
            # are not, this is the shape the act had before: an exclusive
            # create and a no-follow open BY NAME, which still refuses a
            # symlink and (with the inode comparison below) a re-pointed path,
            # and leaves only the window between the two calls. Same policy as
            # `_runner_bound_to`'s `/proc/self/fd` → `/dev/fd` → pathname
            # ladder: take the strongest the platform offers, and say which.
            location.parent.mkdir(parents=True, exist_ok=True)
            try:
                location.mkdir()
            except FileExistsError:
                pass
            owned = os.open(location, os.O_RDONLY | os.O_DIRECTORY
                            | getattr(os, "O_NOFOLLOW", 0))
    except RepositoryActRefused:
        raise
    except OSError as exc:
        raise RepositoryActRefused(
            f"the directory {location} could not be created ({exc}); the map "
            "row is rolled back with the caller's transaction") from exc
    try:
        # EMPTINESS IS ASKED OF THE DESCRIPTOR, not of the name. `os.listdir`
        # takes a file descriptor, so this is a question about the directory
        # this function is holding open — the legal case
        # `refuse_unusable_location` allows (an empty directory this act may
        # use) verified on the object that will be initialized, not on a
        # pathname that can be re-pointed between the two.
        # AND THIS PROBE IS TRANSLATED TOO. `os.listdir` on a descriptor can
        # fail — `EIO` on a failing filesystem, `ENOTDIR` if the object under
        # the handle is no longer a directory — and it sat in a `try/finally`
        # with no `OSError` handler, so the one check that decides whether this
        # act may use the directory escaped as an API 500 instead of the named
        # refusal this act promises for every reason it will not create a
        # repository (Copilot review of openDox-code#26, round 16, suppressed).
        try:
            occupied = os.listdir(owned)
        except OSError as exc:
            raise RepositoryActRefused(
                f"{location} could not be read through the descriptor this act "
                f"opened ({type(exc).__name__}); it will not create a "
                "repository in a directory it cannot tell empty from full"
            ) from exc
        if occupied:
            raise RepositoryActRefused(
                f"{location} is not empty; this act creates a "
                "repository at a directory it owns and adopts none")
        # AND THE NAME STILL LEADS HERE. The descriptor decides what is
        # written; this comparison decides whether the map row's `location`
        # will find it again, and a path re-pointed underneath the act is
        # refused rather than recorded.
        # ASKED WITHOUT FOLLOWING A LINK, which is what makes it a comparison
        # of NAMES rather than of destinations. `os.stat(location)` follows
        # every component, so the one substitution this check exists to catch —
        # the verified directory moved aside and `location` replaced with a
        # SYMLINK back to it — returned the same device and inode and passed,
        # putting a re-pointable name in the durable map (Copilot review of
        # openDox-code#26, round 14, suppressed). `_directory_by_name` walks
        # the chain with `O_NOFOLLOW` instead.
        # AND THIS COMPARISON'S OWN FAILURE IS NAMED. `os.stat(location)`
        # raises `FileNotFoundError` for a path removed under the act and
        # `PermissionError` for an ancestor that stopped being searchable, and
        # it sat in a `try/finally` with no `OSError` handler — so the one
        # check that decides whether the map row will find this directory again
        # escaped as a 500 (Copilot review of openDox-code#26, round 12,
        # suppressed twice). A path that cannot be re-examined is refused for
        # the same reason a path that changed is.
        try:
            created = os.fstat(owned)
            seen = _directory_by_name(location)
        except OSError as exc:
            raise RepositoryActRefused(
                f"{location} could not be re-examined after it was created "
                f"({type(exc).__name__}); the map row must name a directory "
                "this act can still find, so nothing is written") from exc
        if (created.st_dev, created.st_ino) != (seen.st_dev, seen.st_ino):
            raise RepositoryActRefused(
                f"{location} is not the directory this act created; the path "
                "changed underneath it and nothing is written")
        # AND THE HANDLE IS HELD THROUGH THE WHOLE INITIALIZATION, because a
        # check that is released before the use is a check with a window in
        # it. The comparison above proved the PATH still named the directory
        # this act created; the descriptor below names that directory itself,
        # and git is given the descriptor — so a final component replaced
        # between this line and `git init` (by a symlink, or by another real
        # directory) cannot become the place the history is written (Copilot
        # review of openDox-code#26, round 10). Every git call of this act is
        # inside the handle's lifetime for the same reason.
        git = _runner_bound_to(owned, location, executable)
        commit = _initialize_with(git, location, project_id=project_id,
                                  actor=actor, branch=branch)
        # AND THE NAME STILL LEADS HERE AFTERWARDS, which is a different
        # question from the one asked above. The descriptor decides where the
        # history was written and the handle held it safely throughout — but
        # `create_repository` records `location` in the map row, so a path
        # re-pointed DURING the initialization leaves the row naming a
        # directory the history is not in, and the next
        # `LocalGitCorpus.resolve(corpus_ref_for(row))` serves the decoy
        # (Copilot review of openDox-code#26, round 13). Asked once more, at
        # the last moment the act can still refuse: the caller's transaction
        # rolls the row back with this exception.
        try:
            settled = _directory_by_name(location)
        except OSError as exc:
            raise RepositoryActRefused(
                f"{location} could not be re-examined after the repository was "
                f"initialized ({type(exc).__name__}); the map row must name "
                "the directory the history is in, so the act is refused and "
                "the row rolls back") from exc
        if (created.st_dev, created.st_ino) != (settled.st_dev,
                                                settled.st_ino):
            raise RepositoryActRefused(
                f"{location} no longer names the directory this act "
                "initialized; the path changed while the repository was being "
                "created, so the map row would point at another directory. "
                "Nothing is recorded.")
        return commit
    finally:
        os.close(owned)


#: MOVED DOWN TO THE ADAPTER, and re-bound here under the names this module
#: has always used. `local_git_adapter` owns `GitRunner` and its `inherit_fd`,
#: and `write_back` needs the same check-and-use binding this act invented —
#: so the implementation lives with the runner and there is ONE of it (Copilot
#: review of openDox-code#26, round 16).
_open_no_follow_chain = open_no_follow_chain
_runner_bound_to = runner_bound_to


def _directory_by_name(location: Path) -> os.stat_result:
    """`stat` for `location` reached WITHOUT following a symlink anywhere.

    The identity checks in `initialize_repository` compare this with the
    `fstat` of the descriptor the act is holding, and the substitution they are
    for — the verified directory moved aside and the name replaced with a
    symlink back to it — is invisible to `os.stat`, which follows the link and
    reports the very inode being compared.

    THE PLATFORM LADDER IS STATED RATHER THAN ASSUMED, as it is in
    `_runner_bound_to`: where `os.open` takes a `dir_fd` (every place this
    runtime is deployed and every runner its CI uses) the whole chain is walked
    with `O_NOFOLLOW`, so an ancestor swapped for a link is refused too; where
    it does not, `lstat` still refuses a re-pointed LEAF and an ancestor is the
    weaker guarantee that platform can give.
    """
    if os.open in os.supports_dir_fd:
        handle = _open_no_follow_chain(location)
        try:
            return os.fstat(handle)
        finally:
            os.close(handle)
    return os.lstat(location)


def _initialize_with(git: GitRunner, location: Path, *, project_id: str,
                     actor: str, branch: str) -> str:
    """`initialize_repository`'s git half, on a runner its caller chose."""
    try:
        # BARE, and it is the decision `local_git_adapter`'s header argues in
        # full: this repository is storage openDox MANAGES (RULING C3's own
        # verb), the corpus is its history, and a checkout beside it would be a
        # second answer to "what does this project contain" that the adapter is
        # forbidden to keep up to date. A human who wants a checkout clones it;
        # `push_to_remote` below works from a bare repository unchanged.
        # AND IT IS RULED, not this act's preference:
        # RULED openxFactory#656 comment 5701772032 (Brett Heap, 2026-09-16, by interactive multi-choice)
        # answers Q-R1 — the repository this act creates STAYS BARE.
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



@contextmanager
def _bound_to_mapped_repository(row: Any,
                                executable: str) -> Iterator[GitRunner]:
    """A runner on the mapped directory, held OPEN across check and use.

    `_refuse_unless_repository_root` proved a fact about a PATHNAME and both
    callers then re-opened that pathname for every `git` they ran, so a rename
    or a symlink swap in between could still send `remote set-url` or the push
    into another repository — the check and the use were two different objects
    (Copilot review of openDox-code#26, round 16). The directory is opened
    `O_NOFOLLOW` component by component and git is handed `/proc/self/fd/<n>`
    for that descriptor, which is the binding `initialize_repository` already
    uses and which `runner_bound_to` states the platform ladder for.
    """
    location = Path(row.location)
    try:
        handle = open_no_follow_chain(location)
    except (OSError, RuntimeError) as exc:
        raise RepositoryActRefused(
            f"{location} could not be opened without following a link "
            f"({type(exc).__name__}); this act will not run git against a "
            "directory it cannot hold open") from exc
    try:
        git = runner_bound_to(handle, location, executable)
        _refuse_unless_repository_root(git, location)
        yield git
    finally:
        os.close(handle)


def _without(text: str, secret: str | None) -> str:
    """`text` with a KNOWN value taken out of it, wherever it appears.

    The credential rule's pattern half cannot match a value that spans a line,
    and deliberately so. A caller that HOLDS the value does not need a pattern
    (Copilot review of openDox-code#26, round 17).
    """
    if not secret:
        return text
    return text.replace(secret, "<redacted-url>")


def _refuse_unless_repository_root(git: GitRunner, location: Path) -> None:
    """Refuse a mapped location that is INSIDE a repository instead of being one.

    `git -C <path>` WALKS UP. `LocalGitCorpus.resolve` refuses that for reads
    and writes (RULED 5714365086 Q-F3) and these acts did not, although they
    are the ones that RECONFIGURE and PUSH: a row whose directory had been
    removed, or written by hand as `checkout/subdir`, let `attach_remote` set
    `remote.origin.url` on the ENCLOSING checkout and `push_to_remote` push the
    enclosing checkout's branch to the project's remote (Copilot review of
    openDox-code#26, round 14). One rule for the corpus and the acts on it.

    The root is asked the way the adapter asks it: a BARE repository's root is
    its git directory — the shape this act creates — and a repository with a
    work tree has `--show-toplevel`; `--show-toplevel` is a fatal error inside
    a bare one, so the question is chosen rather than guessed.

    ASKED OF THE RUNNER THE CALLER WILL USE, never of a path this function
    opens for itself; see `_bound_to_mapped_repository`.
    """
    try:
        bare = git.out("rev-parse", "--is-bare-repository").decode().strip()
        question = ("--absolute-git-dir" if bare == "true"
                    else "--show-toplevel")
        root = Path(git.out("rev-parse", question)
                    .decode("utf-8", "surrogateescape").strip()).resolve()
        named = location.resolve()
    except GitCommandFailed as failed:
        raise RepositoryActRefused(
            f"the repository at {location} could not be identified "
            f"({failed}); this act runs git against the mapped directory and "
            "will not run it against a directory it cannot account for"
        ) from failed
    except (OSError, RuntimeError) as exc:
        raise RepositoryActRefused(
            f"{location} could not be resolved ({type(exc).__name__}); this "
            "act will not run git against a path it cannot read") from exc
    if root != named:
        raise RepositoryActRefused(
            f"the mapped location {location} is not a repository: it is INSIDE "
            f"the one at {root}. Nothing is configured and nothing is pushed, "
            "because git would have run against that repository instead — "
            "re-create this project's repository, or map it to its own root.")


def _local_git_row(store: Any, project_id: str, *,
                   for_update: bool = False) -> Any:
    """The map row, REFUSED unless this adapter is the one that owns it.

    The map carries an `adapter` column precisely so a project can be served by
    something other than a plain local git repository, and these acts ignored
    it: a row belonging to a governed factory's adapter would have had `git
    remote set-url` and `git push` run against its opaque `location` (Copilot
    review of openDox-code#26). A row this adapter does not own is somebody
    else's to act on.

    AND OWNING THE ROW IS NOT THE SAME AS THE ROW NAMING A REPOSITORY — see
    `_bound_to_mapped_repository`, which is the second half of the question
    both callers were asking only half of, asked on the handle they then use.
    """
    # `for_update` LOCKS the row for the rest of the caller's transaction —
    # see the store's own note; the acts that read a destination and then use
    # it take it, so a concurrent `attach_remote` cannot move the destination
    # between the check and the push.
    row = store.repository_for_project(project_id, for_update=for_update)
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
    refuse_command_executing_remote(remote_url)
    row = _local_git_row(store, project_id, for_update=True)
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
    with _bound_to_mapped_repository(row, executable) as git:
        return _attach_remote_with(git, row, updated, remote_url,
                                   remote_name)


def _attach_remote_with(git: GitRunner, row: Any, updated: Any,
                        remote_url: str, remote_name: str) -> Any:
    """`attach_remote`'s git half, on a runner bound to an open directory."""
    try:
        existing = git.run("remote", "get-url", remote_name)
        # AND THE REMOTE'S EXISTENCE IS ASKED OF THE CONFIG SECTION, not of
        # `get-url` alone. A repository carrying `remote.origin.pushurl` and no
        # `remote.origin.url` — legacy, or hand-edited — is the case, and what
        # git does with it is version-dependent, so this does not depend on the
        # answer: MEASURED on git 2.43.0, `git remote get-url origin` there
        # exits 0 and prints the literal `origin` (`git remote -v` shows the
        # fetch URL empty), so the repair branch was already taken and
        # `--replace-all` created the missing key. Where a git exits non-zero
        # instead, this used to fall through to `remote add`, which fails
        # ("remote origin already exists") and left the one repair this act
        # offers unable to reach the one state that needs it (Copilot review of
        # openDox-code#26, round 12, suppressed). `--get-regexp` answers "is
        # there a remote here" from the config itself.
        section = git.run("config", "--get-regexp",
                          "^remote\\." + re.escape(remote_name) + "\\.")
        if existing.returncode == 0 or section.returncode == 0:
            # `config --replace-all`, NOT `remote set-url`. Git permits several
            # `remote.origin.url` entries, and `set-url` on a remote that has
            # them does not replace the first — measured on git 2.43.0, it
            # FAILS: "fatal: could not set 'remote.origin.url': has multiple
            # values". So a repository in that state (a legacy remote, a
            # hand-edited config) could not be repaired by the one repair this
            # act offers, while `push_to_remote` refused every push because
            # `get-url --push --all` returned two destinations (Copilot review
            # of openDox-code#26, round 10). `--replace-all` collapses every
            # value to the one URL the map records, which is the state the map
            # can describe.
            git.out("config", "--replace-all", f"remote.{remote_name}.url",
                    remote_url)
        else:
            git.out("remote", "add", remote_name, remote_url)
        # AND EVERY `pushurl` IS CLEARED, because `set-url` writes the FETCH
        # url alone. A repository carrying a legacy or hand-added
        # `remote.origin.pushurl` — the very state `push_to_remote` refuses —
        # kept it through this act, so the destination of record could not be
        # repaired by re-attaching, which is the one repair this act offers
        # (Copilot review of openDox-code#26, round 6).
        #
        # AND ONLY *ONE* NON-ZERO STATUS IS "NOTHING TO UNSET". This ignored
        # every failure, so a locked config, a read-only file or a malformed
        # section left a stale `pushurl` in place while the map row committed
        # and the attach reported success — after which the next push goes to
        # the wrong destination or is refused, which is the state this line
        # exists to clear (Copilot review of openDox-code#26, round 10,
        # suppressed twice). Measured on git 2.43.0: `config --unset-all` of an
        # absent key exits 5, and that is the only status this accepts.
        cleared = git.run("config", "--unset-all",
                          f"remote.{remote_name}.pushurl")
        if cleared.returncode not in (0, _GIT_CONFIG_KEY_ABSENT):
            raise GitCommandFailed(
                ("config", "--unset-all", f"remote.{remote_name}.pushurl"),
                cleared)
    except GitCommandFailed as failed:
        raise RepositoryActRefused(
            f"the remote {remote_name!r} could not be attached to "
            f"{row.location} ({failed})") from failed
    return updated


def _configured_remote_url(git: GitRunner, remote_name: str, *,
                           for_push: bool = False) -> str | list[str] | None:
    """What git has under `<remote_name>`, or None when it has no such remote.

    `for_push` asks for the EFFECTIVE PUSH URL. `git push` uses
    `remote.<name>.pushurl` when one is configured and falls back to the fetch
    URL when none is, so the fetch URL alone is not the destination: a stale or
    hand-added `pushurl` passed the map comparison and sent the corpus
    somewhere else while the API reported the mapped URL (Copilot review of
    openDox-code#26, round 5). `--push` is git's own answer to "where would a
    push go", so this asks git rather than reimplementing the fallback.
    """
    arguments = ("remote", "get-url", "--push", "--all", remote_name) if (
        for_push) else ("remote", "get-url", remote_name)
    existing = git.run(*arguments)
    if existing.returncode != 0:
        return None
    if not for_push:
        return existing.stdout.decode("utf-8", "replace").strip() or None
    # `--all`, AND EVERY LINE IS ANSWERED FOR. Git permits several
    # `remote.origin.pushurl` entries and a push is sent to EACH of them, so
    # `get-url --push` — which prints only the first — let an extra push URL
    # match the map while the corpus also went to an unrecorded destination
    # (Copilot review of openDox-code#26, round 6).
    #
    # AND THE LIST IS RETURNED AS A LIST. It used to be joined with `" and "`
    # and compared against the map row as one string, which is not injective:
    # a mapped local path `a and b` equals the join of push URLs `a` and `b`,
    # so a repository pushing to two unrecorded destinations could pass the
    # comparison (Copilot review of openDox-code#26, round 13). The caller
    # requires EXACTLY ONE and compares that one; a delimiter decides nothing.
    return [line.strip() for line
            in existing.stdout.decode("utf-8", "replace").splitlines()
            if line.strip()] or None


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
    # `surrogateescape`, NOT `replace`. A ref name is BYTES — git forbids only
    # a short list of characters — and `replace` turns a byte it cannot decode
    # into U+FFFD, so the branch this act then PUSHES is a different name from
    # the one HEAD points at, and the push fails naming a ref that does not
    # exist. (The review reported a strict decode raising `UnicodeDecodeError`
    # into a 500; this decode was never strict — what it did was quieter and
    # wrong in a way a 500 is not.) `surrogateescape` round-trips through
    # `subprocess`, which encodes arguments the same way (Copilot review of
    # openDox-code#26, round 17).
    ref = symbolic.stdout.decode("utf-8", "surrogateescape").strip()
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
    # LOCKED, and held for the whole check-and-push. These comparisons and the
    # push that follows them are one act: without the lock a concurrent
    # `attach_remote` could move the map and `origin` in between, so the corpus
    # went to the newly attached destination while this call returned the stale
    # URL — defeating the destination-of-record guarantee the comparison exists
    # to make (Copilot review of openDox-code#26, round 6).
    row = _local_git_row(store, project_id, for_update=True)
    if not row.remote_url:
        raise RepositoryActRefused(
            f"project {project_id} has no attached remote; attach one first "
            "(RULING C3: a remote can be attached later, and the move is then "
            "a push)")
    # THE ROW IS ASKED THE SAME QUESTION `attach_remote` ASKS, because this act
    # deliberately keeps a row written before that rule pushable — and a
    # `<name>::<address>` row would then hand `git push` a remote HELPER to
    # run. `-c protocol.ext.allow=never` below covers `ext` and says nothing
    # about `git-remote-evil` (Copilot review of openDox-code#26, round 12).
    refuse_command_executing_remote(row.remote_url)
    with _bound_to_mapped_repository(row, executable) as git:
        return _push_to_remote_with(git, row)


def _push_to_remote_with(git: GitRunner, row: Any) -> str:
    """`push_to_remote`'s git half, on a runner bound to an open directory."""

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
    # THE INSPECTION IS INSIDE A HANDLER, like every other git call in this
    # module. `_configured_remote_url` and `_pushable_branch` ran outside one,
    # so a git that disappeared or became unusable after the map lookup let
    # `GitCommandFailed` escape — and the API translates only
    # `RepositoryActRefused`, so `/push` answered 500 instead of the named
    # refusal this act promises for a missing git runtime (Copilot review of
    # openDox-code#26, round 6).
    try:
        configured = _configured_remote_url(git, REMOTE_NAME)
        destinations = _configured_remote_url(git, REMOTE_NAME, for_push=True)
        branch = _pushable_branch(git, str(row.location))
    except GitCommandFailed as failed:
        raise RepositoryActRefused(
            f"the repository at {row.location} could not be inspected before "
            f"the push ({failed}); nothing is pushed") from failed
    if configured is None:
        raise RepositoryActRefused(
            f"the map records a remote for project {row.project_id} but the "
            f"repository at {row.location} has no {REMOTE_NAME!r}; re-attach "
            "the remote so the two agree before pushing")
    # EXACTLY ONE PUSH DESTINATION, ASKED AS A COUNT and not as a string. A
    # repository configured with two `pushurl` entries pushes to BOTH, and a
    # comparison of a joined string against the map row can be satisfied by a
    # map row that happens to look like the join (round 13).
    if destinations is not None and len(destinations) != 1:
        raise RepositoryActRefused(
            f"the repository at {row.location} would push to "
            f"{len(destinations)} destinations under {REMOTE_NAME!r} "
            f"({', '.join(redact_remote_url(url) for url in destinations)}) "
            f"while the map records one. Nothing is pushed: a destination the "
            "map cannot record is a destination this act cannot make. "
            "Re-attach the remote to settle it.")
    effective = destinations[0] if destinations else None
    for what, found in (("fetches from", configured),
                        ("would push to", effective)):
        if found != row.remote_url:
            raise RepositoryActRefused(
                f"the repository at {row.location} {what} "
                f"{redact_remote_url(found or '(nothing)')} under "
                f"{REMOTE_NAME!r} while the map records "
                f"{redact_remote_url(row.remote_url)}. Nothing is pushed: the "
                "destination of record and the destination git would use are "
                "not the same place. Re-attach the remote to settle it.")

    # THE BRANCH IS THE REPOSITORY'S OWN AND IS NOT A PARAMETER (resolved in
    # the handler above). It was a caller-supplied override defaulting to
    # HEAD's branch, and nothing exposed it — but
    # `push_to_remote(..., branch="other")` would have pushed
    # `refs/heads/other` while HEAD, `LocalGitCorpus` and every read served
    # `main`, then reported success for a history the project is not (Copilot
    # review of openDox-code#26, round 5). It is the same reason `remote_name`
    # is a constant: a push destination the map cannot record is not a push
    # this act can make.
    try:
        # THE ONE OPERATION THAT TOUCHES A NETWORK, and the only one with a
        # wall-clock bound: a stalled remote used to hold the request, the
        # repository and the caller's DATABASE TRANSACTION for as long as it
        # liked. `out_bounded` also refuses every interactive prompt, so a
        # remote that wants a password fails instead of waiting for one that is
        # never coming.
        # `-c protocol.ext.allow=never` BEFORE THE SUBCOMMAND, and it is not
        # belt and braces for the refusal above: that refusal covers what this
        # act STORES, and a row written before it — or by a future caller of
        # the store — still reaches this push. Git's `ext::` transport runs its
        # argument as a command in THIS process, gated by a config value the
        # host sets; measured on git 2.43.0, `protocol.ext.allow=user` in the
        # repository's own config is enough to execute it (Copilot review of
        # openDox-code#26, round 10). A command-line `-c` outranks every
        # config file, so the policy travels with the push instead of being
        # assumed of the machine.
        # AND THE RECEIVE-PACK IS NAMED ON THE COMMAND LINE. `git push` runs
        # the destination's `receive-pack`, and for a LOCAL or `file://`
        # destination it runs it HERE — as a program chosen by
        # `remote.<name>.receivepack` in the pushing repository's own config.
        # The repositories this service manages are writable by it and by
        # whoever can reach their directory, so that key was a command this
        # runtime would execute on every push, which is the same class of
        # defect as the `ext::` transport and the `pre-push` hook and was
        # covered by neither (Copilot review of openDox-code#26, round 16).
        # `--receive-pack` on the command line outranks the config value.
        git.out_bounded("-c", "protocol.ext.allow=never",
                        "push", "--receive-pack=git-receive-pack",
                        REMOTE_NAME,
                        f"refs/heads/{branch}:refs/heads/{branch}",
                        timeout=PUSH_TIMEOUT_SECONDS)
    except GitCommandFailed as failed:
        # THE STORED URL IS REDACTED IN THE REFUSAL. A row written before
        # `refuse_credential_bearing_remote` existed can still carry a
        # credential, and this message reaches an API response (Copilot review
        # of openDox-code#26).
        # AND GIT'S OWN STDERR HAS THE KNOWN DESTINATION TAKEN OUT OF IT.
        # `GitCommandFailed` redacts its stderr with `redact_credentials`,
        # whose userinfo class excludes a newline on purpose (round 14: a
        # pattern cannot tell a URL's own newline from a diagnostic's), so a
        # LEGACY row holding `https://user:secret\n@host/repo` could still ride
        # the failure text git echoes back (Copilot review of openDox-code#26,
        # round 17, suppressed). This path does not need a pattern: it KNOWS
        # the destination, so the literal value is removed before the text is
        # exposed.
        raise RepositoryActRefused(
            f"the push to {redact_remote_url(row.remote_url)} failed "
            f"({_without(str(failed), row.remote_url)}); the project is "
            f"unchanged and is still served from {row.location}") from failed
    return row.remote_url
