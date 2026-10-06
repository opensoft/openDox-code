"""#1144 F12.2's two `tests/test_submission_default.py` nodes (plan 038).

F12.2 names two nodes in this file, and each lands with the box it proves:

  * `test_a_credential_in_the_remote_url_never_reaches_the_report`, with
    plan 038 T011 (12.1a: the `Submission` names where the work went, and
    never what the remote URL holds);
  * `test_server_unset_submission_factory_binds_the_neutral_default`, with
    T014, which adds the binding it asserts (`serve.submission_factory`,
    12.4; R2Q2 (a)). It uses the same checkout fixture.

T014 adds two more nodes beside its own, so each new branch of the binding
has a case that fails without it: an injected factory is the binding, and one
that cannot build a port is absence (`submission_factory`'s compose entry and
its accessor); and the CLI's unset `_submission_port` is the same neutral
class. F12.2's block asserts that last one inline as well, but only once the
`submit` verb exists (T015), so the suite carries its own case.

`tests/test_submission_port.py` imports this file's fixtures (`_isolated_git`,
`checkout`) and git helpers, so the two build their repositories one way.

THE CREDENTIAL NODE PUSHES FOR REAL, over loopback and never the network. A
bare local remote carries no credential and so cannot show a leak, which is
why F12.2 names this test at all. So the remote here is a smart-HTTP endpoint
on `127.0.0.1`: `git http-backend` behind a stdlib server, whose URL carries a
userinfo credential AND a query-string token. The push really reaches it (the
branch arrives, and the server saw the token), so "a credential-bearing remote
is PUSHED, not refused" (ADV-09) is measured rather than assumed. Then the
three ways a push can fail are driven against the same URL: rejected, several
push URLs, and a transport that is not there.

The verb's printed report (`opendox submit`) is 12.4a's, and its half of this
assertion lands with that verb (T015). What `submit` prints is the
`Submission`, whose every field this node asserts on.
"""

from __future__ import annotations

import http.server
import os
import subprocess
import threading
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from opendox import cli, serve, session_pr

#: The served web root, which `build_server` needs and these nodes never read.
WEB = Path(__file__).resolve().parent.parent / "src" / "opendox" / "web"

#: The secrets the remote URL carries, distinct and greppable: a userinfo
#: secret, a query token under a credential-shaped name, and one under a
#: name no pattern knows, which only the held-value scrub can remove.
USERINFO_SECRET = "pw-S3CRET-userinfo-7f41"
TOKEN = "tok-S3CRET-query-91c2"
TICKET = "tkt-S3CRET-query-5be0"
QUERY = f"token={TOKEN}&ticket={TICKET}"


@pytest.fixture(autouse=True)
def _isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No developer's git configuration reaches these pushes.

    A successful HTTP request that carried a password makes git `approve` it
    to every configured credential helper, so without this the developer's own
    credential store would be handed the fixture's secret. An empty global
    config and no system config keep the push to what the test configures.
    """
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    for name, value in (("GIT_AUTHOR_NAME", "fixture"),
                        ("GIT_AUTHOR_EMAIL", "fixture@example.invalid"),
                        ("GIT_COMMITTER_NAME", "fixture"),
                        ("GIT_COMMITTER_EMAIL", "fixture@example.invalid")):
        monkeypatch.setenv(name, value)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _tip(repository: Path, ref: str) -> str | None:
    """The commit `ref` (a branch name, or a full ref) names, or None."""
    found = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--verify", "--quiet",
         ref if ref.startswith("refs/") else f"refs/heads/{ref}"],
        capture_output=True, text=True)
    return found.stdout.strip() if found.returncode == 0 else None


def with_userinfo(scheme: str, userinfo: str, rest: str) -> str:
    """`scheme://userinfo@rest`, assembled, so no credential-shaped URL is
    spelled whole in this tree's source."""
    return f"{scheme}://{userinfo}@{rest}"


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """F12.2's plain repository: `main` seeded, and a session branch `sess-1`
    carrying one commit of its own."""
    plain = tmp_path / "plain"
    subprocess.run(["git", "init", "-q", "-b", "main", str(plain)], check=True)
    _git(plain, "commit", "-q", "--allow-empty", "-m", "seed")
    _git(plain, "switch", "-q", "-c", "sess-1")
    _git(plain, "commit", "-q", "--allow-empty", "-m", "session work")
    _git(plain, "switch", "-q", "main")
    return plain


class _SmartHTTP(http.server.BaseHTTPRequestHandler):
    """`git http-backend` as CGI, on loopback.

    GIT APPENDS ITS OWN PATH TO A URL THAT CARRIES A QUERY, measured on git
    2.43.0: `…/remote.git?<q>` is asked as `/remote.git?<q>/info/refs&service=
    git-receive-pack` and then as `/remote.git?<q>/git-receive-pack`. So the
    request is recorded (that is the proof the query was sent), the query is
    taken out, and the request is put back together for the backend.
    """

    server: "_Server"

    def log_message(self, *args: object) -> None:   # quiet
        pass

    def do_GET(self) -> None:          # noqa: N802 - the stdlib's spelling
        self._backend()

    def do_POST(self) -> None:         # noqa: N802
        self._backend()

    def _backend(self) -> None:
        self.server.seen.append(self.path)
        target = self.path.replace(f"?{QUERY}", "", 1)
        path, _, query = target.partition("?" if "?" in target else "&")
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        env = {"PATH": os.environ["PATH"], "GIT_PROJECT_ROOT": self.server.root,
               "GIT_HTTP_EXPORT_ALL": "1", "REMOTE_USER": "fixture",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "REQUEST_METHOD": self.command, "PATH_INFO": path,
               "QUERY_STRING": query, "CONTENT_LENGTH": str(len(body)),
               "CONTENT_TYPE": self.headers.get("Content-Type", "")}
        out = subprocess.run(["git", "http-backend"], input=body, env=env,
                             capture_output=True, check=False).stdout
        head, _, payload = out.partition(b"\r\n\r\n")
        status, headers = 200, []
        for line in head.decode("latin-1").split("\r\n"):
            name, _, value = line.partition(":")
            if name.lower() == "status":
                status = int(value.split()[0])
            elif name:
                headers.append((name, value.strip()))
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _Server(http.server.ThreadingHTTPServer):
    root: str
    seen: list[str]


@contextmanager
def _smart_http(root: Path) -> Iterator[_Server]:
    server = _Server(("127.0.0.1", 0), _SmartHTTP)
    server.root, server.seen = str(root), []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def _assert_refusal_clean(refusal: BaseException, where: str) -> None:
    """The message, AND the traceback a logger would print: a chained cause
    carries git's own text, which no pattern cleans of a neutral-named
    query value."""
    _assert_clean(str(refusal), f"{where}'s message")
    _assert_clean("".join(traceback.format_exception(refusal)),
                  f"{where}'s traceback")


def _assert_clean(text: str, where: str) -> None:
    for secret in (USERINFO_SECRET, TOKEN, TICKET):
        assert secret not in text, f"{where} carries a secret: {text!r}"


def test_a_credential_in_the_remote_url_never_reaches_the_report(
        checkout: Path, tmp_path: Path) -> None:
    """12.1a, F12.2: a credential in the remote's URL is pushed with, and never
    shown — not in `Submission.url`, not in the report, and not in the message
    of a rejected, refused or failed push. The report still names the remote's
    host and path."""
    served = tmp_path / "served"
    remote = served / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    port = session_pr.LocalGitSubmissions(checkout)

    with _smart_http(served) as server:
        host = f"127.0.0.1:{server.server_address[1]}"
        url = with_userinfo("http", f"alice:{USERINFO_SECRET}",
                            f"{host}/remote.git?{QUERY}")
        _git(checkout, "remote", "add", "origin", url)

        # PUSHED, not refused (ADV-09), and the report names where it went.
        report = port.submit("sess-1")
        assert _tip(remote, "sess-1") == _tip(checkout, "sess-1"), (
            "the branch did not arrive")
        assert any(QUERY in seen for seen in server.seen), (
            "the push did not go through the credential-bearing URL")
        assert report.commit == _tip(checkout, "sess-1")
        assert (report.remote, report.ref, report.branch) == (
            "origin", "refs/heads/sess-1", "sess-1")
        for where, text in (("Submission.url", report.url),
                            ("the report", repr(report)),
                            ("the report", str(report))):
            _assert_clean(text, where)
        assert host in report.url, report.url
        assert "/remote.git" in report.url, report.url

        # REJECTED: the remote's branch moved on, so the push is not a
        # fast-forward. git echoes the query string in its own error.
        _git(checkout, "switch", "-q", "-c", "elsewhere", "main")
        _git(checkout, "commit", "-q", "--allow-empty", "-m", "elsewhere")
        _git(checkout, "push", "-q", "origin", "elsewhere:refs/heads/sess-2")
        _git(checkout, "switch", "-q", "-c", "sess-2", "main")
        _git(checkout, "commit", "-q", "--allow-empty", "-m", "diverged")
        moved = _tip(remote, "sess-2")
        with pytest.raises(session_pr.SubmissionRefused) as rejected:
            port.submit("sess-2")
        assert _tip(remote, "sess-2") == moved
        _assert_refusal_clean(rejected.value, "a rejected push")
        assert "sess-2" in str(rejected.value)

        # REFUSED: two push URLs, both carrying the credential.
        _git(checkout, "remote", "set-url", "--add", "--push", "origin", url)
        _git(checkout, "remote", "set-url", "--add", "--push", "origin",
             url.replace("remote.git", "other.git"))
        with pytest.raises(session_pr.SubmissionRefused) as refused:
            port.submit("sess-1")
        _assert_refusal_clean(refused.value, "a refused push")
        _git(checkout, "config", "--unset-all", "remote.origin.pushurl")

    # FAILED: the same URL, with nothing listening on it any more.
    with pytest.raises(session_pr.SubmissionRefused) as failed:
        port.submit("sess-1")
    message = str(failed.value)
    _assert_refusal_clean(failed.value, "a failed push")
    assert host in message, message


# --------------------------------------------------------------------------
# The two bindings (plan 038 T014; #1144 12.4; R2Q2 (a)).
# --------------------------------------------------------------------------

def _served_handler(checkout: Path, tmp_path: Path, **injected: object) -> type:
    """The handler class a loopback server over `checkout` is bound with, built
    with nothing injected but what is named. `tester` is one of the suite's
    declared principals (`session_fixtures.GATE_TEST_PRINCIPALS`), so the
    plane is a local human's. The server is closed before the class is read;
    the class keeps its binding."""
    httpd = serve.build_server(WEB, tmp_path / "snapshot.json", checkout,
                               actor="tester", **injected)
    try:
        bound = httpd.RequestHandlerClass
    finally:
        httpd.server_close()
    return getattr(bound, "func", bound)


def _bare_origin(checkout: Path, tmp_path: Path) -> Path:
    """A local bare repository attached to `checkout` as `origin`."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(checkout, "remote", "add", "origin", str(remote))
    return remote


def _assert_the_neutral_port(port: object, checkout: Path, remote: Path) -> None:
    """`port` is `LocalGitSubmissions` for `checkout`, and pushes there."""
    assert isinstance(port, session_pr.LocalGitSubmissions), (
        f"the default names a platform: {type(port)}")
    assert isinstance(port, session_pr.SubmissionPort)
    assert not isinstance(port, session_pr.PullRequestPort), (
        "a push-only class claims the platform protocol")
    assert port.checkout_root.resolve() == checkout.resolve(), port.checkout_root
    report = port.submit("sess-1")
    assert _tip(remote, "sess-1") == _tip(checkout, "sess-1"), (
        "the branch did not arrive")
    assert report.ref == "refs/heads/sess-1" and str(remote) in report.url, report


def test_server_unset_submission_factory_binds_the_neutral_default(
        checkout: Path, tmp_path: Path) -> None:
    """12.4, F12.2: a server built with NOTHING injected binds the neutral
    `LocalGitSubmissions` for its own checkout, and it pushes there. A class
    built by hand proves nothing about what the product binds, which is why
    F12.2 names this node.

    Beside it, the platform pair is unchanged (R2Q2 (a)): the unset
    `pull_request_factory` still builds `GhPullRequests`, which only
    openXdox's `gate open-pr` reaches (openXdox-code's
    `tests/test_session_snapshot.py:893-916` pins the same). And a hosted
    handler declares no submission port, for the reason it declares no
    pull-request port: each pushes with the invoking user's own credentials,
    which a hosted plane never holds."""
    remote = _bare_origin(checkout, tmp_path)
    handler = _served_handler(checkout, tmp_path)
    assert handler.capabilities["actions"]["session"], (
        "the fixture's server is not a local human's plane")

    _assert_the_neutral_port(handler._session_submissions(handler),
                             checkout, remote)
    assert isinstance(handler._session_pull_requests(handler),
                      session_pr.GhPullRequests)

    class _Hosted(handler):
        capabilities = {"actions": {"session": False, "gate": False}}
    assert _Hosted._session_submissions(_Hosted) is None


class _HostSubmissions:
    """A host's own `SubmissionPort`, which 12.4 lets a governed host
    contribute (no host does in release 2, R2Q3 (a)). Never asked to submit
    here: the binding is what is asserted."""

    def submit(self, branch: str) -> session_pr.Submission:  # pragma: no cover
        raise NotImplementedError(branch)


def test_an_injected_submission_factory_is_the_servers_binding(
        checkout: Path, tmp_path: Path) -> None:
    """12.4: `submission_factory` is the seam a host contributes its own
    `SubmissionPort` through, so what an injected factory builds is the
    binding. A factory that cannot build a port leaves none: absence, not an
    error, as it is for the pull-request port."""
    contributed = _HostSubmissions()
    assert isinstance(contributed, session_pr.SubmissionPort)
    handler = _served_handler(checkout, tmp_path,
                              submission_factory=lambda: contributed)
    assert handler._session_submissions(handler) is contributed

    def unbuildable() -> session_pr.SubmissionPort:
        raise RuntimeError("the host's port cannot be built")

    handler = _served_handler(checkout, tmp_path,
                              submission_factory=unbuildable)
    assert handler._session_submissions(handler) is None


def test_cli_unset_submission_port_binds_the_neutral_default(
        checkout: Path, tmp_path: Path) -> None:
    """12.4, the CLI's half, as F12.2's block asserts it: `_submission_port`
    with nothing injected is `LocalGitSubmissions` for the checkout it is
    given, and it pushes there. `_pull_request_port` keeps `GhPullRequests`
    (R2Q2 (a))."""
    remote = _bare_origin(checkout, tmp_path)
    _assert_the_neutral_port(cli._submission_port(checkout), checkout, remote)
    assert isinstance(cli._pull_request_port(checkout),
                      session_pr.GhPullRequests)
