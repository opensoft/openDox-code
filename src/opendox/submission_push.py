"""THE SUBMISSION'S PUSH: `session_pr.LocalGitSubmissions`' git half (plan 038
T011; #1144 boxes 12.1a, 12.2 and 12.3; decisions OQ-12-11 and OQ-12-12).

`LocalGitSubmissions(checkout_root).submit(branch)` pushes a NAMED local branch
of the user's own checkout to the remote 12.3 chooses, and returns the
`Submission` 12.1a asks for: where the work went. This module is that push.

IT CARRIES NO PUSH OF ITS OWN. It decides WHAT to push and hands that to the
runtime's push core, `repository_act._push_to_remote_with`, which the runtime's
`push_to_remote` calls too. So the hardening is one piece of code with two
callers, and the two cannot drift (OQ-12-12: "the hardening already exists"):

  * the repository-local command-config refusal (`repository_act.
    _EXECUTED_LOCAL_KEYS`): a checkout whose OWN config names a program git
    would run is refused, not pushed with;
  * `-c protocol.ext.allow=never`, the pinned `--receive-pack`, a local
    destination's hooks off and its directory named by an open descriptor;
  * the wall-clock and output bounds, and no interactive prompt.

TWO OF THE RUNTIME'S CHECKS DO NOT APPLY, and both are about what the runtime
owns. The map row is the runtime's destination of record; a checkout has no
map, and git's own configuration is its record. The containment in the
service's repository root refuses a destination beside the repository; a
checkout has no service root, and a bare remote beside it is the ordinary
local remote (`PushPlan.contained`).

WHICH REMOTE (12.3; ADV-26; CF-7, `6013547504`): the one named `origin`, else
the SOLE remote, whatever its name. No remote, or several and none named
`origin`, is `NoSubmissionTarget`, naming what is missing.

WHICH BRANCH (R2Q5 (a), `6003486656`): any local branch except the default
branch, `main` (R2Q7 (a)). Its tip is read once and pushed BY ITS SHA, so the
`commit` the report names is the commit that was sent, even if the branch
moves meanwhile. Never `--force` and never `--set-upstream`: the checkout's
own configuration is not written.

WHAT IS SHOWN (12.1a; OQ-12-11; ADV-09). A remote whose URL carries a
credential is PUSHED, not refused. `redact_destination` is all a report or a
message ever shows of the URL: the userinfo and every query and fragment value
are replaced, and the scheme, host, port and path stay, so the report still
says where the work went. Text this module did not write (git's stderr, a
runtime refusal) is scrubbed of the URL's literal secrets first (`_scrubbed`),
because git echoes a query string verbatim and a parameter whose NAME is not
credential-shaped passes every pattern.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from contextlib import ExitStack
from pathlib import Path

from opendox.corpus_adapter import CorpusRefused
from opendox.runtime import repository_act
from opendox.runtime.config import MAX_REMOTE_URL_CHARS
from opendox.runtime.local_git_adapter import (
    DEFAULT_BRANCH,
    GitCommandFailed,
    GitRunner,
    carries_a_control_character,
    decoded_path,
    metadata_held_open,
    open_no_follow_chain,
    redact_credentials,
    runner_bound_to,
)
from opendox.session_pr import NoSubmissionTarget, Submission, SubmissionRefused

#: The remote a submission takes when several are attached (12.3).
PREFERRED_REMOTE = "origin"

#: What a redacted value reads as.
REDACTED = "<redacted>"

#: `scheme://`, as git recognises a URL.
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")

#: Schemes whose userinfo may be a LOGIN NAME rather than a credential. Any
#: other scheme's bare user name is redacted, because a token can ride there
#: (`https://<token>@host/...`).
_SSH_SCHEMES = ("ssh://", "git+ssh://", "ssh+git://")

#: What an ssh login name that is kept looks like: nothing but these. A `:`
#: announces a password, and a `%` may encode one (`git%3As3cret`), so either
#: makes the userinfo a credential, as everything else in it does.
_LOGIN_NAME = re.compile(r"[A-Za-z0-9._-]+")

#: Below this length a held value is not scrubbed out of foreign text: a
#: two-letter value replaced everywhere garbles the message and protects
#: nothing.
_SHORTEST_SCRUBBED = 4


def submit_branch(checkout_root: Path | str, branch: str, *,
                  executable: str = "git") -> Submission:
    """Push `branch` to the chosen remote and report where it went.

    Returns only on success. Every failure raises `NoSubmissionTarget` or
    `SubmissionRefused`, with a redacted message.
    """
    if branch == DEFAULT_BRANCH:
        raise SubmissionRefused(
            f"`{DEFAULT_BRANCH}` is the default branch, and a submission takes "
            "any local branch except it (R2Q5 (a)); nothing is pushed. Submit "
            "the branch the work is on.")
    # THE CHECKOUT IS HELD OPEN, as the runtime holds a mapped repository:
    # resolved once (a symlinked parent is the user's own layout), then opened
    # component by component without following a link, and git is pointed at
    # the descriptor, so the directory judged below is the one pushed from.
    try:
        root = Path(checkout_root).expanduser().resolve()
        handle = open_no_follow_chain(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SubmissionRefused(
            f"the checkout {checkout_root} could not be opened "
            f"({type(exc).__name__}); nothing is pushed") from exc
    try:
        try:
            git = runner_bound_to(handle, root, executable)
            _refuse_unless_the_root(git, root)
        except GitCommandFailed as failed:
            raise SubmissionRefused(
                f"{root} could not be read as a repository "
                f"({_scrubbed(str(failed), None)}); nothing is pushed"
            ) from failed
        except (OSError, RuntimeError) as exc:
            raise SubmissionRefused(
                f"the checkout {root} could not be held open "
                f"({type(exc).__name__}); nothing is pushed") from exc
        # AND SO IS A LINKED WORKTREE'S METADATA. Its `.git` is a FILE naming
        # directories elsewhere, which every later git call would re-resolve,
        # so its git directory and common directory are held by descriptor
        # for the whole submission, as the adapter's write path holds them
        # (`metadata_held_open`; a checkout or a bare repository needs none).
        # Asked AFTER the root check: with `GIT_DIR` bound, git reads the
        # working directory as the top level, so the check would pass for a
        # directory inside the checkout.
        with ExitStack() as held:
            try:
                bound, _git_dir = held.enter_context(
                    metadata_held_open(git, subject=str(root)))
            except CorpusRefused as exc:
                raise SubmissionRefused(
                    f"the git metadata of {root} could not be held open "
                    f"({type(exc.__cause__ or exc).__name__}); nothing is "
                    "pushed") from exc
            return _submit_with(bound, root, branch)
    finally:
        os.close(handle)


def _submit_with(git: GitRunner, root: Path, branch: str) -> Submission:
    """`submit_branch` on a runner bound to the open checkout.

    NO REFUSAL HERE CHAINS ITS CAUSE (`from None`). The cause's own message is
    git's stderr or a runtime refusal, redacted only by pattern, so a query
    value under a name no pattern knows survives in it, and a logged
    traceback prints the cause in full. The scrubbed text is in the message,
    and the cause is left out of the traceback.
    """
    remote = url = None
    try:
        repository_act._refuse_repository_local_command_config(git, root)
        remote = _chosen_remote(git, root, branch)
        commit = _branch_tip(git, root, branch)
        url = _the_one_push_url(git, remote, branch)
        repository_act.refuse_command_executing_remote(url)
        # A URL `urlsplit` refuses (`file://[bad`) is refused HERE, by name:
        # the push core reads the destination before it binds it, and a
        # `ValueError` from there would escape as no refusal at all.
        repository_act._destination_as_a_local_path(url, root)
    except GitCommandFailed as failed:
        raise SubmissionRefused(
            f"{root} could not be read before the push of `{branch}` "
            f"({_scrubbed(str(failed), url)}); nothing is pushed") from None
    except (OSError, RuntimeError, ValueError) as exc:
        raise SubmissionRefused(
            f"{root} could not be read before the push of `{branch}` "
            f"({type(exc).__name__}; the value is not echoed); nothing is "
            "pushed") from None
    except repository_act.RepositoryActRefused as refused:
        raise SubmissionRefused(
            f"the push of `{branch}` is refused before it runs: "
            f"{_scrubbed(str(refused), url)}") from None
    shown = redact_destination(url)
    try:
        repository_act._push_to_remote_with(git, repository_act.PushPlan(
            location=root, remote_name=remote, destination=url,
            refspec=f"{commit}:refs/heads/{branch}", contained=False))
    except GitCommandFailed as failed:
        raise SubmissionRefused(
            f"the push of `{branch}` to `{remote}` ({shown}) failed "
            f"({_scrubbed(str(failed), url)}); nothing is reported as "
            "submitted") from None
    except repository_act.RepositoryActRefused as refused:
        raise SubmissionRefused(
            f"the push of `{branch}` to `{remote}` ({shown}) is refused "
            f"before it runs: {_scrubbed(str(refused), url)}") from None
    return Submission(remote=remote, ref=f"refs/heads/{branch}", url=shown,
                      branch=branch, commit=commit)


def _refuse_unless_the_root(git: GitRunner, root: Path) -> None:
    """Refuse a directory that is not a repository's own root.

    `git -C <dir>` WALKS UP, so a directory inside a checkout would submit the
    enclosing one. Asked as `repository_act` asks it: a bare repository's root
    is its git directory, a checkout's is its top level.
    """
    bare = git.out("rev-parse", "--is-bare-repository").decode().strip()
    question = "--absolute-git-dir" if bare == "true" else "--show-toplevel"
    top = Path(decoded_path(git.out("rev-parse", question))).resolve()
    if top != root:
        raise SubmissionRefused(
            f"{root} is not the root of a git repository: it is inside the one "
            f"at {top}. Nothing is pushed; pass that repository's root.")


def _chosen_remote(git: GitRunner, root: Path, branch: str) -> str:
    """`origin`, else the sole remote; anything else is `NoSubmissionTarget`."""
    names = [name for name in decoded_path(git.out("remote")).split("\n")
             if name]
    if not names:
        raise NoSubmissionTarget(
            f"no remote is attached to {root}, so there is nowhere to submit "
            f"`{branch}`. Attach one (`git remote add origin <url>`) and "
            "submit again.")
    if PREFERRED_REMOTE in names:
        return PREFERRED_REMOTE
    if len(names) == 1:
        return names[0]
    listed = ", ".join(f"`{name}`" for name in names)
    raise NoSubmissionTarget(
        f"several remotes are attached to {root} ({listed}) and none is named "
        f"`{PREFERRED_REMOTE}`, so which one receives `{branch}` is not "
        f"decided. Name it `{PREFERRED_REMOTE}` (`git remote rename <name> "
        f"{PREFERRED_REMOTE}`) and submit again.")


def _branch_tip(git: GitRunner, root: Path, branch: str) -> str:
    """The commit `refs/heads/<branch>` names, or a refusal.

    The name is checked as a REF NAME first, so `rev-parse` never reads it as
    a revision expression: `x~1`, `x^{tree}` and `x@{1}` are not branch names,
    and each would otherwise select a commit to push.
    """
    if git.run("check-ref-format", f"refs/heads/{branch}").returncode != 0:
        raise SubmissionRefused(
            "the branch name given is not a valid git branch name (it is not "
            "echoed); nothing is pushed")
    tip = git.run("rev-parse", "--verify", "--quiet",
                  f"refs/heads/{branch}^{{commit}}")
    if tip.returncode != 0:
        raise SubmissionRefused(
            f"{root} has no local branch `{branch}`; nothing is pushed")
    return tip.stdout.decode().strip()


def _the_one_push_url(git: GitRunner, remote: str, branch: str) -> str:
    """The ONE URL a push to `remote` reaches, as git resolves it.

    A remote with neither a `url` nor a `pushurl` is refused by name. MEASURED
    on git 2.43.0: `get-url --push --all` answers such a remote with its own
    NAME, which a push then treats as a path beside the checkout. Several push
    URLs are refused because git pushes to EACH, and a submission reports one
    destination. The URLs are not echoed: they are read by line, and a
    credential split across lines is one a redactor cannot see whole.

    THE URL IS READ EXACTLY, git's terminating newline aside. Git keeps
    surrounding whitespace in a configured URL, and a local path is the one
    place it is meaningful: `/srv/remote ` and `/srv/remote` are two
    directories, so a trimmed reading would push somewhere git does not mean.
    Such a URL is REFUSED rather than trimmed, as `repository_act` refuses
    one where it attaches a remote. So is one holding a control character.
    And no line is dropped: a URL ending in a newline prints as two lines,
    one of them empty, and counts as two destinations.
    """
    if not any(git.run("config", "--get-all", f"remote.{remote}.{key}")
               .stdout.strip() for key in ("url", "pushurl")):
        raise SubmissionRefused(
            f"the remote `{remote}` names no URL, so there is nowhere to push "
            f"`{branch}`; nothing is pushed. Set one (`git remote set-url "
            f"{remote} <url>`).")
    listed = git.out("remote", "get-url", "--push", "--all", remote)
    urls = decoded_path(listed).split("\n")
    if len(urls) != 1:
        raise SubmissionRefused(
            f"the remote `{remote}` would push to {len(urls)} destinations "
            "(a URL holding a newline reads as more than one), and a "
            "submission goes to exactly one; nothing is pushed. Leave one "
            f"(`git remote set-url --push {remote} <url>`); the URLs are not "
            "echoed.")
    url = urls[0]
    if (not url or url != url.strip()
            or carries_a_control_character(url)):
        raise SubmissionRefused(
            f"the push URL of the remote `{remote}` is empty, or has leading "
            "or trailing whitespace or a control character, which git keeps "
            "and a push would use; it is refused rather than normalized, and "
            "not echoed. Set it again (`git remote set-url --push "
            f"{remote} <url>`).")
    return url


def redact_destination(url: str) -> str:
    """`url` as a report may show it: every credential gone, the place kept.

    For a `scheme://` URL, the userinfo is replaced (a plain `ssh` login name
    excepted) and so is every query and fragment VALUE; the
    scheme, host, port and path stay (12.1a). The credential redactor every
    other report in this package uses runs last over the result, so a shape
    this pass does not parse still meets its patterns (`user:pw@host:path`).
    A value too long to judge, or holding a control character, is replaced
    whole, as `local_git_adapter.redact_remote_url` replaces one.
    """
    if len(url) > MAX_REMOTE_URL_CHARS or carries_a_control_character(url):
        return "<redacted-url>"
    scheme = _SCHEME.match(url)
    if scheme:
        rest = url[scheme.end():]
        cut = _authority_end(rest)
        authority, tail = rest[:cut], rest[cut:]
        userinfo, at, host = authority.rpartition("@")
        if at and not _is_a_login_name(url, userinfo):
            authority = f"{REDACTED}@{host}"
        url = url[:scheme.end()] + authority + _redacted_query(tail)
    return redact_credentials(url, a_bare_username_is_not_a_secret=True)


def _is_a_login_name(url: str, userinfo: str) -> bool:
    """Whether `userinfo` is an ssh LOGIN NAME, which a report may show."""
    return (url.lower().startswith(_SSH_SCHEMES)
            and _LOGIN_NAME.fullmatch(userinfo) is not None)


def _authority_end(rest: str) -> int:
    """Where a URL's authority ends: at the first `/`, `?` or `#`."""
    return min((index for index in (rest.find(mark) for mark in "/?#")
                if index >= 0), default=len(rest))


def _redacted_query(tail: str) -> str:
    """`tail` with every query value, and the fragment, replaced."""
    head, hashmark, fragment = tail.partition("#")
    path, question, query = head.partition("?")
    query = "".join(_redacted_parameter(part)
                    for part in re.split(r"([&;])", query))
    return path + question + query + hashmark + (REDACTED if fragment else "")


def _redacted_parameter(part: str) -> str:
    """One query piece: a delimiter or an empty piece as it is, `name=value`
    as `name=<redacted>`, and a bare value as `<redacted>`."""
    if part in ("", "&", ";"):
        return part
    name, equals, _value = part.partition("=")
    return f"{name}={REDACTED}" if equals else REDACTED


def _held_secrets(url: str | None) -> list[str]:
    """The literal values `redact_destination` hides, longest first.

    A caller that HOLDS a value needs no pattern to remove it, which is the
    runtime's `_without` for the same reason: git echoes a query string
    verbatim in its errors, and a parameter whose name is not credential-
    shaped passes every pattern.
    """
    scheme = _SCHEME.match(url or "")
    if not scheme:
        return []
    rest = url[scheme.end():]
    userinfo = rest[:_authority_end(rest)].rpartition("@")[0]
    found = ([] if _is_a_login_name(url, userinfo)
             else [userinfo, userinfo.partition(":")[2]])
    head, _, fragment = rest.partition("#")
    for part in re.split(r"[&;]", head.partition("?")[2]):
        name, equals, value = part.partition("=")
        found.append(value if equals else name)
    found.append(fragment)
    found += [urllib.parse.unquote(value) for value in found]
    return sorted({value for value in found
                   if len(value) >= _SHORTEST_SCRUBBED}, key=len, reverse=True)


def _scrubbed(text: str, url: str | None) -> str:
    """Foreign text with the URL's held secrets removed, then every pattern."""
    for secret in _held_secrets(url):
        text = text.replace(secret, REDACTED)
    return redact_credentials(text)


__all__ = ["PREFERRED_REMOTE", "REDACTED", "redact_destination",
           "submit_branch"]
