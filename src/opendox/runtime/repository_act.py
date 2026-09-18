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

import dataclasses
import os
import re
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from opendox.corpus_adapter import CorpusRef
from opendox.runtime import config
from opendox.runtime.identity import NotFoundError
from opendox.runtime.local_git_adapter import (
    ADAPTER_NAME,
    DEFAULT_BRANCH,
    GitCommandFailed,
    GitRunner,
    carries_a_control_character,
    decoded_path,
    decoded_ref_name,
    git_available,
    git_identity,
    carries_a_credential,
    PlatformCannotGuardPaths,
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
#: THE USER PORTION ADMITS A COLON, and the host portion still does not.
#: `user:secret@host:path` is exactly the credential-carrying shape this rule
#: exists for, and the colon in the pre-`@` half made the old class miss it —
#: so `git remote add` persisted the secret in `.git/config` and in the map row
#: every signed-in caller can read (Copilot review of openDox-code#26, round
#: 31, suppressed). Widening the USER half cannot make the pattern claim a
#: URL: `[^/@]+` cannot cross the `//` of a `scheme://`.
_SCP_USERINFO = re.compile(r"^[^/@]+@[^/:@]+:")

#: A remote URL longer than this is refused — `config.MAX_REMOTE_URL_CHARS`,
#: which is the one declaration and carries the reasoning. It was declared
#: HERE, where the value enters, until the redaction of a STORED value needed
#: the same number: a legacy row passes no refusal, so the bound could not stay
#: in the refusal alone (Copilot review of openDox-code#26, at `4156f233`).
#: The name stays because this is where callers and refusal messages say it.
MAX_REMOTE_URL_CHARS = config.MAX_REMOTE_URL_CHARS

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
#: `local_git_adapter.carries_a_credential` — which is the REDACTOR ITSELF, so
#: the storing rule and the printing rule cannot answer it differently. Naming
#: one of the redactor's three patterns instead (`names_a_secret_parameter`)
#: is how they came apart a third time: that one is positionally anchored, so
#: `host=db password=hunter2 dbname=x` was stored verbatim in this column and
#: redacted in every read-back of it (independent adversarial review of
#: openDox-code#26, A26-3).


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
    # THE SAME QUESTION THE REDACTOR ASKS, and asked by asking IT. This branch
    # consulted one of the redactor's three patterns, and that one is
    # positionally anchored — so `host=db password=hunter2 dbname=x` was
    # ACCEPTED and stored verbatim in the column whose refusal text two
    # paragraphs up says it is "stored durably with nothing to rotate it",
    # while every read-back of it was dutifully redacted (independent
    # adversarial review of openDox-code#26, A26-3). A value this act would
    # refuse to PRINT is a value it must refuse to STORE, and the two cannot
    # drift again because there is now one predicate and it is the printer.
    if carries_a_credential(remote_url):
        raise RepositoryActRefused(
            "the remote URL carries a credential — a credential-shaped query "
            "or fragment parameter, or a keyword/value password. Userinfo is "
            "not the only place a secret hides, and this column is read back "
            "to every authenticated caller and stored with nothing to rotate "
            "it; give this act the URL alone and let git's own credential "
            "machinery supply the rest.")


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
    #
    # AND THE VALUE IS NOT ECHOED BACK. This branch is the one place in this
    # act that is reached by an identifier NOTHING has validated — every other
    # message naming a project id names one the map already holds — and it put
    # that identifier straight into a refusal that the CLI prints and the API
    # returns. The redactors are shaped for URLs and for libpq conninfo, not
    # for arbitrary caller text, and they do not cover it: MEASURED, both
    # `'user:secret@host/path'` and `'//user:pw@h/x'` reach this branch (each
    # holds a `/`) and come back through `redact_credentials` VERBATIM, secret
    # included (Copilot review of openDox-code#26, round 19). The report named
    # `https://user:secret\n@host`, which `repr` happens to rescue by escaping
    # the newline into a form the URL pattern then matches — the class is real
    # even where that one example is not. A path-component rule has nothing to
    # say that needs the value: it says WHICH rule was broken, and the caller
    # already holds what it sent.
    #
    # AND IT IS A SINGLE NATIVE PATH COMPONENT, judged by the STRICTEST
    # flavour rather than by this host's. `/` is not the only separator a
    # `Path` join honours: on Windows `PureWindowsPath("C:/srv/projects") /
    # "C:\\outside"` is `C:\\outside` — the root is discarded entirely — and
    # `"..\\outside"` walks out of it, while this module's own fallback says
    # the package is meant to run there (Copilot review of openDox-code#26,
    # round 21). Asking `PureWindowsPath` on every host means the answer does
    # not depend on where the check happens to run.
    windows = PureWindowsPath(project_id) if project_id else None
    reason = ("is empty" if not project_id
              else "holds a '/'" if "/" in project_id
              else "holds a NUL" if "\0" in project_id
              else "is '.' or '..'" if project_id in {".", ".."}
              # `windows.root` IS IN THIS PREDICATE, and it is not redundant
              # with `is_absolute()`: MEASURED on python 3.12,
              # `PureWindowsPath(r"\\outside")` has `drive=''`, `root='\\'`
              # and `is_absolute() == False` — a ROOT-RELATIVE path, which is
              # not absolute because it names no drive, and which discards the
              # configured parent all the same:
              # `PureWindowsPath("C:/srv/projects") / r"\\outside"` is
              # `C:\\outside` (Copilot review of openDox-code#26, round 29).
              else "is not a single path component"
              if (windows is not None
                  and (windows.drive or windows.root or windows.is_absolute()
                       or len(windows.parts) != 1))
              # A CONTROL CHARACTER, because git terminates a pathname with a
              # newline and `rev-parse` has no `-z`: a location whose name
              # contained one could not be read back unambiguously, and the
              # root comparison every act makes is that read (Copilot review of
              # openDox-code#26, round 22). It is the same predicate
              # `refuse_command_executing_remote` uses, for a related reason —
              # a value an operator reads as two lines.
              else "holds a control character"
              if carries_a_control_character(project_id)
              else None)
    if reason is not None:
        raise RepositoryActRefused(
            f"that project id {reason}, so it is not a usable project id for "
            "a directory name (the value is not echoed: it is caller-"
            "controlled text and this refusal is evidence)")
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
    #
    # AND `ValueError`, for the same reason the project id is checked for a NUL
    # above: `Path.resolve()` raises it — NOT `OSError` — for an embedded NUL
    # in the ROOT, so a malformed `OPENDOX_PROJECT_REPOSITORY_ROOT` reached the
    # API as a 500 in place of the refusal this act promises (Copilot review of
    # openDox-code#26, round 21). MEASURED on python 3.12:
    # `Path("/tmp/root\x00x").expanduser().resolve()` raises
    # `ValueError("embedded null byte")`.
    try:
        return (Path(root).expanduser().resolve() / project_id)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RepositoryActRefused(
            f"the configured repository root could not be resolved "
            f"({type(exc).__name__}); set OPENDOX_PROJECT_REPOSITORY_ROOT to a "
            "directory this process can read") from exc


#: The mode this act creates a repository directory with, and then ENFORCES.
#:
#: `os.mkdir`'s default is `0o777 & ~umask`, so without this the mode of the
#: configured root, of each project's repository and of everything `git init`
#: makes under it was a property of whatever umask the process inherited —
#: MEASURED: `0755` at umask 022, `0775` at 002, and `0777` at 000, with
#: `config` at `0666`. The shipped Kubernetes shape is safe today because the
#: pod runs as a single uid with a private volume, which makes the answer
#: accidental rather than decided (independent adversarial review of
#: openDox-code#26, A26-5). `0o700`: this act's process owns the store, and a
#: second container sharing the `fsGroup`, a different base image or an
#: operator's `umask 0` in a `runtime init` shell no longer change the answer.
REPOSITORY_DIRECTORY_MODE = 0o700


def refuse_unusable_location(location: Path) -> bool:
    """Refuse a path that is not an empty (or absent) directory, BY NAME.

    Returns whether the location was THERE when it was asked — an empty
    directory this act may adopt (`True`) or nothing at all (`False`). The
    caller needs that answer to tell one `FileExistsError` from another: see
    `initialize_repository`, where "it was absent a moment ago and exists now"
    is a race and "it was an empty directory and still is" is the documented
    case.

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
    return present


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
    # NEITHER VALUE MAY FORGE A LINE IN THE FIRST COMMIT, and the check is here
    # — BEFORE `git init` — because "nothing is created" has to be true.
    # `initialize_repository` is public and does not go through
    # `repository_location`'s validation, and the API hands `actor` an
    # authenticated DISPLAY NAME, so a newline in either wrote extra lines into
    # the repository's first and permanent commit, where a reader cannot tell
    # them from the act's own (Copilot review of openDox-code#26, round 33: one
    # thread and one "previously missed"). The adapter refuses the same shapes
    # at the write path; this is that rule at the create path, raised as this
    # module's own refusal because that is what its callers catch.
    for field, value in (("project id", str(project_id)), ("actor", actor)):
        if carries_a_control_character(value):
            raise RepositoryActRefused(
                f"the {field} contains a control character, and it is written "
                "into this repository's first commit message and identity, "
                "where a newline forges a line a reader of the durable history "
                "cannot tell from the act's own; nothing is created")
    was_there = refuse_unusable_location(location)
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
                    # THE MODE IS DECLARED AND THEN ENFORCED, because neither
                    # half is enough on its own. `os.mkdir`'s default is
                    # `0o777 & ~umask`, so the mode of this repository, its
                    # `objects/`, `refs/`, `hooks/` and `config` was whatever
                    # umask the process happened to inherit — at `umask 000` a
                    # world-writable document store, and the shipped shape is
                    # safe only by a default nobody declared (independent
                    # adversarial review of openDox-code#26, A26-5). `mode=` is
                    # still MASKED by the umask, so it cannot widen and cannot
                    # be relied on to narrow; the `fchmod` through the held
                    # descriptor is what makes the answer the same under every
                    # umask, and doing it through the descriptor rather than
                    # the name is what makes it race-free.
                    os.mkdir(leaf, REPOSITORY_DIRECTORY_MODE, dir_fd=parent)
                except FileExistsError:
                    # AND "IT EXISTS" IS TWO DIFFERENT ANSWERS. The preflight
                    # allows an EMPTY DIRECTORY this act may adopt, and for
                    # that one this exception is expected and means nothing.
                    # For a location the preflight found ABSENT it is the race
                    # the exclusive `mkdir` exists to detect: another process
                    # created an ordinary empty directory in the window, this
                    # branch swallowed the error, the emptiness check below
                    # passed, and the act initialized a repository in a
                    # directory it did not create — the documented exclusive
                    # guarantee quietly not kept (Copilot review of
                    # openDox-code#26, at `cec91c08`).
                    if not was_there:
                        raise RepositoryActRefused(
                            f"{location} did not exist when this act checked "
                            "it and existed a moment later, so something else "
                            "created it while this repository was being made. "
                            "Nothing has been initialized: this act creates "
                            "the directory it uses, and will not adopt one "
                            "that appeared under it; the map row is rolled "
                            "back with the caller's transaction.") from None
                owned = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY
                                | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
                os.fchmod(owned, REPOSITORY_DIRECTORY_MODE)
            finally:
                os.close(parent)
        else:
            # A PLATFORM WITHOUT `dir_fd` REFUSES, and that is a change of
            # policy this comment owes an explanation for. The branch here used
            # to create the parents with `location.parent.mkdir(parents=True)`
            # and then open the leaf no-follow by name, described as "the
            # strongest the platform offers". It is not weaker — it is not a
            # guard at all: `mkdir(parents=True)` resolves the chain BY
            # PATHNAME, so an EXISTING `<root>/link` pointing elsewhere is
            # followed every time on every platform taking this branch, and the
            # act would have created a repository outside the root it owns and
            # reported success (Copilot review of openDox-code#26, round 29 —
            # "this is not just the documented race window"). Refusing is the
            # honest answer for a platform this act has never run on: both
            # `deploy/` shapes and every CI runner are Linux. The refusal is an
            # `OSError`, which this function's caller already translates.
            raise PlatformCannotGuardPaths(
                "creating a repository needs a dir_fd-capable `mkdir` and "
                "this platform has none, so the parents could only be made by "
                "pathname — which follows any link already in the chain. "
                "Nothing has been created")
    except RepositoryActRefused:
        raise
    except (OSError, ValueError) as exc:
        # `ValueError` TOO, for the reason the project id and the root already
        # have it: `Path.mkdir` and `os.open` raise it — NOT `OSError` — for an
        # embedded NUL, and `initialize_repository` is PUBLIC. A direct caller
        # that did not come through `create_repository`'s own guard therefore
        # got a raw exception where this act promises a named refusal for every
        # reason it will not create a repository (Copilot review of
        # openDox-code#26, round 25). The preflight cannot catch it either: a
        # path holding a NUL reads as ABSENT, so the refusal has to be here.
        raise RepositoryActRefused(
            f"the directory could not be created ({type(exc).__name__}); the "
            "map row is rolled back with the caller's transaction") from exc
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
        # `--shared=0600` PINS WHAT GIT MAKES UNDER IT. The directory this act
        # creates is `0o700` by the `fchmod` above, and `git init` then creates
        # `objects/`, `refs/`, `hooks/` and `config` by its own rule — which is
        # the umask again unless it is told otherwise (independent adversarial
        # review of openDox-code#26, A26-5). `--shared` is `init`'s own option
        # for this and it takes an octal; `-c core.sharedRepository=…` is NOT
        # the spelling, because `GitRunner` puts its `-c` options before the
        # subcommand and `git init -c …` is `unknown switch \`c'` (measured on
        # git 2.43.0). The compose and Kubernetes shapes run as a single uid
        # with a private volume; this is that intent written down rather than
        # inherited from a shell.
        git.out("init", "--bare", "--shared=0600",
                f"--initial-branch={branch}", ".")
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
    # `ValueError` IS ONE OF THE THREE. A legacy or hand-written map row can
    # hold a location with an embedded NUL, and `open()` raises `ValueError`
    # before any syscall — which this handler did not name, so attach and push
    # answered with a traceback and a 500 instead of the act's own named
    # refusal (Copilot review of openDox-code#26, round 32, suppressed).
    except (OSError, RuntimeError, ValueError) as exc:
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
        root = Path(decoded_path(git.out("rev-parse", question))).resolve()
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
    ref = decoded_ref_name(symbolic.stdout)
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


#: Config keys whose value git EXECUTES, and which a repository this service
#: owns must therefore not set in its OWN config file. The operator's global
#: and system git keep them — that is why `GIT_CONFIG_GLOBAL`/`_SYSTEM` are
#: preserved rather than stripped — so the rule is about SCOPE and not about
#: the feature.
_EXECUTED_LOCAL_KEYS = ("credential.helper", "core.gitProxy", "core.sshCommand",
                        "uploadpack.packObjectsHook", "core.fsmonitor",
                        "diff.external")

#: The same rule's PATTERN keys — the ones with a caller-named middle segment,
#: which `--get-all` on a fixed name cannot see. Each was MEASURED on git
#: 2.43.0 against a planted `git-remote-evil` on PATH and a bare destination,
#: and NONE of them is stopped by the `-c protocol.ext.allow=never` this act
#: already passes (Copilot review of openDox-code#26, round 32):
#:
#:   * `remote.origin.vcs=evil` ran `git-remote-evil origin <dest>` — the
#:     review's own case, and the URL predicate never sees a `::` because the
#:     URL itself stays ordinary.
#:   * `url.<prefix>.insteadOf` REWRITES the destination before the transport
#:     is chosen, so `url."evil::".insteadOf = <dest>` ran the same helper.
#:     The same key pointed at `ext::` is already refused by git itself
#:     (`fatal: transport 'ext' not allowed`), which is why the REWRITE and
#:     not `ext` is the hole here.
#:
#: `proxy` is the per-remote twin of `core.gitProxy`, which is already in the
#: fixed list above; it is listed here because a list naming only the cases
#: somebody demonstrated is a list the next transport walks past.
#:
#: `remote.<name>.receivepack` IS DELIBERATELY ABSENT, and that is a decision
#: rather than an oversight. It is executed on a local push — measured, and
#: `test_a_push_cannot_be_made_to_run_the_repository_s_own_receive_pack`
#: measures it both ways — but round 16 closed it by PINNING `--receive-pack`
#: on the command line, where it outranks the config value. Refusing the key
#: as well would turn a neutralized stale setting into a failed push, and the
#: recorded decision is that an operator's leftover is neutralized rather than
#: fatal.
_EXECUTED_LOCAL_KEY_PATTERNS = (
    r"^remote\..*\.(vcs|proxy)$",
    r"^url\..*\.insteadof$",
)


def _refuse_repository_local_command_config(git: GitRunner, location: Any) -> None:
    """Refuse a push from a repository whose OWN config names a program.

    `credential.helper` is the one the review named, and it is the sharpest:
    git runs a `!command` helper when an HTTPS push is asked for credentials,
    and the terminal and askpass guards say nothing about helpers. MEASURED on
    git 2.43.0 against a local endpoint answering 401 — a repository-local
    `credential.helper = !f() { touch MARKER; …; }; f` RAN during the push, and
    `-c credential.helper=` stopped it (Copilot review of openDox-code#26,
    round 21).

    REFUSED RATHER THAN OVERRIDDEN, and that is the whole point. `-c
    credential.helper=` resets the WHOLE list, including the operator's global
    helper — the configuration this package deliberately preserves, which is
    how a real destination is authenticated at all. The value that must not be
    trusted is the one in the repository this service WRITES TO, so the check
    is scoped to that file: the operator keeps their helper, and a repository
    that grew one is refused by name instead of being pushed with it.

    The other keys are the same rule's other instances, checked in the same
    pass because a list with one entry is a list somebody forgets to extend.
    """
    def _refuse_key(key: str, scope: str) -> RepositoryActRefused:
        return RepositoryActRefused(
            f"the repository at {location} sets {key!r} in its own "
            f"git config ({scope.lstrip('-')} scope). git runs that "
            "value as a program, and this service writes to this "
            "repository, so it is refused rather than pushed with. "
            "Remove it with `git config --unset-all " + key + "`; an "
            "operator's own helper belongs in the global or system "
            "config, which this runtime keeps")

    # `--includes` ON EVERY SCOPED PROBE, because git turns it OFF when a config
    # FILE is named and ON only when it searches all of them — while git's own
    # config READER always follows `include.path`. So a repository whose
    # `.git/config` holds nothing but `[include] path = extra.cfg` hid every one
    # of these keys from this guard and still had git run them during the push,
    # which is the execution round 21 added this guard to stop. MEASURED on git
    # 2.43.0: `git config --local --get-all credential.helper` exits 1 with no
    # output while `git config --local --includes --get-all credential.helper`
    # prints `!f() { … }; f` (independent adversarial review of
    # openDox-code#26, A26-1). This guard is the whole attack surface by
    # design — `GitRunner` deliberately keeps the operator's global and system
    # config — so a hole in it is a hole straight through.
    for key in _EXECUTED_LOCAL_KEYS:
        for scope in ("--local", "--worktree"):
            probe = git.run("config", scope, "--includes", "--get-all", key)
            if probe.returncode == 0 and probe.stdout.strip():
                raise _refuse_key(key, scope)
    # AND THE PATTERN KEYS, WHICH `--get-all` CANNOT REACH. `remote.<name>.vcs`
    # names a remote HELPER — `git-remote-<value>`, resolved off PATH — while
    # `remote.origin.url` stays perfectly ordinary, so the URL predicate sees
    # no `::` and `-c protocol.ext.allow=never` says nothing about it
    # (measured; see `_EXECUTED_LOCAL_KEY_PATTERNS`). `--get-regexp` is git's
    # own answer for a key whose middle segment the repository chooses, and
    # `--name-only` keeps the VALUE — which may be a credential-shaped
    # `insteadOf` prefix — out of the refusal this act returns to a caller.
    for pattern in _EXECUTED_LOCAL_KEY_PATTERNS:
        for scope in ("--local", "--worktree"):
            probe = git.run("config", scope, "--includes", "--name-only",
                            "--get-regexp", pattern)
            if probe.returncode == 0 and probe.stdout.strip():
                found = probe.stdout.decode("utf-8", "replace").split()
                raise _refuse_key(found[0], scope)


#: A DRIVE-LETTER OR UNC PATH, which git reads as a LOCAL path and not as
#: `host:path`. `C:/srv/x` has a `:` in its first component, so the scp rule
#: below claimed it — and the containment check was skipped on the platform
#: this module's own pathname fallback exists for (Copilot review of
#: openDox-code#26, round 23).
_WINDOWS_LOCAL_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def _destination_as_a_local_path(destination: str,
                                 location: Any,
                                 *, windows: bool = os.name == "nt"
                                 ) -> Path | None:
    """The filesystem path a destination names, or `None` if it names a host.

    git's own rule, narrowed to what this act has to decide — and each of the
    three corrections below was a way PAST the containment check, not a
    cosmetic one (Copilot review of openDox-code#26, round 23):

    * **`file://` IS PERCENT-DECODED FIRST.** git decodes the path before it
      opens it, so `file:///…/projects%2Fanother.git` opens
      `…/projects/another.git` while an undecoded comparison sees one component
      and calls it a sibling OUTSIDE the root. Encoded traversal (`%2e%2e`) is
      the same trick.
    * **A WINDOWS DRIVE OR A UNC SHARE IS A PATH, not `host:path`.** `C:` in
      the first component made `C:/…/sibling.git` look like scp syntax and
      skipped the check entirely — on the very platform this module's pathname
      fallback says it runs.
    * **A RELATIVE DESTINATION IS THE REPOSITORY'S, not this process's.** `git
      -C <location> push ../another.git` resolves against the mapped
      repository; `Path(destination).resolve()` resolved against whatever
      working directory the service happens to have, so `../another-project` in
      the map compared as something else entirely.
    """
    if destination.startswith("file://"):
        return Path(urllib.parse.unquote(
            urllib.parse.urlsplit(destination).path or "/"))
    # THE DRIVE/UNC BRANCH RUNS ONLY WHERE GIT READS IT AS A PATHNAME. It ran
    # on every host, so a POSIX runtime classified `C:/repo.git` as a local
    # path — and MEASURED on git 2.43.0 on Linux, git reads that colon form as
    # scp/SSH syntax: `git ls-remote C:/repo.git` gives `ssh: Could not resolve
    # hostname c`. So this act would have sent the LOCAL hook-disabling
    # `--receive-pack` to a remote host, and compared ownership against a
    # filesystem path nothing was ever going to touch (Copilot review of
    # openDox-code#26, round 29). `windows` is a parameter so the case can
    # measure both platforms from either.
    if windows and _WINDOWS_LOCAL_PATH.match(destination):
        return Path(destination)
    # AND `://` STILL WINS OVER AN ABSOLUTE PATH, which round 29 also asked
    # about — `/srv/projects/other://repo.git` returning `None` was reported as
    # a bypass, "even though Git treats an absolute path as a local
    # repository". It does not treat THAT one as a path. MEASURED:
    #
    #   git push /tmp/cls/src/../other://repo.git HEAD:refs/heads/main
    #   fatal: protocol '/tmp/cls/src/../other' is not supported
    #
    # git splits on `://` first too, so the destination is unusable rather than
    # unchecked: the push fails loudly at git and nothing is bypassed. This
    # classifier agreeing with git is the property that matters, and it does.
    if "://" in destination:
        return None
    head = destination.split("/", 1)[0]
    if ":" in head:                       # `user@host:path`, or `host:path`
        return None
    named = Path(destination)
    return named if named.is_absolute() else Path(location) / named


def _refuse_a_destination_this_service_owns(
        destinations: tuple[str, ...],
        location: Any) -> dict[str, tuple[int, int] | None]:
    """Refuse a push aimed INSIDE this service's own repository root.

    The act accepts a local destination by design — a governed factory is a
    repository, and RULING C3 makes the move a push — and `git push` to one
    runs `git-receive-pack` against it with this service's own credentials.
    Nothing tied the destination to the project, so an owner could point
    `origin` at ANOTHER PROJECT'S repository under the same root and have this
    runtime write into it (Copilot review of openDox-code#26, round 21).

    The root is `location.parent` by construction — `repository_location` is
    `<root>/<project id>` — so this needs no new setting to know what it owns.
    A destination that resolves to this project's own repository, to a sibling,
    or to the root itself is refused by name.

    WHAT THIS DOES NOT DO, registered rather than implied: there is no
    allowlist tying a destination to a governed factory. Outside this root a
    local path is still accepted, because that is what the ruling asks for and
    an allowlist is a contract with an owner — the governed-destination
    registry — that this act does not have. What is closed is the one
    destination this service can reach WITHOUT any credential of the operator's
    at all: its own.

    AND IT RETURNS THE IDENTITY OF WHAT IT CHECKED — `(st_dev, st_ino)` per
    local destination, or `None` where nothing was there — so the push can
    prove it opened THE SAME OBJECT. This function judges a NAME, and a name
    is not a thing: an allowed EXTERNAL symlink repointed from repository A to
    repository B between this check and the open passes the containment test
    both times, because B is outside the root as surely as A was, and the push
    lands in B while the row and the response name A (Copilot review of
    openDox-code#26, at `cec91c08`). The service-owned case was closed by
    re-asking containment of the OPEN object; this closes the external case,
    which containment cannot answer.
    """
    checked: dict[str, tuple[int, int] | None] = {}
    owned = Path(location).parent
    for destination in destinations:
        try:
            path = _destination_as_a_local_path(destination, location)
        except ValueError as exc:
            # A LEGACY ROW CAN HOLD A VALUE `urlsplit` REFUSES. Only NEW
            # attachments pass the validating path, and `file://[bad` raises
            # `ValueError` here — before this function's own translation — so
            # the push leaked a raw exception and the API answered 500 instead
            # of a named refusal (Copilot review of openDox-code#26, round 25).
            # The URL is NOT echoed: it is a stored value this act has already
            # decided it cannot read.
            raise RepositoryActRefused(
                "this project's remote is not a destination this act can "
                f"read ({type(exc).__name__}); re-attach the remote") from exc
        if path is None:
            continue
        try:
            resolved = path.expanduser().resolve()
            root = owned.resolve()
            here = Path(location).resolve()
            checked[destination] = _identity_of(resolved)
        except (OSError, RuntimeError, ValueError) as exc:
            # FAIL CLOSED. This `continue` said "unreadable: other guards
            # answer", and no other guard answers THIS question: a local
            # destination whose path could not be resolved — a permission
            # error, a symlink loop, an embedded NUL — went on to `git push`
            # without anything having proved it lies outside the root this
            # service owns (Copilot review of openDox-code#26, round 29). A
            # containment check that cannot be made is a refusal, not a pass.
            raise RepositoryActRefused(
                "this project's remote is a local path whose location this "
                f"act cannot establish ({type(exc).__name__}), so it cannot "
                "prove the push stays out of the repository root this service "
                "owns; re-attach a remote that resolves") from exc
        if resolved == here or resolved == root or root in resolved.parents:
            raise RepositoryActRefused(
                "this project's remote names a path inside the repository "
                "root this service owns, which is this project's own "
                "repository or another project's. A push moves the project "
                "into a GOVERNED destination; re-attach a remote that is one")
    return checked


def _identity_of(resolved: Path) -> tuple[int, int] | None:
    """`(st_dev, st_ino)` — WHICH OBJECT this is, not what it is called.

    `None` where nothing is there: a destination that does not exist yet is
    not an error here (the open that follows is what refuses it), and "there
    was nothing, and now there is something" is itself a mismatch the caller
    must see rather than a missing answer.

    `os.stat` and not `os.lstat`, because `resolved` has already been through
    `Path.resolve()`: the link chain is gone and the last component IS the
    object. Every other `OSError` propagates deliberately — the caller has this
    inside the translation that makes an unresolvable destination a named
    refusal, and a containment check that cannot be made is a refusal.
    """
    try:
        st = os.stat(resolved)
    except FileNotFoundError:
        return None
    return (st.st_dev, st.st_ino)


#: `_bound_local_destination`'s "nobody told me what was checked". Distinct
#: from `None`, which is a real answer: the destination WAS checked and there
#: was nothing there.
_NOT_CHECKED = object()


def _bound_local_destination(destination: str | None, location: Any, *,
                             checked: Any = _NOT_CHECKED):
    """A LOCAL push destination named by an OPEN DIRECTORY, where the OS allows.

    THE WINDOW THIS CLOSES (Copilot review of openDox-code#26, round 29): the
    containment check resolved the destination, refused it if it lay inside the
    root this service owns, and then THREW THE RESOLVED OBJECT AWAY — the push
    re-opened the same URL by pathname. A symlink used as an external local
    destination could be re-pointed at a sibling under this service's root
    between the two, and the push would write into another project with the
    guard's blessing. The act registered this as residue twice; it is closed
    here rather than registered a third time.

    The handle is opened with the same component-by-component no-follow walk
    every other path in this module uses, and `git push /proc/self/fd/<n>`
    writes into THAT object whatever the name now points at — measured on this
    container (Linux 6.18, git 2.43.0): `rc 0`, `* [new branch] HEAD -> main`
    in the directory the descriptor held.

    Returns `(handle, argument)`: the descriptor to keep open across the push
    and the destination to name on the command line, or `(None, None)` when the
    destination is not local. WHERE NEITHER `/proc/self/fd` NOR `/dev/fd`
    EXISTS the handle is released and the pathname is used, which is the ladder
    `runner_bound_to` already documents — unlike the creation path, the guard
    here is real on every platform and only its NAMING degrades.
    """
    if destination is None:
        return None, None
    path = _destination_as_a_local_path(destination, location)
    if path is None:
        return None, None
    try:
        resolved = path.expanduser().resolve()
        handle = open_no_follow_chain(resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RepositoryActRefused(
            "this project's remote is a local path this act could not open "
            f"without following a link ({type(exc).__name__}); nothing is "
            "pushed") from exc
    try:
        # AND IT IS THE OBJECT THE GUARD CHECKED, asked of the OPEN
        # DESCRIPTOR. Containment answers "is this inside the root this
        # service owns", and for two EXTERNAL destinations the answer is `no`
        # both times — so a symlink repointed from external repository A to
        # external repository B between the check and this open passed every
        # test and the push landed in B while the row and the response named A
        # (Copilot review of openDox-code#26, at `cec91c08`). `os.fstat` on
        # the handle cannot be raced: it reports the object this descriptor
        # refers to, and that is the object `--receive-pack` will write into.
        if checked is not _NOT_CHECKED:
            seen = os.fstat(handle)
            if (seen.st_dev, seen.st_ino) != checked:
                raise RepositoryActRefused(
                    "this project's remote named one place when it was "
                    "checked and another when it was opened, so the "
                    "destination of record and the destination this push "
                    "would reach are not the same object. Nothing is pushed; "
                    "the remote is not echoed, because a value that changed "
                    "under the act is not one this refusal can name")
        for base in ("/proc/self/fd", "/dev/fd"):
            if os.path.isdir(base):
                bound = f"{base}/{handle}"
                # AND THE CONTAINMENT IS RE-ASKED OF THE OPEN OBJECT, which is
                # the half the first cut left open. `_refuse_a_destination_this
                # _service_owns` approved a NAME; this function then resolved
                # that name again, so a symlink outside the root during the
                # check and repointed into a sibling before this open bound the
                # SIBLING and pushed to it with the guard's blessing (Copilot
                # review of openDox-code#26, round 30). The descriptor's own
                # path is what is asked now — `/proc/self/fd/<n>` resolves, in
                # this process, to the directory the handle refers to — so the
                # object that is checked is the object that is pushed to, with
                # nothing between them.
                real = Path(os.path.realpath(bound))
                # `resolve()` CAN RAISE, and this one sat outside the
                # translation the destination path above gets: a mapped
                # repository whose parent is renamed, replaced by a symlink
                # loop or made unreachable after the bind raises `OSError` or
                # `RuntimeError` here, and `push_to_remote` translates only
                # `GitCommandFailed` — so the API answered 500 instead of the
                # act's named refusal (Copilot review of openDox-code#26,
                # round 33, suppressed). The check that cannot complete is a
                # check that did not pass.
                try:
                    owned = Path(location).parent.resolve()
                except (OSError, RuntimeError, ValueError) as exc:
                    raise RepositoryActRefused(
                        "the repository root this service owns could not be "
                        f"resolved ({type(exc).__name__}), so this push's "
                        "destination cannot be proved to be outside it; the "
                        "push is refused rather than made unchecked"
                    ) from exc
                if real == owned or owned in real.parents:
                    raise RepositoryActRefused(
                        "this project's remote resolved, at the moment it was "
                        "opened, to a path inside the repository root this "
                        "service owns — this project's own repository or "
                        "another project's. A push moves the project into a "
                        "GOVERNED destination; re-attach a remote that is one")
                return handle, bound
    except BaseException:
        os.close(handle)
        raise
    os.close(handle)                      # unreachable: the capability refuses
    return None, None


def _receive_pack_for(destination: str | None, location: Any) -> str:
    """`--receive-pack=…`, with the hook guard on the LOCAL case and only it.

    Round 21 put `git -c core.hooksPath=<devnull> receive-pack` on every push,
    to stop a LOCAL destination's `pre-receive` running in this process. For a
    network destination that same option runs on the SERVER — `--receive-pack`
    is the command executed THERE — so it disabled a governed factory's own
    `pre-receive`/`update`/`post-receive`, which is the policy that destination
    exists to apply (Copilot review of openDox-code#26, round 25). The guard
    and the sabotage are the same string; what decides is WHOSE process runs
    the hooks.

    A network destination still gets the pinned plain receiver, which is round
    16's property: the program is one THIS act names and not one the pushing
    repository's `remote.<name>.receivepack` chose.
    """
    local = destination is not None and _destination_as_a_local_path(
        destination, location) is not None
    return ("--receive-pack=git -c core.hooksPath=" + os.devnull
            + " receive-pack") if local else "--receive-pack=git-receive-pack"


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
        _refuse_repository_local_command_config(git, row.location)
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
            f"{len(destinations)} destinations under {REMOTE_NAME!r} while "
            f"the map records one ({redact_remote_url(row.remote_url)}). "
            "Nothing is pushed: a destination the map cannot record is a "
            "destination this act cannot make. Re-attach the remote to settle "
            "it. THE CONFIGURED VALUES ARE NOT ECHOED: `get-url --push --all` "
            "is read by LINE, so a stored URL holding a newline — which a "
            "legacy row can — arrives here as fragments like "
            "`https://user:secret` and `@host/repo`, and a redactor cannot "
            "see userinfo that has been cut in half (Copilot review of "
            "openDox-code#26, round 30). The count is the finding; `git -C "
            f"{row.location} remote get-url --push --all {REMOTE_NAME}` shows "
            "them to whoever already has the repository.")
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

    # AND IT IS NOT A PLACE THIS SERVICE OWNS. Checked after the two agree, so
    # the value judged is the one git would use and the one the map records.
    checked = _refuse_a_destination_this_service_owns(
        tuple(url for url in (configured, effective, row.remote_url) if url),
        row.location)

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
        # AND THE RECEIVER RUNS WITH THE DESTINATION'S HOOKS OFF. For a LOCAL
        # destination — which this act accepts by design, a governed factory
        # being a repository — `git push` forks `git-receive-pack` IN THIS
        # PROCESS TREE, and that process reads the DESTINATION's config and
        # runs its `pre-receive`, `update` and `post-receive` hooks. The
        # client's own `core.hooksPath` does not reach it: MEASURED on git
        # 2.43.0, a planted `pre-receive` RAN under `git -c
        # core.hooksPath=/dev/null push`, and did NOT run when the option was
        # carried on `--receive-pack` instead — where it becomes the receiving
        # command's own `-c` — with the push still landing (Copilot review of
        # openDox-code#26, round 21). The value is still one THIS act chooses
        # rather than one the repository names, which is the property round 16
        # pinned.
        # AND A LOCAL DESTINATION IS NAMED BY THE OBJECT THE GUARD CHECKED.
        # `REMOTE_NAME` made git re-read `remote.origin.url` and re-walk that
        # pathname, so the destination the containment check resolved and the
        # destination git opened were two lookups with a window between them —
        # see `_bound_local_destination`. The remote's two URLs and the map row
        # have already been proved equal above, so naming the handle loses
        # nothing and closes that window. A network destination still pushes to
        # `REMOTE_NAME`, which is the value all three agree on.
        # AND THE IDENTITY THE GUARD ABOVE CHECKED TRAVELS WITH IT, so the
        # object that was judged is the object that is written to. Without it
        # the window is real for an EXTERNAL destination, which containment
        # cannot close: both A and B are outside the root.
        handle, bound = _bound_local_destination(
            effective, row.location, checked=checked.get(effective))
        try:
            runner = (dataclasses.replace(git, extra_fd=handle)
                      if handle is not None else git)
            runner.out_bounded("-c", "protocol.ext.allow=never",
                               "push",
                               _receive_pack_for(effective, row.location),
                               bound or REMOTE_NAME,
                               f"refs/heads/{branch}:refs/heads/{branch}",
                               timeout=PUSH_TIMEOUT_SECONDS)
        finally:
            if handle is not None:
                os.close(handle)
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
