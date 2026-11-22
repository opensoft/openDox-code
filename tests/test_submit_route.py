"""#1144 F12.2's five `tests/test_submit_route.py` nodes, and the rest of the
submit route's surface (plan 038 T015; 12.4a; openxFactory
`specs/038-.../contracts/cli-http-submit-land.md`).

F12.2 runs five nodes here BY NAME, so a missing one fails its command:

  * `test_submit_route_is_refused_off_loopback`
  * `test_submit_route_is_refused_without_a_resolved_actor`
  * `test_submit_route_is_refused_without_the_console_token`
  * `test_submit_route_is_refused_from_a_foreign_origin`
  * `test_submit_route_takes_no_repository_from_the_request`

"Each of the five route tests also asserts that the remote is unchanged, so a
refusal that pushed anyway fails" (F12.2's prose). Each sends a WELL-FORMED
request naming a branch that exists, so only the clause under test can be what
refused it, and each asserts the refusal's own code, so a refusal made by a
later clause instead fails the node.

Beside them: the success path and every named refusal past the gate; the
order of the gate, before any body byte is read; the contributed port under
`governed` (R2Q4 (a)); the `actions.submit` key's presence and value (ADV-14;
OQ-12-14), including the falsifier's node that a host profile replacing the
default sees no key; and the control in `web/views/branch-actions.js`, run in
node.

The suite's root conftest registers an EMPTY host profile for the whole
process, so a server built here with no fixture is a HOST's plane: it carries
no submit route and no key. `standalone_profile` puts openDox's own default
profile in place for one case, as `tests/test_console_token_delivery.py`
does, and restores the suite's afterwards.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

import route_extension
from opendox import serve, serve_branch_actions, session_pr
from test_submission_default import (  # noqa: F401 - fixtures, by name
    _git,
    _isolated_git,
    _tip,
    checkout,
    with_userinfo,
)

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src" / "opendox" / "web"
BRANCH_ACTIONS_JS = WEB / "views" / "branch-actions.js"
ROUTE = serve_branch_actions.ACTIONS_SESSION_SUBMIT_ROUTE
NODE = shutil.which("node")

#: A well-formed submit request for the fixture's session branch.
SESS_1 = json.dumps({"branch": "sess-1"}).encode()


@pytest.fixture
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


def _bare(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
    return path


def _heads(repository: Path) -> str:
    """Every branch `repository` holds, with its commit: "" for none."""
    return _git(repository, "for-each-ref", "refs/heads")


@pytest.fixture
def origin(checkout: Path, tmp_path: Path) -> Path:
    """A bare `origin` beside the checkout, F12.2's own layout, holding
    nothing yet."""
    remote = _bare(tmp_path / "remote")
    _git(checkout, "remote", "add", "origin", str(remote))
    return remote


@contextlib.contextmanager
def _serving(checkout: Path, tmp_path: Path, *, host: str = "127.0.0.1",
             actor: str | None = "tester", **injected) -> Iterator:
    """`serve.build_server` over `checkout`, serving. `tester` is one of the
    suite's declared principals, so a loopback plane is a local human's."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    httpd = serve.build_server(WEB, snapshot, checkout, host=host, port=0,
                               actor=actor, **injected)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


def _bound(httpd) -> type:
    """The handler class the server dispatches on."""
    return getattr(httpd.RequestHandlerClass, "func", httpd.RequestHandlerClass)


def _request(httpd, method: str, path: str, body: bytes | None = None, *,
             token: str | None = None, headers: dict | None = None,
             timeout: float = 30) -> tuple[int, object]:
    """One request over loopback: the status and the parsed JSON body."""
    connection = http.client.HTTPConnection(
        "127.0.0.1", httpd.server_address[1], timeout=timeout)
    try:
        sent = {"Content-Type": "application/json"} if body is not None else {}
        if token:
            sent[serve.CONSOLE_TOKEN_HEADER] = token
        sent.update(headers or {})
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        raw = response.read()
        return response.status, (json.loads(raw) if raw else None)
    finally:
        connection.close()


def _submit(httpd, body: bytes | None = SESS_1, **kwargs) -> tuple[int, object]:
    return _request(httpd, "POST", ROUTE, body, **kwargs)


def _capabilities(httpd) -> dict:
    status, caps = _request(httpd, "GET", serve.CAPABILITIES_ROUTE)
    assert status == 200, caps
    return caps


# --------------------------------------------------------------------------
# F12.2's five nodes: the gate's three clauses, in order, and no repository
# from the request. Each sends a well-formed request; each asserts the
# remote unchanged.
# --------------------------------------------------------------------------

def test_submit_route_is_refused_off_loopback(
        checkout: Path, origin: Path, tmp_path: Path,
        standalone_profile) -> None:
    """Clause 1, the hosted plane's refusal, which is the ROUTE's own (ADV-04):
    a server bound off loopback refuses before anything else, by name."""
    with _serving(checkout, tmp_path, host="0.0.0.0") as httpd:
        assert not _bound(httpd).loopback
        status, body = _submit(httpd, token="any-token")
    assert (status, body["error"]) == (403, "loopback_only"), body
    assert body["message"] == serve_branch_actions.LOOPBACK_ONLY
    assert _heads(origin) == "", "a refused submit pushed anyway"


def test_submit_route_is_refused_without_a_resolved_actor(
        checkout: Path, origin: Path, tmp_path: Path,
        standalone_profile) -> None:
    """Clause 2: no git identity in the checkout and no `--actor`, so the
    plane resolves no human and grants no `session` capability."""
    with _serving(checkout, tmp_path, actor=None) as httpd:
        assert _bound(httpd).actor is None
        assert _capabilities(httpd)["actions"]["session"] is False
        status, body = _submit(httpd)
    assert (status, body["error"]) == (403, "action_unavailable"), body
    assert body["message"] == serve_branch_actions.UNAVAILABLE
    assert _heads(origin) == "", "a refused submit pushed anyway"


@pytest.mark.parametrize("token", [None, "x" * 43], ids=["absent", "wrong"])
def test_submit_route_is_refused_without_the_console_token(
        checkout: Path, origin: Path, tmp_path: Path, standalone_profile,
        token) -> None:
    """Clause 3: a local human's plane, a JSON body naming a real branch, and
    no console token, or one that is not this serve's."""
    with _serving(checkout, tmp_path) as httpd:
        assert httpd.console_token, "the plane minted no token"
        status, body = _submit(httpd, token=token)
    assert (status, body["error"]) == (403, "agent_invocation"), body
    assert httpd.console_token not in json.dumps(body)
    assert _heads(origin) == "", "a refused submit pushed anyway"


@pytest.mark.parametrize("header", ["Origin", "Referer"])
def test_submit_route_is_refused_from_a_foreign_origin(
        checkout: Path, origin: Path, tmp_path: Path, standalone_profile,
        header: str) -> None:
    """Clause 3 again, holding the RIGHT token: a page on another origin that
    somehow carried it still cannot drive the act."""
    with _serving(checkout, tmp_path) as httpd:
        status, body = _submit(httpd, token=httpd.console_token,
                               headers={header: "https://evil.example/x"})
    assert (status, body["error"]) == (403, "agent_invocation"), body
    assert _heads(origin) == "", "a refused submit pushed anyway"


@pytest.mark.parametrize("field", ["repo_root", "repository", "checkout_root"])
def test_submit_route_takes_no_repository_from_the_request(
        checkout: Path, origin: Path, tmp_path: Path, standalone_profile,
        field: str) -> None:
    """12.4a: the route submits a branch of the checkout the server was
    started on. A request that names another checkout, under any key, is
    refused whole, and neither that checkout's remote nor the served one's
    receives anything."""
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
    _git(other, "commit", "-q", "--allow-empty", "-m", "seed")
    _git(other, "branch", "sess-1")
    other_remote = _bare(tmp_path / "other-remote")
    _git(other, "remote", "add", "origin", str(other_remote))
    request = json.dumps({"branch": "sess-1", field: str(other)}).encode()
    with _serving(checkout, tmp_path) as httpd:
        status, body = _submit(httpd, request, token=httpd.console_token)
    assert (status, body["error"]) == (400, "invalid_body"), body
    assert body["message"] == serve_branch_actions.ONLY_THE_BRANCH
    assert str(other) not in json.dumps(body)
    assert _heads(origin) == "", "the served checkout's remote changed"
    assert _heads(other_remote) == "", "the named checkout was pushed"


# --------------------------------------------------------------------------
# The gate refuses before any body byte is read (12.4a; FR-004).
# --------------------------------------------------------------------------

def _refused_with_the_body_unsent(httpd, token: str | None) -> tuple[int, dict]:
    """POST with `Content-Length: 64` and NO body sent. A handler that read
    the body before refusing would wait on it (until its own 30-second
    timeout); the refusal must come at once, so the client waits 5."""
    with socket.create_connection(("127.0.0.1", httpd.server_address[1]),
                                  timeout=5) as sock:
        lines = [f"POST {ROUTE} HTTP/1.1",
                 f"Host: 127.0.0.1:{httpd.server_address[1]}",
                 "Content-Type: application/json", "Content-Length: 64"]
        if token:
            lines.append(f"{serve.CONSOLE_TOKEN_HEADER}: {token}")
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        response = http.client.HTTPResponse(sock)
        response.begin()
        return response.status, json.loads(response.read())


@pytest.mark.parametrize("clause", ["off-loopback", "no-actor", "no-token"])
def test_each_refusal_is_made_before_the_body_is_read(
        checkout: Path, origin: Path, tmp_path: Path, standalone_profile,
        clause: str) -> None:
    expected = {"off-loopback": "loopback_only",
                "no-actor": "action_unavailable",
                "no-token": "agent_invocation"}[clause]
    kwargs = {"off-loopback": {"host": "0.0.0.0"},
              "no-actor": {"actor": None}, "no-token": {}}[clause]
    with _serving(checkout, tmp_path, **kwargs) as httpd:
        status, body = _refused_with_the_body_unsent(httpd, None)
    assert (status, body["error"]) == (403, expected), body
    assert _heads(origin) == ""


def test_a_plane_whose_actor_is_gone_refuses_whatever_its_capability_says(
        checkout: Path, origin: Path, tmp_path: Path,
        standalone_profile) -> None:
    """Clause 2 asks for BOTH the capability and the actor, as the governed
    gate does: a handler whose actor is unset refuses even where its
    capability verdict still reads `session` true."""
    with _serving(checkout, tmp_path) as httpd:
        bound = _bound(httpd)
        assert bound.capabilities["actions"]["session"] is True
        bound.actor = None
        status, body = _submit(httpd, token=httpd.console_token)
    assert (status, body["error"]) == (403, "action_unavailable"), body
    assert _heads(origin) == ""


def test_a_plane_whose_verdict_says_no_session_refuses_whatever_its_actor(
        checkout: Path, origin: Path, tmp_path: Path,
        standalone_profile) -> None:
    """...and the converse: a handler that still holds an actor and a token,
    but whose capability verdict reads `session` false, refuses at clause 2,
    by that clause's own sentence, and never reaches the port."""
    with _serving(checkout, tmp_path) as httpd:
        bound = _bound(httpd)
        assert bound.actor
        assert httpd.console_token
        bound.capabilities = {**bound.capabilities, "actions": {
            **bound.capabilities["actions"], "session": False}}
        status, body = _submit(httpd, token=httpd.console_token)
    assert (status, body) == (403, {"ok": False, "error": "action_unavailable",
                                    "message": serve_branch_actions.UNAVAILABLE})
    assert _heads(origin) == ""


# --------------------------------------------------------------------------
# Past the gate: the act, and its named refusals.
# --------------------------------------------------------------------------

def test_submit_route_pushes_the_served_branch_and_answers_where_it_went(
        checkout: Path, origin: Path, tmp_path: Path,
        standalone_profile) -> None:
    """12.4a with 12.1a: the branch arrives at the served checkout's remote,
    and the answer is the `Submission` object, its five fields and no other."""
    with _serving(checkout, tmp_path) as httpd:
        status, body = _submit(httpd, token=httpd.console_token)
    assert status == 200, body
    tip = _tip(checkout, "sess-1")
    assert _tip(origin, "sess-1") == tip, "the branch did not arrive"
    assert body == {"remote": "origin", "ref": "refs/heads/sess-1",
                    "url": str(origin), "branch": "sess-1", "commit": tip}


def test_submit_route_refuses_the_default_branch(
        checkout: Path, origin: Path, tmp_path: Path,
        standalone_profile) -> None:
    """R2Q5 (a): `main` is refused by name, and nothing is pushed."""
    request = json.dumps({"branch": "main"}).encode()
    with _serving(checkout, tmp_path) as httpd:
        status, body = _submit(httpd, request, token=httpd.console_token)
    assert (status, body["error"]) == (409, "submission_refused"), body
    assert "`main` is the default branch" in body["message"]
    assert _heads(origin) == ""


def test_submit_route_refuses_a_checkout_with_no_remote_naming_it(
        checkout: Path, tmp_path: Path, standalone_profile) -> None:
    """12.3: no remote attached is `NoSubmissionTarget`, by its own name."""
    with _serving(checkout, tmp_path) as httpd:
        status, body = _submit(httpd, token=httpd.console_token)
    assert (status, body["error"]) == (409, "no_submission_target"), body
    assert "no remote is attached" in body["message"]


@pytest.mark.parametrize("raw, message", [
    (b"[1, 2]", serve_branch_actions.NOT_AN_OBJECT),
    (b"not json", serve_branch_actions.NOT_AN_OBJECT),
    (b"{}", serve_branch_actions.NO_BRANCH),
    (json.dumps({"branch": ""}).encode(), serve_branch_actions.NO_BRANCH),
    (json.dumps({"branch": 7}).encode(), serve_branch_actions.NO_BRANCH),
    (json.dumps({"ref": "sess-1"}).encode(),
     serve_branch_actions.ONLY_THE_BRANCH),
], ids=["array", "not-json", "empty", "blank-branch", "number-branch",
        "other-key"])
def test_a_malformed_submit_request_is_refused_and_pushes_nothing(
        checkout: Path, origin: Path, tmp_path: Path, standalone_profile,
        raw: bytes, message: str) -> None:
    with _serving(checkout, tmp_path) as httpd:
        status, body = _submit(httpd, raw, token=httpd.console_token)
    assert (status, body) == (400, {"ok": False, "error": "invalid_body",
                                    "message": message})
    assert _heads(origin) == ""


@pytest.mark.parametrize("body, expected", [
    ({"branch": "sess-1"}, ("sess-1", None)),
    ({"branch": "sess-1", "x": 1}, (None, serve_branch_actions.ONLY_THE_BRANCH)),
    ({"x": 1}, (None, serve_branch_actions.ONLY_THE_BRANCH)),
    ({}, (None, serve_branch_actions.NO_BRANCH)),
    ({"branch": None}, (None, serve_branch_actions.NO_BRANCH)),
    (None, (None, serve_branch_actions.NOT_AN_OBJECT)),
    ("sess-1", (None, serve_branch_actions.NOT_AN_OBJECT)),
])
def test_requested_branch_reads_one_key_and_nothing_else(body, expected) -> None:
    assert serve_branch_actions.requested_branch(body) == expected


# --------------------------------------------------------------------------
# A contributed port (R2Q4 (a)): the act goes through it and reports where
# the work went.
# --------------------------------------------------------------------------

class _ContributedPort:
    """A governed host's own `SubmissionPort`, which reports a destination of
    its own and pushes nothing here."""

    def __init__(self, answer=None, raises: BaseException | None = None):
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


def test_a_contributed_port_is_what_the_route_submits_through(
        checkout: Path, origin: Path, tmp_path: Path,
        standalone_profile) -> None:
    port = _ContributedPort()
    with _serving(checkout, tmp_path, submission_factory=lambda: port) as httpd:
        status, body = _submit(httpd, token=httpd.console_token)
    assert status == 200, body
    assert port.asked == ["sess-1"]
    assert body["url"] == "https://forge.example/team/repo"
    assert body["remote"] == "review"
    assert _heads(origin) == "", "the neutral default pushed beside the host's"


def test_the_default_branch_never_reaches_a_contributed_port(
        checkout: Path, tmp_path: Path, standalone_profile) -> None:
    """The act refuses `main` BEFORE the port is asked, so a host's port that
    would take it is never handed it."""
    port = _ContributedPort()
    request = json.dumps({"branch": "main"}).encode()
    with _serving(checkout, tmp_path, submission_factory=lambda: port) as httpd:
        status, body = _submit(httpd, request, token=httpd.console_token)
    assert (status, body["error"]) == (409, "submission_refused"), body
    assert port.asked == []


def test_a_port_that_cannot_be_built_is_named_and_pushes_nothing(
        checkout: Path, origin: Path, tmp_path: Path,
        standalone_profile) -> None:
    def unbuildable():
        raise RuntimeError("the host's port cannot be built")

    with _serving(checkout, tmp_path, submission_factory=unbuildable) as httpd:
        status, body = _submit(httpd, token=httpd.console_token)
    assert (status, body) == (403, {"ok": False, "error": "action_unavailable",
                                    "message": serve_branch_actions.NO_PORT})
    assert _heads(origin) == ""


def test_a_report_that_names_no_destination_is_refused(
        checkout: Path, tmp_path: Path, standalone_profile) -> None:
    port = _ContributedPort(answer=object())
    with _serving(checkout, tmp_path, submission_factory=lambda: port) as httpd:
        status, body = _submit(httpd, token=httpd.console_token)
    assert (status, body["error"]) == (409, "submission_refused"), body
    assert "no `remote`" in body["message"]


def test_a_port_failure_it_did_not_name_is_reported_without_its_text(
        checkout: Path, tmp_path: Path, standalone_profile,
        capsys: pytest.CaptureFixture) -> None:
    """A host's port that raises something other than a `SubmissionError`:
    a fixed answer, and only the exception's TYPE reaches the server log,
    since its text is not this route's to vet (12.1a)."""
    secret = "S3CRET-from-a-host-port"
    port = _ContributedPort(raises=RuntimeError(secret))
    with _serving(checkout, tmp_path, submission_factory=lambda: port) as httpd:
        status, body = _submit(httpd, token=httpd.console_token)
    assert (status, body) == (500, {"ok": False, "error": "submission_failed",
                                    "message": serve_branch_actions.FAILED})
    logged = capsys.readouterr().err
    assert "raised RuntimeError" in logged
    assert secret not in logged
    assert secret not in json.dumps(body)



HOST_PORT_SECRET = "S3CRET-from-a-host-port"
#: Credential-shaped URLs ASSEMBLED, never spelled whole in this tree's source.
HOST_PORT_URL = with_userinfo(
    "https", f"alice:{HOST_PORT_SECRET}",
    f"forge.example/team/repo?token={HOST_PORT_SECRET}")
#: A host port's refusal, in each shape lane 3 measured leaking at `2d64f42e`.
REFUSAL_SHAPES = {
    "token-as-username": with_userinfo(
        "https", HOST_PORT_SECRET, "forge.example/team/repo.git"),
    "unknown-query-name": ("https://forge.example/team/repo.git?ticket="
                           + HOST_PORT_SECRET),
    "fragment": "https://forge.example/team/repo.git#" + HOST_PORT_SECRET,
}


def test_a_contributed_report_is_answered_redacted(
        checkout: Path, tmp_path: Path, standalone_profile) -> None:
    """Copilot on #96 at `7dc8214b`: the route answers a host port's report
    with `url` and `remote` redacted, as the verb prints it (12.1a)."""
    port = _ContributedPort(answer=session_pr.Submission(
        remote=with_userinfo("https", HOST_PORT_SECRET, "forge.example/team/repo"),
        ref="refs/heads/sess-1", url=HOST_PORT_URL, branch="sess-1",
        commit="c" * 40))
    with _serving(checkout, tmp_path, submission_factory=lambda: port) as httpd:
        status, body = _submit(httpd, token=httpd.console_token)
    assert status == 200, body
    assert HOST_PORT_SECRET not in json.dumps(body)
    assert "forge.example/team/repo" in body["url"]
    assert "forge.example/team/repo" in body["remote"]


@pytest.mark.parametrize(("refusal", "error"), [
    (session_pr.SubmissionRefused, "submission_refused"),
    (session_pr.NoSubmissionTarget, "no_submission_target"),
])
@pytest.mark.parametrize("shape", sorted(REFUSAL_SHAPES))
def test_a_contributed_refusal_is_answered_redacted(
        checkout: Path, tmp_path: Path, standalone_profile, refusal,
        error: str, shape: str) -> None:
    """Lane 3's MAJOR on R1-T015 at `2d64f42e`, and Copilot's thread there: a
    host port's refusal naming a URL that carries a secret, in each shape, is
    answered on both 409 arms with the secret gone, the host kept and the
    refusal's own words intact."""
    port = _ContributedPort(raises=refusal(
        f"push to {REFUSAL_SHAPES[shape]} was rejected by the host"))
    with _serving(checkout, tmp_path, submission_factory=lambda: port) as httpd:
        status, body = _submit(httpd, token=httpd.console_token)
    assert (status, body["error"]) == (409, error), body
    assert HOST_PORT_SECRET not in body["message"]
    assert body["message"].startswith("push to https://")
    assert "forge.example/team/repo.git" in body["message"]
    assert body["message"].endswith(" was rejected by the host")


def test_a_report_that_is_not_the_submissions_is_refused_by_the_route(
        checkout: Path, tmp_path: Path, standalone_profile) -> None:
    """Lane 3's MINOR at `2d64f42e`: a report naming another branch is refused
    with a fixed sentence (409 `submission_refused`), never answered."""
    port = _ContributedPort(answer=session_pr.Submission(
        remote="review", ref="refs/heads/sess-2", url="https://forge.example/r",
        branch="sess-2", commit="c" * 40))
    with _serving(checkout, tmp_path, submission_factory=lambda: port) as httpd:
        status, body = _submit(httpd, token=httpd.console_token)
    assert (status, body["error"]) == (409, "submission_refused"), body
    assert "is not the submission's" in body["message"]
    assert "sess-2" not in body["message"]


# --------------------------------------------------------------------------
# `actions.submit`: PRESENT only under openDox's own profile, its VALUE from
# the route bindings (ADV-14; OQ-12-14; contracts § /capabilities).
# --------------------------------------------------------------------------

def test_a_host_profile_replacing_the_default_sees_no_submit_key(
        checkout: Path, origin: Path, tmp_path: Path) -> None:
    """The falsifier's node (R2Q3 (a)): this suite's own registered host
    profile replaces the default, so its plane carries no `actions.submit`
    key, no submit route and no submit handler, and its action keys are core
    `_DEFAULT_CAPABILITIES`' own."""
    from opendox import default_profile, domain_profile

    assert domain_profile.current() is not default_profile
    with _serving(checkout, tmp_path) as httpd:
        caps = _capabilities(httpd)
        assert caps["actions"]["session"] is True, "not a local human's plane"
        status, body = _submit(httpd, token=httpd.console_token)
        assert not hasattr(_bound(httpd), "_handle_session_submit")
    assert "submit" not in caps["actions"], caps["actions"]
    assert set(caps["actions"]) == set(serve._DEFAULT_CAPABILITIES["actions"])
    assert (status, body["error"]) == (404, "unknown_action"), body
    assert _heads(origin) == ""


def test_the_standalone_plane_offers_submit_to_its_local_human(
        checkout: Path, tmp_path: Path, standalone_profile) -> None:
    with _serving(checkout, tmp_path) as httpd:
        caps = _capabilities(httpd)
        assert _bound(httpd)._handle_session_submit is (
            serve_branch_actions.BranchActionRoutes._handle_session_submit)
    assert caps["actions"]["submit"] is True, caps["actions"]


@pytest.mark.parametrize("plane", ["hosted", "no-actor"])
def test_the_key_is_present_and_false_where_the_route_cannot_act(
        checkout: Path, tmp_path: Path, standalone_profile, plane: str) -> None:
    kwargs = {"hosted": {"host": "0.0.0.0"}, "no-actor": {"actor": None}}[plane]
    with _serving(checkout, tmp_path, **kwargs) as httpd:
        caps = _capabilities(httpd)
    assert caps["actions"]["submit"] is False, caps["actions"]


def test_core_default_capabilities_gain_nothing() -> None:
    """`_DEFAULT_CAPABILITIES` (which always carries `gate`) carries no
    `submit`: the key is the default profile's contribution, never core's."""
    assert "submit" not in serve._DEFAULT_CAPABILITIES["actions"]


_SUBMIT = route_extension.RouteBinding("POST", ROUTE, False,
                                       "_handle_session_submit")


@pytest.mark.parametrize("binding, answers", [
    (_SUBMIT, True),
    (route_extension.RouteBinding("POST", "/actions/session/", True, "h"), True),
    (route_extension.RouteBinding("GET", ROUTE, False, "h"), False),
    (route_extension.RouteBinding("POST", ROUTE + "x", False, "h"), False),
    (route_extension.RouteBinding("POST", "/actions/refresh", False, "h"), False),
])
def test_what_answers_the_submit(binding, answers: bool) -> None:
    assert serve.answers_the_submit(binding) is answers


def test_compute_capabilities_derives_the_key_from_the_bindings() -> None:
    """No submit binding, no key; with one, the value is the local human's
    verdict, so the key is never true where the route would refuse."""
    base = dict(nlm_present=False, checkout_real=True, loopback=True)
    other = route_extension.RouteBinding("POST", "/actions/refresh", False, "h")
    assert "submit" not in serve.compute_capabilities(
        actor="a", **base)["actions"]
    assert "submit" not in serve.compute_capabilities(
        actor="a", route_bindings=(other,), **base)["actions"]
    on = serve.compute_capabilities(actor="a", route_bindings=(_SUBMIT,), **base)
    assert on["actions"]["submit"] is True
    for actor, loopback, real in ((None, True, True), ("a", False, True),
                                  ("a", True, False)):
        off = serve.compute_capabilities(
            nlm_present=False, checkout_real=real, loopback=loopback,
            actor=actor, route_bindings=(_SUBMIT,))
        assert off["actions"]["submit"] is False, (actor, loopback, real)


def test_the_default_profile_contributes_the_route_and_its_mixin() -> None:
    """N-2 refined by ADV-14: the route through `ROUTE_EXTENSIONS`, its
    method through `HANDLER_CONTRIBUTIONS`."""
    from opendox import default_profile

    bindings = route_extension.collect_bindings(default_profile.ROUTE_EXTENSIONS)
    # T016 adds the two land routes beside it (#1144 12.6a; OQ-12-13)
    assert bindings[0] == _SUBMIT
    assert [b.pattern for b in bindings[1:]] == [
        serve_branch_actions.ACTIONS_SESSION_LAND_NONCE_ROUTE,
        serve_branch_actions.ACTIONS_SESSION_LAND_ROUTE]
    assert route_extension.declared_handler_contributions(default_profile) == (
        serve_branch_actions.BranchActionRoutes,)


# --------------------------------------------------------------------------
# The control (`web/views/branch-actions.js`), run in node against the module
# itself, with the DOM stood in.
# --------------------------------------------------------------------------

_HARNESS = r"""
const out = {};
function node(tag) {
  const n = { tag, children: [], attrs: {}, listeners: {}, textContent: "",
              value: "", disabled: false, className: "", type: "",
              placeholder: "",
              setAttribute(k, v) { this.attrs[k] = v; },
              addEventListener(k, f) { this.listeners[k] = f; },
              append(...c) { this.children.push(...c); } };
  return n;
}
const doc = { createElement: node };
function host() { const h = node("span"); h.ownerDocument = doc; return h; }
const m = await import("./branch-actions.js");
const TOKEN = "Tk_" + "a".repeat(40);
const SERVED = "served-repo";
const live = { actions: { submit: true, session: true }, console_token: TOKEN,
               repository: SERVED };
const calls = [];
const answering = (status, payload) => async (url, options) => {
  calls.push({ url, options });
  return { ok: status < 400, status, json: async () => payload };
};

out.capable = {
  live: m.submitCapable(live),
  noKey: m.submitCapable({ actions: { session: true }, console_token: TOKEN }),
  falseKey: m.submitCapable({ actions: { submit: false }, console_token: TOKEN }),
  truthy: m.submitCapable({ actions: { submit: 1 }, console_token: TOKEN }),
  noToken: m.submitCapable({ actions: { submit: true } }),
  emptyToken: m.submitCapable({ actions: { submit: true }, console_token: "" }),
  nothing: m.submitCapable(undefined),
};
out.proposed = [m.proposedBranch("sess-1"), m.proposedBranch("main"),
                m.proposedBranch(""), m.proposedBranch(undefined)];
out.another = {
  served: m.anotherRepositoryIsActive(live, SERVED),
  other: m.anotherRepositoryIsActive(live, "other-repo"),
  noActive: m.anotherRepositoryIsActive(live, null),
  emptyActive: m.anotherRepositoryIsActive(live, ""),
  undeclared: m.anotherRepositoryIsActive({ ...live, repository: undefined }, SERVED),
  nothingDeclaredNoneActive: m.anotherRepositoryIsActive(undefined, null),
  nothingDeclared: m.anotherRepositoryIsActive(undefined, SERVED),
};

let h = host();
h.textContent = "stale";
let c = m.mountBranchActions(h, { caps: { actions: { session: true },
                                          console_token: TOKEN } });
out.unoffered = { enabled: c.enabled, children: h.children.length,
                  text: h.textContent, submitted: await c.submit() };
h = host();
c = m.mountBranchActions(h, { caps: live, branch: "sess-1", repository: SERVED,
                              composed: true });
out.composed = { enabled: c.enabled, children: h.children.length };
h = host();
c = m.mountBranchActions(h, { caps: live, branch: "sess-1",
                              repository: "other-repo" });
out.otherRepository = { enabled: c.enabled, children: h.children.length };
h = host();
c = m.mountBranchActions(h, { caps: { ...live, repository: undefined },
                              branch: "sess-1", repository: SERVED });
out.undeclared = { enabled: c.enabled, children: h.children.length };
h = host();
c = m.mountBranchActions(h, { caps: live, branch: null, repository: null });
out.noneActive = { enabled: c.enabled, children: h.children.length };

h = host();
c = m.mountBranchActions(h, { caps: live, branch: "sess-1", repository: SERVED,
  fetcher: answering(200, { remote: "origin", ref: "refs/heads/sess-1",
                            url: "/srv/remote", branch: "sess-1",
                            commit: "0123456789abcdef0123" }) });
const [input, button, message] = h.children;
out.mounted = { enabled: c.enabled, count: h.children.length,
                value: input.value, label: button.textContent,
                role: message.attrs.role, click: typeof button.listeners.click };
out.submitted = await c.submit();
out.request = { url: calls[0].url, method: calls[0].options.method,
                headers: calls[0].options.headers,
                body: JSON.parse(calls[0].options.body) };
out.afterSuccess = { disabled: button.disabled, cls: message.className };

h = host();
c = m.mountBranchActions(h, { caps: live, branch: "main", repository: SERVED,
                              fetcher: answering(200, {}) });
out.mainValue = h.children[0].value;
calls.length = 0;
out.mainRefused = await c.submit();
h.children[0].value = "main";
out.mainTyped = await c.submit();
out.mainCalls = calls.length;

h = host();
c = m.mountBranchActions(h, { caps: live, branch: "sess-2", repository: SERVED,
  fetcher: answering(409, { ok: false, error: "no_submission_target",
                            message: "no remote is attached" }) });
out.refused = await c.submit();
out.refusedCls = h.children[2].className;

h = host();
c = m.mountBranchActions(h, { caps: live, branch: "sess-3", repository: SERVED,
  fetcher: async () => { throw new Error("offline"); } });
out.thrown = await c.submit();
out.thrownEnabled = !h.children[1].disabled;

out.describe = [
  m.describeAnswer({ ok: false, status: 500, payload: null }),
  m.describeAnswer({ ok: false, status: 403, payload: { error: "loopback_only" } }),
];
out.route = m.ACTIONS_SESSION_SUBMIT_ROUTE;
out.nullHost = (await m.mountBranchActions(null, { caps: live }).submit());
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def control(tmp_path_factory):
    if NODE is None:
        pytest.skip("node not available for the submit control's probe")
    root = tmp_path_factory.mktemp("branch-actions")
    shutil.copy(BRANCH_ACTIONS_JS, root / "branch-actions.js")
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    harness = root / "harness.mjs"
    harness.write_text(_HARNESS, encoding="utf-8")
    done = subprocess.run([NODE, str(harness)], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_control_is_keyed_on_submit_and_the_token(control) -> None:
    """OQ-12-14 refined by ADV-14: `actions.submit` exactly true, never
    `session`, and a console token to send."""
    assert control["capable"] == {"live": True, "noKey": False,
                                  "falseKey": False, "truthy": False,
                                  "noToken": False, "emptyToken": False,
                                  "nothing": False}
    assert control["unoffered"] == {"enabled": False, "children": 0,
                                    "text": "", "submitted": None}
    assert control["nullHost"] is None
    # D10: a composed render is read-only, so no acting control is offered
    assert control["composed"] == {"enabled": False, "children": 0}


def test_the_control_is_withheld_only_while_another_repository_is_active(
        control) -> None:
    """The route submits from the SERVED checkout alone and takes no
    repository from the request (12.4a). With another repository active the
    control would offer that repository's branch name, and the push would go
    out from the served one (Copilot's finding on #96 at `39a73a33`), so it
    is withheld then, and where an active key meets a plane that declares no
    repository. With NO repository active it is offered: a standalone plane
    has no snapshot index, so nothing is ever active there (lane 3's MAJOR on
    R1-T015 at `63a12ad4`)."""
    assert control["another"] == {"served": False, "other": True,
                                  "noActive": False, "emptyActive": False,
                                  "undeclared": True,
                                  "nothingDeclaredNoneActive": False,
                                  "nothingDeclared": True}
    assert control["otherRepository"] == {"enabled": False, "children": 0}
    assert control["undeclared"] == {"enabled": False, "children": 0}
    assert control["noneActive"] == {"enabled": True, "children": 3}


def test_the_control_posts_the_branch_and_shows_where_it_went(control) -> None:
    assert control["route"] == ROUTE
    assert control["mounted"] == {"enabled": True, "count": 3,
                                  "value": "sess-1", "label": "submit",
                                  "role": "status", "click": "function"}
    request = control["request"]
    assert (request["url"], request["method"]) == (ROUTE, "POST")
    assert request["body"] == {"branch": "sess-1"}
    assert request["headers"] == {"Content-Type": "application/json",
                                  serve.CONSOLE_TOKEN_HEADER: "Tk_" + "a" * 40}
    assert control["submitted"] == (
        "submitted sess-1 to origin (/srv/remote) as refs/heads/sess-1 at "
        "0123456789ab")
    assert control["afterSuccess"] == {"disabled": False, "cls": ""}


def test_the_control_never_offers_or_sends_the_default_branch(control) -> None:
    assert control["proposed"] == ["sess-1", "", "", ""]
    assert control["mainValue"] == ""
    assert control["mainRefused"] == "name a branch other than main"
    assert control["mainTyped"] == "name a branch other than main"
    assert control["mainCalls"] == 0


def test_the_control_states_a_refusal_in_the_servers_words(control) -> None:
    assert control["refused"] == "not submitted: no remote is attached"
    assert control["refusedCls"] == "repopick-msg"
    assert control["thrown"] == "not submitted: offline"
    assert control["thrownEnabled"] is True
    assert control["describe"] == ["not submitted: HTTP 500",
                                   "not submitted: loopback_only"]



# --------------------------------------------------------------------------
# The control on a REAL standalone plane, its arguments derived as the page
# derives them (lane 3's MAJOR on R1-T015 at `63a12ad4`).
# --------------------------------------------------------------------------

_DERIVE = r"""
const [BASE, TOKEN] = process.argv.slice(2);
// The page as the standalone entry point opens it: the console token in the
// URL's fragment (`console_access.publish`), never on `/capabilities`.
globalThis.location = { hash: "#console_token=" + TOKEN,
                        pathname: "/index.html", search: "" };
globalThis.history = { state: null, replaceState() {} };
const served = (path, options) => fetch(new URL(path, BASE + "/"), options);
const { probeCapabilities } = await import("./views/notebook.js");
const { fetchIndex } = await import("./views/repo-selector.js");
const { resolveActive, resolveStoredKey, safeKey } =
  await import("./views/repo-selector-model.js");
const { isComposed } = await import("./views/composed-model.js");
const { mountBranchActions } = await import("./views/branch-actions.js");
function node(tag) {
  return { tag, children: [], attrs: {}, listeners: {}, textContent: "",
           value: "", disabled: false, className: "", type: "", placeholder: "",
           setAttribute(k, v) { this.attrs[k] = v; },
           addEventListener(k, f) { this.listeners[k] = f; },
           append(...c) { this.children.push(...c); } };
}
const host = node("span");
host.ownerDocument = { createElement: node };
// `render()` in app.js, in its order: the index, the active key (nothing is
// stored on a freshly opened page), the snapshot and whether it is composed,
// then the mount with exactly app.js's arguments.
const caps = await probeCapabilities(served);
const index = await fetchIndex(served);
const active = resolveActive(index, resolveStoredKey(index, null));
const snapshot = await (await served("./snapshot.json", { cache: "no-store" })).json();
const composed = isComposed(snapshot);
const control = mountBranchActions(host, {
  caps, composed, branch: safeKey(active)?.ref || null,
  repository: safeKey(active)?.repository || null,
});
process.stdout.write(JSON.stringify({
  submit: caps?.actions?.submit ?? null, repository: caps?.repository ?? null,
  tokenDelivered: caps?.console_token === TOKEN, index, active, composed,
  offered: control.enabled, children: host.children.length,
}));
"""


def test_a_standalone_plane_offers_the_control_as_the_page_derives_it(
        checkout: Path, tmp_path: Path, standalone_profile) -> None:
    """The one plane that carries `actions.submit` is a standalone one, and it
    has no snapshot index: `/snapshot-index.json` answers 404, so `fetchIndex`
    gives null, `resolveActive` gives no key, and the mount is handed no
    repository. The control must be OFFERED there. The bundle's own modules
    derive every argument against a real standalone serve, as app.js does,
    the console token included, which reaches the page in its URL's fragment.
    """
    if NODE is None:
        pytest.skip("node not available for the page's derivation")
    from opendox import console_access

    bundle = tmp_path / "bundle"
    shutil.copytree(WEB, bundle)
    (bundle / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    derive = bundle / "derive.mjs"
    derive.write_text(_DERIVE, encoding="utf-8")
    with _serving(checkout, tmp_path) as httpd:
        assert httpd.console_token_delivery == console_access.DELIVERY_OPENED_URL
        declared = _capabilities(httpd)
        assert "console_token" not in declared
        done = subprocess.run(
            [NODE, str(derive), f"http://127.0.0.1:{httpd.server_address[1]}",
             httpd.console_token],
            capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {
        "submit": True, "repository": declared["repository"],
        "tokenDelivered": True, "index": None, "active": None,
        "composed": False, "offered": True, "children": 3,
    }

# --------------------------------------------------------------------------
# The account menu names the verb `actions.submit` grants (Codex's P2 on #96;
# `views/account-menu.js` admitted for its one word by #656 `6069024568`).
# --------------------------------------------------------------------------

_ACCESS_PROBE = r"""
const am = await import("./account-menu.js");
process.stdout.write(JSON.stringify({
  standalone: am.accessLevel({ actions: { gate: true, edit: true,
                                          session: true, submit: true } }),
  offeredAlone: am.accessLevel({ actions: { submit: true } }),
  notGranted: am.accessLevel({ actions: { session: true, submit: false } }),
  hostPlane: am.accessLevel({ actions: { session: true } }),
}));
"""


def test_the_account_menu_names_submit_where_it_is_granted(tmp_path) -> None:
    """`submit` is a write-class verb of its own, split from `session`
    (OQ-12-14), so the menu's access line names it where `actions.submit` is
    true, and only there: a host's plane, which carries no key, reads as it
    did."""
    if NODE is None:
        pytest.skip("node not available for the account menu's probe")
    for name in ("account-menu.js", "helpers.js"):
        shutil.copy(WEB / "views" / name, tmp_path / name)
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    probe = tmp_path / "probe.mjs"
    probe.write_text(_ACCESS_PROBE, encoding="utf-8")
    done = subprocess.run([NODE, str(probe)], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {
        "standalone": "gate, edit, session, submit",
        "offeredAlone": "submit",
        "notGranted": "session",
        "hostPlane": "session",
    }
