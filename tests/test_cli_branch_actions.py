"""`opendox submit`, the verb (plan 038 T015; #1144 12.4a; openxFactory
`specs/038-.../contracts/cli-http-submit-land.md`).

The CLI half of F12.2's submission block, case by case:

  * the product's own verb pushes the branch and REPORTS where it went
    (12.1a; requirement 11's third scenario), and `--json` prints that report
    as one object;
  * F12.2's own run, end to end: the installed `opendox` console script in a
    child process whose PATH holds `git` and no `gh` (12.4; CF-8), then the
    no-remote case through the same verb, refused, naming the remote, with no
    traceback (12.3; the fourth scenario);
  * a credential in the remote's URL reaches neither the printed report nor a
    refusal (12.1a), the half `tests/test_submission_default.py` leaves to this
    verb;
  * the default branch is refused by name, and never reaches the port, a
    host's included (R2Q5 (a));
  * the install mode is not read; `--local` is refused only where it
    disagrees with `OPENDOX_INSTALL_MODE=hosted`, naming both, and beside any
    other value it is accepted (N-17; R2Q9 (a) item 7);
  * no actor gate (OQ-12-9);
  * under `governed`, the verb goes through the host's contributed port and
    reports where the work went (R2Q4 (a));
  * a failure the port did not name, from the binding or the port, is
    refused with a fixed sentence naming its type alone, never its text and
    never a traceback (12.1a), as the route answers it;
  * the verb is the default profile's contribution, and a host profile that
    replaces the default has no `submit` (N-2; R2Q3 (a)).

The verb exists only on a parser built from openDox's own default profile, so
every case that runs it puts that profile in place first (`standalone_profile`,
as `tests/test_submit_route.py` does); the suite's root conftest otherwise
registers an empty host profile for the whole process.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from opendox import cli, cli_branch_actions, session_pr
from test_submission_default import (  # noqa: F401 - fixtures, by name
    QUERY,
    TICKET,
    TOKEN,
    USERINFO_SECRET,
    _git,
    _isolated_git,
    _smart_http,
    _tip,
    checkout,
    with_userinfo,
)

#: The installed console script, beside this interpreter (plan 034 T038).
OPENDOX = Path(sys.executable).with_name("opendox")


@pytest.fixture()
def standalone_profile():
    """openDox's OWN default profile for one case, and the suite's host
    profile put back afterwards exactly as it was."""
    from opendox import default_profile, domain_profile as dp

    saved = (dp._registered, dp._is_default, dp._built_from_default)
    dp.unregister()
    dp.register_default(default_profile)
    try:
        yield default_profile
    finally:
        dp._registered, dp._is_default, dp._built_from_default = saved


@pytest.fixture
def origin(checkout: Path, tmp_path: Path) -> Path:
    """A bare `origin` beside the checkout, F12.2's own layout."""
    remote = tmp_path / "remote"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(checkout, "remote", "add", "origin", str(remote))
    return remote


@pytest.fixture(autouse=True)
def _no_install_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """F12.2 runs the verb with no `OPENDOX_INSTALL_MODE`; a case that wants
    one sets it."""
    monkeypatch.delenv("OPENDOX_INSTALL_MODE", raising=False)


def _heads(repository: Path) -> str:
    return _git(repository, "for-each-ref", "refs/heads")


def _submit(capsys: pytest.CaptureFixture, checkout: Path, *extra: str,
            branch: str = "sess-1") -> tuple[int, str, str]:
    """`opendox submit` in this process: the exit status, stdout and stderr."""
    status = cli.main(["submit", "--repo-root", str(checkout),
                       "--branch", branch, *extra])
    out, err = capsys.readouterr()
    return status, out, err


# --------------------------------------------------------------------------
# The act, and what the verb prints.
# --------------------------------------------------------------------------

def test_submit_pushes_the_branch_and_reports_where_it_went(
        checkout: Path, origin: Path, standalone_profile,
        capsys: pytest.CaptureFixture) -> None:
    status, out, err = _submit(capsys, checkout)
    tip = _tip(checkout, "sess-1")
    assert (status, err) == (0, ""), err
    assert _tip(origin, "sess-1") == tip, "the branch did not arrive"
    assert out.splitlines() == [
        "submitted `sess-1` to `origin`",
        "  ref:    refs/heads/sess-1",
        f"  url:    {origin}",
        f"  commit: {tip}",
    ]


def test_submit_json_prints_the_submission_object(
        checkout: Path, origin: Path, standalone_profile,
        capsys: pytest.CaptureFixture) -> None:
    status, out, _err = _submit(capsys, checkout, "--json")
    assert status == 0
    assert json.loads(out) == {"remote": "origin", "ref": "refs/heads/sess-1",
                               "url": str(origin), "branch": "sess-1",
                               "commit": _tip(checkout, "sess-1")}


def _gh_free_path(tmp_path: Path) -> str:
    """A PATH holding `git` and nothing else, so `gh` is absent (CF-8)."""
    bin_dir = tmp_path / "gh-free-bin"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(shutil.which("git"))
    path = str(bin_dir)
    assert shutil.which("gh", path=path) is None
    return path


def test_f12_2_runs_the_installed_verb_with_no_gh(
        checkout: Path, origin: Path, tmp_path: Path) -> None:
    """F12.2's own commands, through the console script a student's install
    has, in a child with no `gh` on its PATH and no install mode set: the
    branch arrives and the output names where it went; then, with the remote
    removed, the same verb is refused naming the remote, with no traceback."""
    if not OPENDOX.exists():
        pytest.skip(f"no installed console script at {OPENDOX}")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("GIT_", "XF_", "OPENDOX_INSTALL_MODE"))}
    env.update(PATH=_gh_free_path(tmp_path), HOME=str(tmp_path),
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    command = [str(OPENDOX), "submit", "--repo-root", str(checkout),
               "--branch", "sess-1"]
    done = subprocess.run(command, env=env, capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr
    assert _tip(origin, "sess-1") == _tip(checkout, "sess-1")
    assert str(origin) in done.stdout, done.stdout

    _git(checkout, "remote", "remove", "origin")
    none = subprocess.run(command, env=env, capture_output=True, text=True,
                          timeout=120)
    said = none.stdout + none.stderr
    assert none.returncode != 0, said
    assert "remote" in said.lower(), said
    assert "Traceback" not in said, said


# --------------------------------------------------------------------------
# Refusals: a sentence on stderr, exit 1, nothing pushed, no traceback.
# --------------------------------------------------------------------------

def test_submit_refuses_a_checkout_with_no_remote_naming_it(
        checkout: Path, standalone_profile,
        capsys: pytest.CaptureFixture) -> None:
    status, out, err = _submit(capsys, checkout)
    assert (status, out) == (1, "")
    assert err.startswith("submit refused: no remote is attached"), err
    assert "Traceback" not in err


def test_submit_refuses_the_default_branch(
        checkout: Path, origin: Path, standalone_profile,
        capsys: pytest.CaptureFixture) -> None:
    status, out, err = _submit(capsys, checkout, branch="main")
    assert (status, out) == (1, "")
    assert "`main` is the default branch" in err, err
    assert _heads(origin) == ""


def test_a_credential_in_the_remote_url_reaches_neither_report_nor_refusal(
        checkout: Path, tmp_path: Path, standalone_profile,
        capsys: pytest.CaptureFixture) -> None:
    """12.1a through the verb: the remote's URL carries a userinfo secret and
    two query tokens. The push goes through it, the printed report and the
    `--json` object name the host and the path and none of the secrets, and
    so does the refusal of a second push once nothing listens there."""
    served = tmp_path / "served"
    remote = served / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    with _smart_http(served) as server:
        host = f"127.0.0.1:{server.server_address[1]}"
        _git(checkout, "remote", "add", "origin",
             with_userinfo("http", f"alice:{USERINFO_SECRET}",
                           f"{host}/remote.git?{QUERY}"))
        status, out, err = _submit(capsys, checkout)
        json_status, json_out, _ = _submit(capsys, checkout, "--json")
        assert any(QUERY in seen for seen in server.seen)
    assert (status, json_status, err) == (0, 0, ""), err
    assert _tip(remote, "sess-1") == _tip(checkout, "sess-1")
    report = json.loads(json_out)
    for text in (out, json_out, report["url"]):
        assert host in text and "/remote.git" in text, text
    status, refused_out, refused = _submit(capsys, checkout)
    assert status == 1 and host in refused, refused
    for text in (out, json_out, refused_out, refused):
        for secret in (USERINFO_SECRET, TOKEN, TICKET):
            assert secret not in text, text


# --------------------------------------------------------------------------
# The install mode is not read (N-17); `--local` refused only beside a
# selection it contradicts.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [None, "hosted", "local", "Local"])
def test_without_local_the_install_mode_is_not_read(
        checkout: Path, origin: Path, standalone_profile, mode,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    """The hosted default, `hosted` set, `local` set, even a value the
    selector would refuse: the verb pushes the user's own checkout with the
    user's own git, and asks the selector nothing."""
    if mode is not None:
        monkeypatch.setenv("OPENDOX_INSTALL_MODE", mode)
    status, _out, err = _submit(capsys, checkout)
    assert (status, err) == (0, ""), err
    assert _tip(origin, "sess-1") == _tip(checkout, "sess-1")


@pytest.mark.parametrize("mode", [None, "local"])
def test_local_is_accepted_where_it_agrees(
        checkout: Path, origin: Path, standalone_profile, mode,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    if mode is not None:
        monkeypatch.setenv("OPENDOX_INSTALL_MODE", mode)
    status, _out, err = _submit(capsys, checkout, "--local")
    assert (status, err) == (0, ""), err
    assert _tip(origin, "sess-1") == _tip(checkout, "sess-1")


@pytest.mark.parametrize("mode", ["hosted", " hosted "])
def test_local_beside_hosted_is_refused_naming_both(
        checkout: Path, origin: Path, standalone_profile, mode,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    """R2Q9 (a) item 7: a flag and a setting that disagree are refused, naming
    both, before anything is pushed. The setting is read as the selector
    reads it, stripped."""
    monkeypatch.setenv("OPENDOX_INSTALL_MODE", mode)
    status, out, err = _submit(capsys, checkout, "--local")
    assert (status, out) == (1, "")
    assert err == f"submit refused: {cli_branch_actions.LOCAL_BESIDE_HOSTED}\n"
    assert "--local" in err and "OPENDOX_INSTALL_MODE=hosted" in err, err
    assert _heads(origin) == ""


@pytest.mark.parametrize("mode", ["Hosted", "Local", "single-user"])
def test_local_beside_any_other_value_is_accepted(
        checkout: Path, origin: Path, standalone_profile, mode,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    """The contract refuses `--local` ONLY where it disagrees with
    `OPENDOX_INSTALL_MODE=hosted` (N-17). A value the selector matches as
    neither shape, case included, is not this verb's to judge: the verb does
    not depend on the mode, so it pushes."""
    monkeypatch.setenv("OPENDOX_INSTALL_MODE", mode)
    status, _out, err = _submit(capsys, checkout, "--local")
    assert (status, err) == (0, ""), err
    assert _tip(origin, "sess-1") == _tip(checkout, "sess-1")


# --------------------------------------------------------------------------
# No actor gate (OQ-12-9).
# --------------------------------------------------------------------------

def test_submit_needs_no_actor(
        checkout: Path, origin: Path, standalone_profile,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    """No principal is declared and the checkout carries no git identity, so
    no human could be resolved, and the verb still pushes: it runs as the
    invoking user, and it has no `--actor` to claim one with."""
    from opendox import actor_identity

    for name in (actor_identity.ROSTER_ENV, actor_identity.ALLOWLIST_ENV,
                 actor_identity.PRINCIPAL_ENV, actor_identity.GATEWAY_ENV):
        monkeypatch.delenv(name, raising=False)
    assert actor_identity.authenticated_actor_or_none(
        None, checkout_root=checkout) is None
    status, _out, err = _submit(capsys, checkout)
    assert (status, err) == (0, ""), err
    assert _tip(origin, "sess-1") == _tip(checkout, "sess-1")
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["submit", "--repo-root", str(checkout), "--branch", "sess-1",
             "--actor", "tester"])


# --------------------------------------------------------------------------
# A contributed port (R2Q4 (a)).
# --------------------------------------------------------------------------

class _ContributedPort:
    """A governed host's own `SubmissionPort`, contributed through the CLI's
    `_submission_port` binding."""

    def __init__(self, answer=None, raises=None):
        self.asked: list[str] = []
        self.answer = answer
        self.raises = raises

    def submit(self, branch: str):
        self.asked.append(branch)
        if self.raises is not None:
            raise self.raises
        if self.answer is not None:
            return self.answer
        return session_pr.Submission(
            remote="review", ref=f"refs/heads/{branch}",
            url="https://forge.example/team/repo", branch=branch,
            commit="c" * 40)


def test_a_contributed_port_is_what_the_verb_submits_through(
        checkout: Path, origin: Path, standalone_profile,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    port = _ContributedPort()
    handed: list[Path] = []

    def contributed(repo_root: Path) -> _ContributedPort:
        handed.append(repo_root)
        return port

    monkeypatch.setattr(cli, "_submission_port", contributed)
    status, out, err = _submit(capsys, checkout)
    assert (status, err) == (0, ""), err
    assert port.asked == ["sess-1"] and handed == [checkout]
    assert "  url:    https://forge.example/team/repo" in out.splitlines()
    assert "submitted `sess-1` to `review`" in out
    assert _heads(origin) == "", "the neutral default pushed beside the host's"


def test_the_default_branch_never_reaches_a_contributed_port(
        checkout: Path, standalone_profile, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    port = _ContributedPort()
    monkeypatch.setattr(cli, "_submission_port", lambda _root: port)
    status, _out, err = _submit(capsys, checkout, branch="main")
    assert status == 1 and "`main` is the default branch" in err, err
    assert port.asked == []


@pytest.mark.parametrize("raised_by", ["binding", "port"])
def test_a_port_failure_it_did_not_name_is_refused_without_its_text(
        checkout: Path, origin: Path, standalone_profile, raised_by: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    """Lane 3's review R1 of T015 (#656 `6064547745`), the route's
    `test_a_port_failure_it_did_not_name_is_reported_without_its_text` for
    the verb. A host's binding that cannot build its port, or a host's port
    whose `submit` raises something other than a `SubmissionError`: a fixed
    refusal naming the TYPE alone and exit 1, never the exception's text (here
    a credential in a remote URL, 12.1a) and never a traceback."""
    secret = "S3CRET-from-a-host-port"
    failure = RuntimeError(f"push to https://user:{secret}@forge.example/x failed")
    port = _ContributedPort(raises=failure)

    def binding(_root: Path) -> _ContributedPort:
        if raised_by == "binding":
            raise failure
        return port

    monkeypatch.setattr(cli, "_submission_port", binding)
    status, out, err = _submit(capsys, checkout)
    assert (status, out) == (1, "")
    assert err == ("submit refused: " + cli_branch_actions.UNNAMED_FAILURE.format(
        kind="RuntimeError") + "\n"), err
    assert secret not in err and "Traceback" not in err
    assert port.asked == ([] if raised_by == "binding" else ["sess-1"])
    assert _heads(origin) == ""


@pytest.mark.parametrize("missing", cli_branch_actions.SUBMISSION_FIELDS)
def test_a_report_that_does_not_name_where_the_work_went_is_refused(
        checkout: Path, standalone_profile, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture, missing: str) -> None:
    fields = {"remote": "r", "ref": "refs/heads/sess-1", "url": "u",
              "branch": "sess-1", "commit": "c" * 40}
    fields[missing] = ""
    port = _ContributedPort(answer=session_pr.Submission(**fields))
    monkeypatch.setattr(cli, "_submission_port", lambda _root: port)
    status, out, err = _submit(capsys, checkout)
    assert (status, out) == (1, "")
    assert f"carries no `{missing}`" in err, err


def test_submission_object_reads_the_five_fields_by_name() -> None:
    class _Report:
        remote, ref, url, branch, commit = "o", "refs/heads/b", "u", "b", "c"
        extra = "never read"

    assert cli_branch_actions.submission_object(_Report()) == {
        "remote": "o", "ref": "refs/heads/b", "url": "u", "branch": "b",
        "commit": "c"}
    with pytest.raises(session_pr.SubmissionRefused, match="no `remote`"):
        cli_branch_actions.submission_object(None)
    _Report.url = 7
    with pytest.raises(session_pr.SubmissionRefused, match="no `url`"):
        cli_branch_actions.submission_object(_Report())


# --------------------------------------------------------------------------
# The verb is the default profile's contribution (N-2; R2Q3 (a)).
# --------------------------------------------------------------------------

def _verbs(parser) -> dict:
    import argparse

    (action,) = [a for a in parser._actions
                 if isinstance(a, argparse._SubParsersAction)]
    return action.choices


def test_the_default_profile_contributes_submit(standalone_profile) -> None:
    verbs = _verbs(cli.build_parser())
    assert "submit" in verbs
    args = cli.build_parser().parse_args(
        ["submit", "--repo-root", "r", "--branch", "b", "--local", "--json"])
    assert args.func is cli_branch_actions.cmd_submit
    assert (args.repo_root, args.branch, args.local, args.json) == (
        "r", "b", True, True)
    assert any(isinstance(extension, cli_branch_actions.BranchActionSubcommands)
               for extension in standalone_profile.SUBCOMMAND_EXTENSIONS)


def test_a_host_profile_replacing_the_default_has_no_submit() -> None:
    """This suite's own registered host profile replaces the default, so its
    parser carries no `submit` and refuses the command line."""
    from opendox import default_profile, domain_profile

    assert domain_profile.current() is not default_profile
    assert "submit" not in _verbs(cli.build_parser())
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["submit", "--repo-root", "r", "--branch", "b"])
