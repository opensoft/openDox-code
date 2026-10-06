"""`session_pr.SubmissionPort` and its neutral default, `LocalGitSubmissions`
(plan 038 T011; #1144 boxes 12.1, 12.1a, 12.2 and 12.3).

Every remote here is a LOCAL bare repository, never the network; the one
credential-bearing remote F12.2 needs is in `test_submission_default.py`. Each
refusal is asserted twice over: the exception's TYPE (12.3: "catch that type
and nothing else"), and that nothing reached any remote.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

from opendox import session_pr, submission_push
from opendox.runtime import repository_act
from opendox.runtime.local_git_adapter import GitRunner
from opendox.session_pr import (
    LocalGitSubmissions,
    NoSubmissionTarget,
    Submission,
    SubmissionError,
    SubmissionRefused,
)
from test_submission_default import (  # noqa: F401 - fixtures, by name
    _git,
    _isolated_git,
    _tip,
    checkout,
    with_userinfo,
)


def _bare(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
    return path


def _heads(repository: Path) -> str:
    return _git(repository, "for-each-ref", "refs/heads")


@pytest.fixture
def origin(checkout: Path, tmp_path: Path) -> Path:
    """A bare `origin` BESIDE the checkout, which is F12.2's own layout."""
    remote = _bare(tmp_path / "remote")
    _git(checkout, "remote", "add", "origin", str(remote))
    return remote


# -- 12.1: the protocol, split from the platform's ---------------------------


def test_the_submission_port_is_its_own_one_operation_protocol(
        tmp_path: Path) -> None:
    """12.1: ONE operation, beside `PullRequestPort` and never inside it."""
    assert session_pr.SUBMISSION_OPERATIONS == ("submit",)
    declared = {name for name in vars(session_pr.SubmissionPort)
                if not name.startswith("_")}
    assert declared == {"submit"}
    # THE PLATFORM PROTOCOL IS UNCHANGED (12.1; FR-030).
    assert session_pr.PORT_OPERATIONS == ("push", "open_or_update",
                                          "find_open")

    port = LocalGitSubmissions(tmp_path)
    assert isinstance(port, session_pr.SubmissionPort)
    assert not isinstance(port, session_pr.PullRequestPort), (
        "a push-only class claims the platform protocol")
    for name in (*session_pr.PORT_OPERATIONS, "merge", "approve", "land"):
        assert not hasattr(port, name), name
    for platform in (session_pr.FakePullRequests(),
                     session_pr.GhPullRequests(tmp_path)):
        assert not isinstance(platform, session_pr.SubmissionPort)

    # The report's fields, and the two named failures under one base.
    assert [f.name for f in dataclasses.fields(Submission)] == [
        "remote", "ref", "url", "branch", "commit"]
    assert issubclass(NoSubmissionTarget, SubmissionError)
    assert issubclass(SubmissionRefused, SubmissionError)
    assert not issubclass(NoSubmissionTarget, SubmissionRefused)
    assert not issubclass(SubmissionRefused, NoSubmissionTarget)


# -- 12.2: the push, and the report -------------------------------------------


def test_a_branch_is_pushed_to_origin_and_the_report_names_where_it_went(
        checkout: Path, origin: Path) -> None:
    """12.2 and 12.1a, on F12.2's layout: the bare remote sits BESIDE the
    checkout, which the runtime's service-root containment would refuse.

    The branch arrives at the commit the report names; nothing else moves,
    in the remote or in the checkout (no upstream is written); and a second
    submit of the same tip is the same report (F12.2: "idempotent")."""
    config = (checkout / ".git" / "config").read_bytes()
    head = _git(checkout, "rev-parse", "HEAD")
    tip = _tip(checkout, "sess-1")

    report = LocalGitSubmissions(checkout).submit("sess-1")

    assert report == Submission(remote="origin", ref="refs/heads/sess-1",
                                url=str(origin), branch="sess-1", commit=tip)
    assert _tip(origin, "sess-1") == tip
    assert _heads(origin).count("refs/heads/") == 1, _heads(origin)
    assert (checkout / ".git" / "config").read_bytes() == config
    assert _git(checkout, "rev-parse", "HEAD") == head

    assert LocalGitSubmissions(str(checkout)).submit("sess-1") == report


def test_a_sole_remote_of_any_name_is_the_target(
        checkout: Path, tmp_path: Path) -> None:
    """12.3 with ADV-26: "a remote attached" holds for a sole remote of any
    name, not only `origin`."""
    upstream = _bare(tmp_path / "upstream.git")
    _git(checkout, "remote", "add", "upstream", str(upstream))
    report = LocalGitSubmissions(checkout).submit("sess-1")
    assert (report.remote, report.url) == ("upstream", str(upstream))
    assert _tip(upstream, "sess-1") == _tip(checkout, "sess-1")


def test_origin_is_the_target_among_several_remotes(
        checkout: Path, tmp_path: Path) -> None:
    """ADV-26: the one named `origin` wins, whatever the others are called or
    in which order git lists them."""
    remotes = {name: _bare(tmp_path / f"{name}.git")
               for name in ("aaa", "origin", "zzz")}
    for name, path in remotes.items():
        _git(checkout, "remote", "add", name, str(path))
    assert LocalGitSubmissions(checkout).submit("sess-1").remote == "origin"
    assert _tip(remotes["origin"], "sess-1") == _tip(checkout, "sess-1")
    for name in ("aaa", "zzz"):
        assert _heads(remotes[name]) == "", name


# -- 12.3: no target ------------------------------------------------------------


def test_no_remote_is_no_submission_target_naming_what_is_missing(
        checkout: Path) -> None:
    """12.3: not an opaque failure and not a reported success; the TYPE is
    `NoSubmissionTarget` and the message names the missing remote."""
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit("sess-1")
    assert type(caught.value) is NoSubmissionTarget
    assert "no remote is attached" in str(caught.value)


def test_several_remotes_and_none_named_origin_are_refused_by_name(
        checkout: Path, tmp_path: Path) -> None:
    """CF-7 (`6013547504`): several remotes and none named `origin` is
    `NoSubmissionTarget`, naming them, and nothing is pushed anywhere."""
    remotes = [_bare(tmp_path / f"{name}.git") for name in ("aaa", "bbb")]
    for path in remotes:
        _git(checkout, "remote", "add", path.stem, str(path))
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit("sess-1")
    message = str(caught.value)
    assert type(caught.value) is NoSubmissionTarget
    for said in ("several remotes", "`origin`", "`aaa`", "`bbb`"):
        assert said in message, said
    for path in remotes:
        assert _heads(path) == "", path


# -- the branch: R2Q5 (a) -------------------------------------------------------


def test_the_default_branch_is_refused(checkout: Path, origin: Path) -> None:
    """R2Q5 (a): any local branch EXCEPT `main`."""
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit("main")
    assert type(caught.value) is SubmissionRefused
    assert "`main` is the default branch" in str(caught.value)
    assert _heads(origin) == ""


@pytest.mark.parametrize(("branch", "said"), [
    ("no-such-branch", "has no local branch `no-such-branch`"),
    ("sess-1~1", "not a valid git branch name"),
    ("sess-1^{tree}", "not a valid git branch name"),
    ("", "not a valid git branch name"),
])
def test_a_branch_that_is_not_there_or_not_a_name_is_refused(
        checkout: Path, origin: Path, branch: str, said: str) -> None:
    """The name is checked as a REF NAME before `rev-parse` reads it, so a
    revision expression never selects a commit to push."""
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit(branch)
    assert type(caught.value) is SubmissionRefused
    assert said in str(caught.value)
    assert _heads(origin) == ""


# -- the destination ------------------------------------------------------------


def test_several_push_urls_are_refused(checkout: Path, tmp_path: Path) -> None:
    """git pushes to EACH push URL, and a submission reports one destination."""
    first, second = (_bare(tmp_path / name) for name in ("a.git", "b.git"))
    _git(checkout, "remote", "add", "origin", str(first))
    _git(checkout, "remote", "set-url", "--add", "--push", "origin", str(first))
    _git(checkout, "remote", "set-url", "--add", "--push", "origin",
         str(second))
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit("sess-1")
    assert type(caught.value) is SubmissionRefused
    assert "would push to 2 destinations" in str(caught.value)
    assert str(first) not in str(caught.value), "the URLs were echoed"
    assert _heads(first) == ""
    assert _heads(second) == ""


def test_a_push_url_with_surrounding_whitespace_is_refused_not_trimmed(
        checkout: Path, tmp_path: Path) -> None:
    """Git keeps surrounding whitespace in a configured URL, and for a local
    path it names another directory: `<dir>/remote ` is not `<dir>/remote`.
    A trimmed reading would push to the second; the URL is refused instead."""
    trimmed = _bare(tmp_path / "remote")
    _git(checkout, "remote", "add", "origin", f"{trimmed} ")
    kept = subprocess.run(["git", "-C", str(checkout), "config",
                           "remote.origin.url"], capture_output=True,
                          text=True).stdout
    assert kept == f"{trimmed} \n", "git trimmed it; this case measures nothing"
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit("sess-1")
    assert type(caught.value) is SubmissionRefused
    assert "or trailing whitespace" in str(caught.value)
    assert _heads(trimmed) == ""


@pytest.mark.parametrize("shape", ["trailing", "leading"])
def test_a_push_url_with_a_newline_is_refused_not_normalized(
        checkout: Path, tmp_path: Path, shape: str) -> None:
    """MEASURED on git 2.43.0: git keeps a newline in a configured URL and
    `get-url --push --all` prints it, so `<dir>/remote` plus a newline reads
    as two lines, one of them empty. Dropping the empty one would push to
    `<dir>/remote`, which git does not mean; it counts as two and is
    refused."""
    plain = _bare(tmp_path / "remote")
    url = f"{plain}\n" if shape == "trailing" else f"\n{plain}"
    subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin",
                    url], check=True)
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit("sess-1")
    assert type(caught.value) is SubmissionRefused
    assert "would push to 2 destinations" in str(caught.value)
    assert str(plain) not in str(caught.value), "the URL was echoed"
    assert _heads(plain) == ""


def test_a_linked_worktree_is_submitted_with_its_metadata_held_open(
        checkout: Path, origin: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A linked worktree's `.git` is a FILE naming its git and common
    directories elsewhere. Both are held by descriptor for the whole
    submission (`metadata_held_open`), so the runner the push core receives
    names them as `/proc/self/fd/<n>` and the push still lands."""
    linked = tmp_path / "linked"
    _git(checkout, "worktree", "add", "-q", str(linked), "sess-1")
    seen: list[dict[str, str]] = []
    real = repository_act._push_to_remote_with

    def _spy(git: GitRunner, plan: repository_act.PushPlan) -> None:
        seen.append(dict(git.held_environment))
        real(git, plan)

    monkeypatch.setattr(repository_act, "_push_to_remote_with", _spy)
    report = LocalGitSubmissions(linked).submit("sess-1")
    assert report.commit == _tip(checkout, "sess-1")
    assert _tip(origin, "sess-1") == report.commit
    assert len(seen) == 1
    assert set(seen[0]) == {"GIT_DIR", "GIT_COMMON_DIR"}
    for name, value in seen[0].items():
        assert value.startswith(("/proc/self/fd/", "/dev/fd/")), (name, value)


def test_a_remote_with_no_url_is_refused_not_pushed_to_as_a_path(
        checkout: Path) -> None:
    """MEASURED on git 2.43.0: `git remote get-url --push --all origin` for a
    remote with a fetch refspec and no URL prints `origin`, which a push would
    then treat as a path beside the checkout."""
    _git(checkout, "config", "remote.origin.fetch",
         "+refs/heads/*:refs/remotes/origin/*")
    beside = _bare(checkout / "origin")      # what the name would reach
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit("sess-1")
    assert type(caught.value) is SubmissionRefused
    assert "names no URL" in str(caught.value)
    assert _heads(beside) == ""


def test_a_rejected_push_is_refused_and_moves_nothing(
        checkout: Path, origin: Path) -> None:
    """A non-fast-forward is the remote's refusal; never `--force`."""
    _git(checkout, "push", "-q", "origin", "main:refs/heads/sess-1")
    _git(checkout, "switch", "-q", "-c", "ahead", "main")
    _git(checkout, "commit", "-q", "--allow-empty", "-m", "ahead")
    _git(checkout, "push", "-q", "origin", "ahead:refs/heads/sess-1")
    moved = _tip(origin, "sess-1")
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit("sess-1")
    assert type(caught.value) is SubmissionRefused
    assert "the push of `sess-1` to `origin`" in str(caught.value)
    assert _tip(origin, "sess-1") == moved


@pytest.mark.parametrize("where", ["a path that is not there",
                                   "http://127.0.0.1:1/remote.git",
                                   "file://[not-a-host/remote.git"])
def test_a_transport_failure_is_refused(checkout: Path, tmp_path: Path,
                                        where: str) -> None:
    """A destination that cannot be reached, or read, raises by name; port 1
    on loopback answers no one, so the second case never leaves the machine,
    and the third is a URL `urlsplit` refuses (`ValueError`)."""
    url = str(tmp_path / "missing.git") if where.startswith("a path") else where
    _git(checkout, "remote", "add", "origin", url)
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit("sess-1")
    assert type(caught.value) is SubmissionRefused
    assert "Traceback" not in str(caught.value)


# -- the runtime's hardening, kept (OQ-12-12) ----------------------------------


@pytest.mark.parametrize("key", [*repository_act._EXECUTED_LOCAL_KEYS,
                                 "remote.origin.vcs", "url.x.insteadOf"])
def test_a_checkout_whose_own_config_names_a_program_is_refused(
        checkout: Path, origin: Path, tmp_path: Path, key: str) -> None:
    """The repository-local command-config refusal the runtime's push makes is
    the submission's too: refused, named, and the program never runs."""
    marker = tmp_path / "ran"
    _git(checkout, "config", "--local", key, f"!touch {marker}")
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit("sess-1")
    assert type(caught.value) is SubmissionRefused
    assert key.lower() in str(caught.value).lower()
    assert not marker.exists()
    assert _heads(origin) == ""


@pytest.mark.parametrize("url", ["ext::sh -c touch% {marker}",
                                 "evil::{marker}"])
def test_a_remote_that_names_a_command_is_refused(
        checkout: Path, tmp_path: Path, url: str) -> None:
    """`<name>::<address>` makes git run `git-remote-<name>`: refused before
    any push, as the runtime refuses it."""
    marker = tmp_path / "ran"
    _git(checkout, "remote", "add", "origin", url.format(marker=marker))
    port = LocalGitSubmissions(checkout)
    with pytest.raises(SubmissionError) as caught:
        port.submit("sess-1")
    assert type(caught.value) is SubmissionRefused
    assert "runs a command" in str(caught.value)
    assert not marker.exists()


def test_no_hook_runs_on_either_side(checkout: Path, origin: Path,
                                     tmp_path: Path) -> None:
    """The core's two hook guards hold for a submission: the checkout's own
    `pre-push` and the local destination's `pre-receive` do not run, and the
    push still lands."""
    marker = tmp_path / "ran"
    for hook in (checkout / ".git" / "hooks" / "pre-push",
                 origin / "hooks" / "pre-receive"):
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
        hook.chmod(0o755)
    LocalGitSubmissions(checkout).submit("sess-1")
    assert _tip(origin, "sess-1") == _tip(checkout, "sess-1")
    assert not marker.exists()


def test_the_runtime_push_keeps_its_containment_and_the_submission_skips_it(
        checkout: Path, origin: Path) -> None:
    """The ONE runtime check a submission does not make, asked of the shared
    bind directly: by default a destination beside the repository is inside
    the service's root and refused; `contained=False` binds it."""
    with pytest.raises(repository_act.RepositoryActRefused) as caught:
        repository_act._bound_local_destination(str(origin), checkout)
    assert "inside the repository root this service owns" in str(caught.value)
    handle, bound = repository_act._bound_local_destination(
        str(origin), checkout, contained=False)
    try:
        assert handle is not None
        assert bound.endswith(f"/{handle}")
    finally:
        os.close(handle)


def test_the_runtime_plans_its_own_push_as_before_and_the_core_sends_it(
        tmp_path: Path) -> None:
    """The factoring, asked of the runtime's half without a database: the map
    row is still the destination of record, HEAD's branch is still the one
    pushed, the destination's identity is still carried to the open, and the
    containment is still asked. The core then sends exactly that plan."""
    root = tmp_path / "service-root"
    location = root / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(location)],
                   check=True)
    empty_tree = subprocess.run(
        ["git", "-C", str(location), "hash-object", "-t", "tree", "-w",
         "--stdin"], input="", check=True, capture_output=True,
        text=True).stdout.strip()
    seed = _git(location, "commit-tree", "-m", "seed", empty_tree)
    _git(location, "update-ref", "refs/heads/main", seed)
    governed = _bare(tmp_path / "elsewhere" / "governed.git")
    _git(location, "remote", "add", "origin", str(governed))
    row = SimpleNamespace(location=location, remote_url=str(governed),
                          project_id="p")
    git = GitRunner(location)

    plan = repository_act._mapped_push_plan(git, row)

    seen = os.stat(governed)
    assert plan == repository_act.PushPlan(
        location=location, remote_name="origin", destination=str(governed),
        refspec="refs/heads/main:refs/heads/main",
        checked=(seen.st_dev, seen.st_ino), contained=True)
    repository_act._push_to_remote_with(git, plan)
    assert _tip(governed, "main") == seed


# -- the checkout ------------------------------------------------------------------


@pytest.mark.parametrize("which", ["a directory inside it", "no repository",
                                   "nothing there"])
def test_a_checkout_root_that_is_not_a_repository_root_is_refused(
        checkout: Path, origin: Path, tmp_path: Path, which: str) -> None:
    """`git -C <dir>` walks up, so a directory inside a checkout would submit
    the enclosing one; it is refused, as the runtime refuses it."""
    root = {"a directory inside it": checkout / "inner",
            "no repository": tmp_path / "plain-directory",
            "nothing there": tmp_path / "absent"}[which]
    if which != "nothing there":
        root.mkdir()
    port = LocalGitSubmissions(root)
    with pytest.raises(SubmissionError) as caught:
        port.submit("sess-1")
    assert type(caught.value) is SubmissionRefused
    assert _heads(origin) == ""


# -- 12.1a: what a report may show ---------------------------------------------


@pytest.mark.parametrize(("url", "shown"), [
    pytest.param(
        with_userinfo("https", "alice:S3CRET",
                      "example.invalid/o/r.git?token=T0KEN#S3CFRAG"),
        "https://<redacted>@example.invalid/o/r.git?token=<redacted>"
        "#<redacted>", id="userinfo-query-fragment"),
    pytest.param(
        with_userinfo("https", "ghp_T0KENASUSERNAME", "github.com/o/r.git"),
        "https://<redacted>@github.com/o/r.git", id="token-as-user-name"),
    pytest.param(
        "https://example.invalid:8443/r.git?x=S3CRETX&y=S3CRETY",
        "https://example.invalid:8443/r.git?x=<redacted>&y=<redacted>",
        id="every-query-value"),
    pytest.param(
        with_userinfo("ssh", "git:S3CRET", "example.invalid/o/r.git"),
        "ssh://<redacted>@example.invalid/o/r.git", id="ssh-password"),
    pytest.param(
        "ssh://git@example.invalid/o/r.git",
        "ssh://git@example.invalid/o/r.git", id="ssh-login-name-kept"),
    pytest.param(
        "git@example.invalid:o/r.git", "git@example.invalid:o/r.git",
        id="scp-login-name-kept"),
    pytest.param(
        "user:S3CRET@example.invalid:o/r.git", "<redacted-url>",
        id="scp-password"),
    pytest.param("/srv/repos/r.git", "/srv/repos/r.git", id="local-path"),
    pytest.param("file:///srv/repos/r.git", "file:///srv/repos/r.git",
                 id="file-url"),
    pytest.param("https://example.invalid/r.git\n@S3CRET", "<redacted-url>",
                 id="control-character"),
])
def test_a_report_names_the_place_and_never_the_credential(
        url: str, shown: str) -> None:
    """12.1a: userinfo and every query and fragment value are replaced; the
    scheme, host, port and path stay. An ssh LOGIN NAME is not a credential
    and stays; an `https` user name alone may be a token and does not."""
    assert submission_push.redact_destination(url) == shown
    assert "S3C" not in shown
    assert "T0KEN" not in shown
