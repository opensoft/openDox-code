"""Capability honesty: a flag in `/capabilities`' `actions` map whose affordance
is a route this server serves is true only where such a route answers (plan 034
T084; #1144 4.3 as T007 batch L's addendum reads, RULED openxFactory#656
`5920216845`, item 1, *"Fix in T084 + #1144 note (Recommended)"*).

MEASURED AT openDox-code `047bb4fa`: a standalone `/capabilities` answered
`actions.gate` and `actions.refresh` true, while every `POST /actions/gate/<verb>`
and `POST /actions/refresh` answered `404 unknown_action`. The gate flag
followed the checkout's git identity alone (`compute_capabilities`). Both routes
are a HOST's: a gate verb and the refresh arrive only through the route bindings
the assembly collects, so each flag is now true only when those bindings carry a
route it governs. `notebook`, `edit` and `session` govern core routes and keep
their conditions, and `intent` governs another plane's API, so its condition
stands too.

The cases:

1. A STANDALONE SERVER, `python -m opendox.serve` as a child with neither
   sibling importable (`tests/standalone_child.py`), over a fresh repository:
   `gate` and `refresh` read false, and the two routes they would govern answer
   `unknown_action`, which is why. It is run WITH a git identity, so an actor
   resolves and the false `gate` is the routes' doing and not a missing actor's,
   and without one. The child's environment carries no `GIT_*` and no `XF_*`:
   the suite itself declares a roster of several principals
   (`session_fixtures.declared_gate_principals`), and a roster of several names
   with no claim resolves no actor at all.
2. COMPOSED HOSTS whose other conditions hold (a loopback bind, a real checkout,
   an authenticated actor), built in process with contributed bindings and the
   mixins that answer them, through the handler-contribution facet: a host that
   contributes both routes reads both true; a gate-only host and a refresh-only
   host each read only the flag whose route it contributes.
3. ON EVERY SERVER ABOVE, for every `actions` key that reads TRUE, a route it
   governs does not answer `unknown_action`. So a plane that switched every flag
   off would fail the cases that require a flag true, and a plane that left one
   on with no route behind it fails here. `intent` governs no route of this
   server, and every key of the map must be accounted for in `GOVERNED`.
4. The two predicates, case by case.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import http.client
import json
import os
import re
import threading
from pathlib import Path

import pytest

from route_extension import RouteBinding
from standalone_child import Child, fresh_repository, git, run_module

ROOT = Path(__file__).resolve().parent.parent
PLAIN = ROOT / "tests" / "fixtures" / "plain-documents"
WEB = ROOT / "src" / "opendox" / "web"

#: For each key of the `actions` map, the route it governs on THIS server, as
#: `(method, path)`, or None where it governs no route this server serves.
GOVERNED: dict[str, tuple[str, str] | None] = {
    "notebook": ("POST", "/actions/notebook"),
    "gate": ("POST", "/actions/gate/demote"),
    "refresh": ("POST", "/actions/refresh"),
    "session": ("POST", "/actions/workbench/chat-turn"),
    "edit": ("POST", "/actions/edit"),
    # a POST to ANOTHER plane's intent API, which that plane answers
    "intent": None,
    # openDox's own submit route (plan 038 T015; #1144 12.4a), contributed by
    # its default profile, so a host's map carries no such key
    "submit": ("POST", "/actions/session/submit"),
}

_SERVE_URL = re.compile(r"^serving ideation dashboard at "
                        r"(http://([0-9.]+):([0-9]+))/index\.html$")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _request(base: tuple[str, int], method: str, path: str) -> tuple[int, dict]:
    """One request; the status and the JSON body (`{}` where it is not JSON).
    A dropped connection raises, which is a failure of the case."""
    connection = http.client.HTTPConnection(*base, timeout=30)
    try:
        body = b"{}" if method == "POST" else None
        headers = {"Content-Type": "application/json"} if body else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError:
            parsed = {}
        return response.status, parsed if isinstance(parsed, dict) else {}
    finally:
        connection.close()


def _capabilities(base: tuple[str, int]) -> dict:
    status, caps = _request(base, "GET", "/capabilities")
    assert status == 200, status
    return caps


def _unknown(answer: tuple[int, dict]) -> bool:
    status, body = answer
    return status == 404 and body.get("error") == "unknown_action"


def _assert_every_true_flag_answers(base: tuple[str, int], caps: dict, *,
                                    default_profile: bool) -> None:
    """Case 3: every `actions` key is accounted for, and each that reads true
    has a route that answers something other than `unknown_action`."""
    actions = caps["actions"]
    # PROFILE-AWARE (plan 038 T015; holder ruling, #656 6028383410): `submit`
    # is openDox's default profile's own key, so the default's map carries
    # every key here and a composed host's carries every key but that one.
    expected = set(GOVERNED) if default_profile else set(GOVERNED) - {"submit"}
    assert set(actions) == expected, (
        f"the actions map has keys this test does not account for: "
        f"{sorted(set(actions) ^ expected)}")
    for key, value in actions.items():
        if value is not True or GOVERNED[key] is None:
            continue
        method, path = GOVERNED[key]
        answer = _request(base, method, path)
        assert not _unknown(answer), (
            f"actions.{key} reads true, but {method} {path} answers "
            f"unknown_action: {answer}")


def _clean_environment(monkeypatch) -> None:
    """No `GIT_*` and no `XF_*` reaches the child, and no user or system git
    configuration: its only identity is the one its repository carries."""
    for name in list(os.environ):
        if name.startswith(("GIT_", "XF_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def _repository(tmp_path: Path, *, identity: bool) -> Path:
    repo = fresh_repository(PLAIN, tmp_path)
    if identity:
        git(repo, "config", "user.name", "fixture")
        git(repo, "config", "user.email", "fixture@example.invalid")
    return repo


def _snapshot(tmp_path: Path, repo: Path) -> Path:
    out = tmp_path / "out" / "snapshot.json"
    child, status = run_module(
        tmp_path, "opendox.cli", "generate", "--repo-root", str(repo),
        "--repository", "fixture", "--output", str(out), "--no-validate")
    assert status == 0, child.stderr_text()
    return out


# ---------------------------------------------------------------------------
# 1 and 3 — a standalone server
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("identity", [True, False], ids=["identity", "no-identity"])
def test_a_standalone_server_offers_neither_gate_nor_refresh(
        tmp_path, monkeypatch, identity) -> None:
    """`python -m opendox.serve`, nothing registered by any host: `gate` and
    `refresh` read false, the routes they would govern answer
    `unknown_action`, and every flag that reads true answers."""
    _clean_environment(monkeypatch)
    repo = _repository(tmp_path, identity=identity)
    out = _snapshot(tmp_path, repo)
    child = Child(tmp_path, "opendox.serve", "--snapshot", str(out),
                  "--checkout-root", str(repo), "--port", "0")
    try:
        match = child.wait_for_line(_SERVE_URL)
        base = (match.group(2), int(match.group(3)))
        caps = _capabilities(base)
        actions = caps["actions"]
        # THE OTHER CONDITIONS, so the false `gate` is the routes' doing: with
        # an identity an actor resolves and the core write flags read true.
        assert caps["actor"] == ("fixture" if identity else None), caps
        assert actions["session"] is identity and actions["edit"] is identity
        # the plane would regenerate, and no route offers it
        assert caps["refresh"]["binding"] == "regenerate", caps
        assert actions["gate"] is False and actions["refresh"] is False, caps
        assert _unknown(_request(base, "POST", "/actions/gate/demote"))
        assert _unknown(_request(base, "POST", "/actions/refresh"))
        _assert_every_true_flag_answers(base, caps, default_profile=True)
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()
    assert child.refused() == [], child.refused()


# ---------------------------------------------------------------------------
# 2 and 3 — composed hosts
# ---------------------------------------------------------------------------

class _GateColumn:
    """A host's gate column: answers every verb under the gate prefix."""

    def _handle_honesty_gate(self, remainder):
        self._send_json(200, {"ok": True, "verb": remainder})


class _RefreshColumn:
    """A host's refresh: answers `POST /actions/refresh`."""

    def _handle_honesty_refresh(self):
        self._send_json(200, {"ok": True, "refreshed": True})


class _Contribution:
    """A route extension contributing `bindings` and the mixins answering them."""

    def __init__(self, bindings, mixins) -> None:
        self._bindings = tuple(bindings)
        self.HANDLER_CONTRIBUTIONS = tuple(mixins)

    def routes(self):
        return self._bindings


def _gate():
    from opendox import serve
    return (RouteBinding("POST", serve.ACTIONS_GATE_PREFIX, True,
                         "_handle_honesty_gate"), _GateColumn)


def _refresh():
    from opendox import serve
    return (RouteBinding("POST", serve.ACTIONS_REFRESH_ROUTE, False,
                         "_handle_honesty_refresh"), _RefreshColumn)


@pytest.fixture()
def composed(tmp_path):
    """`build(*contributions)`: a composed host over a REAL checkout, on a
    loopback bind, with an authenticated actor (`brett`, one of the suite's
    declared principals), served on a thread. Yields `(base, capabilities)`."""
    from opendox import serve

    repo = _repository(tmp_path, identity=True)
    out = _snapshot(tmp_path, repo)
    servers = []

    def build(*contributed):
        bindings = [binding for binding, _mixin in contributed]
        mixins = [mixin for _binding, mixin in contributed]
        httpd = serve.build_server(
            WEB, out, repo, port=0, actor="brett",
            route_extensions=(_Contribution(bindings, mixins),)
            if contributed else ())
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        servers.append((httpd, worker))
        base = httpd.server_address[:2]
        return base, _capabilities(base)

    try:
        yield build
    finally:
        for httpd, worker in servers:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=10)


def test_a_composed_host_contributing_both_routes_reads_both_true(composed) -> None:
    base, caps = composed(_gate(), _refresh())
    assert caps["actor"] == "brett", caps
    assert caps["actions"]["gate"] is True, caps
    assert caps["actions"]["refresh"] is True, caps
    assert caps["actions"]["session"] is True and caps["actions"]["edit"] is True
    _assert_every_true_flag_answers(base, caps, default_profile=False)


def test_a_gate_only_host_reads_only_gate_true(composed) -> None:
    base, caps = composed(_gate())
    assert caps["actions"]["gate"] is True, caps
    assert caps["actions"]["refresh"] is False, caps
    _assert_every_true_flag_answers(base, caps, default_profile=False)


def test_a_refresh_only_host_reads_only_refresh_true(composed) -> None:
    base, caps = composed(_refresh())
    assert caps["actions"]["refresh"] is True, caps
    assert caps["actions"]["gate"] is False, caps
    _assert_every_true_flag_answers(base, caps, default_profile=False)


def test_the_same_host_with_nothing_contributed_reads_both_false(composed) -> None:
    """The control: the same checkout, actor and bind, and no contribution."""
    base, caps = composed()
    assert caps["actor"] == "brett", caps
    assert caps["actions"]["gate"] is False and caps["actions"]["refresh"] is False
    assert caps["actions"]["session"] is True
    _assert_every_true_flag_answers(base, caps, default_profile=False)


# ---------------------------------------------------------------------------
# 4 — the two predicates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("binding,answers", [
    (RouteBinding("POST", "/actions/gate/", True, "h"), True),
    (RouteBinding("POST", "/actions/", True, "h"), True),
    (RouteBinding("POST", "/actions/gate/demote", False, "h"), True),
    (RouteBinding("POST", "/actions/gate/lens/", True, "h"), True),
    (RouteBinding("POST", "/actions/gate/", False, "h"), False),
    (RouteBinding("POST", "/actions/gatehouse/", True, "h"), False),
    (RouteBinding("GET", "/actions/gate/", True, "h"), False),
    (RouteBinding("POST", "/actions/refresh", False, "h"), False),
])
def test_what_answers_a_gate_verb(binding, answers) -> None:
    from opendox import serve
    assert serve.answers_a_gate_verb(binding) is answers


@pytest.mark.parametrize("binding,answers", [
    (RouteBinding("POST", "/actions/refresh", False, "h"), True),
    (RouteBinding("POST", "/actions/", True, "h"), True),
    (RouteBinding("GET", "/actions/refresh", False, "h"), False),
    (RouteBinding("POST", "/actions/refresh/", True, "h"), False),
    (RouteBinding("POST", "/actions/gate/", True, "h"), False),
])
def test_what_answers_the_refresh(binding, answers) -> None:
    from opendox import serve
    assert serve.answers_the_refresh(binding) is answers


def test_the_verdict_follows_the_bindings_and_keeps_the_other_conditions() -> None:
    """`compute_capabilities` directly: the routes are necessary, never
    sufficient, so an unresolved actor still keeps `gate` off."""
    from opendox import serve
    both = (_gate()[0], _refresh()[0])
    kwargs = dict(nlm_present=False, checkout_real=True, loopback=True,
                  refresh_binding="regenerate")
    assert serve.compute_capabilities(actor="a", **kwargs)["actions"]["gate"] is False
    on = serve.compute_capabilities(actor="a", route_bindings=both, **kwargs)
    assert on["actions"]["gate"] is True and on["actions"]["refresh"] is True
    off = serve.compute_capabilities(actor=None, route_bindings=both, **kwargs)
    assert off["actions"]["gate"] is False and off["actions"]["refresh"] is True
    unbound = serve.compute_capabilities(
        actor="a", route_bindings=both,
        **{**kwargs, "refresh_binding": None})
    assert unbound["actions"]["refresh"] is False


# ---------------------------------------------------------------------------
# 5 — the three sites that dropped a connection, and the chat turn
# ---------------------------------------------------------------------------

def _call(base: tuple[str, int], method: str, path: str, *,
          body: bytes | None = None, token: str | None = None
          ) -> tuple[int, dict, str]:
    """One request carrying `body` and, where given, the console token, from
    a same-origin JSON client. The status, the JSON body (`{}` where it is not
    JSON) and the raw text. A dropped connection RAISES (`RemoteDisconnected`,
    a reset), which fails the case: that is the failure this section exists
    to rule out."""
    from opendox import serve
    connection = http.client.HTTPConnection(*base, timeout=30)
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers[serve.CONSOLE_TOKEN_HEADER] = token
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError:
            parsed = {}
        return (response.status, parsed if isinstance(parsed, dict) else {},
                raw)
    finally:
        connection.close()


def _json(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


#: A scope no snapshot of the fixture's declares a document under: each
#: request below is refused, and none is served a document.
_SCOPE = {"repository": "fixture", "ref": "main", "tile_kind": "staged",
          "tile_id": "honesty-topic"}

#: A well-formed abstract request: the shape step 3 accepts.
_ABSTRACT = {"scope": _SCOPE, "subject_path": "notes/one.md",
             "model_id": "honesty-model"}


def _chat_turn() -> dict:
    """A well-formed v2 chat turn: the shape the body parser accepts, an
    outline and one document, bound to the document."""
    from opendox.serve_wire import DOXBENCH_CHAT_TURN_V2_KIND

    def buffer(kind, path, content):
        return {"kind": kind, "repository": "fixture", "path": path,
                "base_ref": "main", "base_revision": "0" * 40,
                "base_hash": "0" * 64, "content_hash": "0" * 64,
                "content": content, "dirty": False}

    return {"schema_version": 1, "kind": DOXBENCH_CHAT_TURN_V2_KIND,
            "client_turn_id": "honesty-turn-1", "scope": _SCOPE,
            "working_subject": "", "message": "What does this note claim?",
            "model_id": "honesty-model", "transcript": [],
            "last_assistant_turn_id": None,
            "bound_buffer": "notes/one.md",
            "buffers": [buffer("outline", None, "# outline"),
                        buffer("document", "notes/one.md", "# one")]}


def _structured(answer: tuple[int, dict, str]) -> bool:
    """An answer a client can read: a status, and a JSON body naming its
    error, or a stated 404. Anything else (an empty 500, a reset) is not."""
    status, body, raw = answer
    if body.get("ok") is False and isinstance(body.get("error"), str):
        return True
    # THE RELEASED FAILURE ENVELOPE IS STRUCTURED TOO. Where openDox's own
    # validators answer (plan 034 T085), a turn refusal arrives in
    # `workbench-chat-turn-v2-failure`, which carries `error` but no `ok`.
    if (str(body.get("kind", "")).endswith("-failure")
            and isinstance(body.get("error"), str)):
        return True
    return status == 404 and bool(raw.strip())


def _standalone(tmp_path, repo):
    """`python -m opendox.serve` over `repo`, as section 1 runs it, with its
    base address and its capabilities."""
    out = _snapshot(tmp_path, repo)
    child = Child(tmp_path, "opendox.serve", "--snapshot", str(out),
                  "--checkout-root", str(repo), "--port", "0")
    match = child.wait_for_line(_SERVE_URL)
    base = (match.group(2), int(match.group(3)))
    return child, base, _capabilities(base)


def test_the_three_crash_sites_answer_a_standalone_server(
        tmp_path, monkeypatch) -> None:
    """#1144 batch L (RULED `5920216845`, item 1). At `047bb4fa` each of these
    three ended a standalone request with a dropped connection, on a deferred
    `openxdox` import: the document abstract's above its step-1 check, model
    approval's past its only check, and the project register's with no check
    at all. Each now gets a structured answer, and none reaches for openXdox.
    Run with an identity, so `session` reads true and the abstract and the
    approval pass the checks a plane with no actor would refuse at."""
    from opendox import column_seams
    from opendox.serve_wire import (DOXBENCH_ERR_APPROVAL_REFUSED,
                                    DOXBENCH_ERR_MODEL_CAPABILITY_UNAVAILABLE)
    _clean_environment(monkeypatch)
    repo = _repository(tmp_path, identity=True)
    child, base, caps = _standalone(tmp_path, repo)
    try:
        # THE TOKEN IS NOT ON `/capabilities` (plan 034 T104): a standalone
        # plane delivers it in the opened URL, through its private copy.
        assert "console_token" not in caps, caps
        token = child.console_token(base[1])
        assert caps["actions"]["session"] is True and token, caps
        abstract = _call(base, "POST", "/actions/workbench/document-abstract",
                         body=_json(_ABSTRACT), token=token)
        approval = _call(base, "POST", "/actions/workbench/model-approval",
                         body=_json({"binding": "honesty-binding"}),
                         token=token)
        register = _call(base, "GET", "/project-register.json")
        for name, answer in (("document abstract", abstract),
                             ("model approval", approval),
                             ("project register", register)):
            assert _structured(answer), f"{name}: {answer}"
        # step 1 refuses once `gate` reads false (batch L)
        assert abstract[1]["error"] == DOXBENCH_ERR_MODEL_CAPABILITY_UNAVAILABLE
        # the seam refuses by name: no host's gate, so no record is written
        assert approval[1]["error"] == DOXBENCH_ERR_APPROVAL_REFUSED, approval
        assert approval[1]["reason"] == column_seams.GATE_RECORDS_REFUSAL
        # openDox's own kickoff discovers no register: today's 404
        assert register[0] == 404 and "no project register" in register[2]
        assert not (repo / "ideation" / "dashboard" / "gate-records").exists()
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()
    assert child.refused() == [], child.refused()


def test_the_rails_thread_read_answers_a_standalone_server(
        tmp_path, monkeypatch) -> None:
    """The chat rail's thread read, with the exact query the rail sends on
    opening a document (`views/staging-workbench.js` `loadThread`, called from
    `views/doxbench-chat.js`): a group tile and one of its members. Found by
    T095's AT-R1 harness (openDox-code#75): the route reached
    `from openxdox import doxbench_scope` (`serve_workbench.py:548` at
    `047bb4fa`) and dropped the connection. A query-less GET stops at the 400
    check first, which is why batch L's measurement missed it. The live-session
    question now goes through `column_seams.scope`, and a checkout with no open
    session answers the stated no-session absence."""
    from opendox import serve_workbench
    from opendox.serve_wire import DOXBENCH_ERR_THREAD_CAPABILITY_UNAVAILABLE
    _clean_environment(monkeypatch)
    repo = _repository(tmp_path, identity=True)
    child, base, caps = _standalone(tmp_path, repo)
    try:
        # THE TOKEN IS NOT ON `/capabilities` (plan 034 T104): a standalone
        # plane delivers it in the opened URL, through its private copy.
        assert "console_token" not in caps, caps
        token = child.console_token(base[1])
        assert caps["actions"]["session"] is True and token, caps
        status, body, raw = _call(
            base, "GET",
            "/workbench/thread?repository=fixture&ref=main&tile_kind=cluster"
            "&tile_id=barrel-rain&document=notes-rain-barrel-leak.md",
            token=token)
        assert _structured((status, body, raw)), (status, raw)
        assert body["error"] == DOXBENCH_ERR_THREAD_CAPABILITY_UNAVAILABLE, raw
        assert body.get("cause") == serve_workbench.NO_LIVE_SESSION_CAUSE, body
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()
    assert child.refused() == [], child.refused()


def test_an_unknown_tile_kind_on_the_thread_read_is_refused_not_dropped(
        tmp_path, monkeypatch) -> None:
    """Adversarial review 2, L1: `ScopeKey` refuses a `tile_kind` outside
    its closed vocabulary with a `ValueError`, which escaped the thread read
    and dropped the connection. It is a malformed query, answered so."""
    from opendox.serve_wire import DOXBENCH_ERR_INVALID_TURN_REQUEST
    _clean_environment(monkeypatch)
    repo = _repository(tmp_path, identity=True)
    child, base, caps = _standalone(tmp_path, repo)
    try:
        status, body, raw = _call(
            base, "GET",
            "/workbench/thread?repository=fixture&ref=main&tile_kind=bogus"
            "&tile_id=barrel-rain&document=notes-rain-barrel-leak.md",
            # a standalone plane's token, from its private copy (T104)
            token=child.console_token(base[1]))
        assert body.get("error") == DOXBENCH_ERR_INVALID_TURN_REQUEST, (status, raw)
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()
    assert child.refused() == [], child.refused()


def test_an_unknown_tile_kind_on_the_abstract_is_refused_not_dropped(
        composed_turns) -> None:
    """L1 on the document abstract, past step 1 (a host contributing the gate
    routes, so `gate` reads true)."""
    from opendox.serve_wire import DOXBENCH_ERR_INVALID_ABSTRACT_REQUEST
    base, caps = composed_turns(_gate())
    status, body, raw = _call(
        base, "POST", "/actions/workbench/document-abstract",
        body=_json({**_ABSTRACT, "scope": {**_SCOPE, "tile_kind": "bogus"}}),
        token=caps["console_token"])
    assert body.get("error") == DOXBENCH_ERR_INVALID_ABSTRACT_REQUEST, (status, raw)


def test_an_unknown_tile_kind_on_the_chat_turn_is_refused_not_dropped(
        composed_turns) -> None:
    """L1 on the chat turn, where validators that admit the shape carry it to
    the scope step: refused in the released envelope."""
    from opendox.serve_wire import DOXBENCH_ERR_INVALID_TURN_REQUEST
    base, caps = composed_turns()
    turn = _chat_turn()
    turn["scope"] = {**_SCOPE, "tile_kind": "bogus"}
    status, body, raw = _call(base, "POST", "/actions/workbench/chat-turn",
                              body=_json(turn), token=caps["console_token"])
    assert body.get("error") == DOXBENCH_ERR_INVALID_TURN_REQUEST, (status, raw)
    assert body.get("client_turn_id") == "honesty-turn-1", body


#: The binding `opendox model-binding add` declares for the cases below, as
#: `tests/test_model_provider_broker.py` declares its own. Nothing is spawned
#: and nothing is contacted: no case dispatches a turn.
_BINDING = ["--id", "honesty-binding", "--label", "Honesty binding",
            "--provider", "honesty-provider",
            "--credential-ref", "opref-4f2a91c07be3d5a8140b6e77",
            "--auth-kind", "api_key",
            "--credential-approver", "fixture@example.invalid",
            "--endpoint", "https://provider.invalid/turn",
            "--dialect", "xfactory-prompt-v1",
            "--", "honesty-broker", "--home", "/srv/{binding_id}"]


def test_a_chat_turn_with_a_binding_configured_is_answered_standalone(
        tmp_path, monkeypatch) -> None:
    """The chat-turn route over a standalone server whose checkout DECLARES a
    model binding (`opendox model-binding add`), so the turn does not stop at
    "no model configured" (T081) and runs on toward its scope step, which
    reached for openXdox by a deferred import until this task. The answer is
    structured, whichever step refuses it."""
    _clean_environment(monkeypatch)
    repo = _repository(tmp_path, identity=True)
    added, status = run_module(tmp_path, "opendox.cli", "model-binding", "add",
                               "--repo-root", str(repo), *_BINDING)
    assert status == 0, added.stderr_text()
    child, base, caps = _standalone(tmp_path, repo)
    try:
        # THE TOKEN IS NOT ON `/capabilities` (plan 034 T104): a standalone
        # plane delivers it in the opened URL, through its private copy.
        assert "console_token" not in caps, caps
        token = child.console_token(base[1])
        assert caps["actions"]["session"] is True and token, caps
        answer = _call(base, "POST", "/actions/workbench/chat-turn",
                       body=_json(_chat_turn()), token=token)
        assert _structured(answer), answer
        # past openDox's own validators (T085) to the scope step, which
        # reached openXdox by a deferred import until this task: the scope
        # names no tile of this snapshot, so it is refused, stated
        from opendox.serve_wire import DOXBENCH_ERR_TURN_SCOPE_REFUSED
        assert answer[1]["error"] == DOXBENCH_ERR_TURN_SCOPE_REFUSED, answer
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()
    assert child.refused() == [], child.refused()


class _Conforms:
    """A validator every instance conforms to."""

    @staticmethod
    def iter_errors(_instance):
        return iter(())


class _EveryKind(dict):
    """The released validators, as a plane that can read its contract has
    them: one for every kind, each of which every instance conforms to. So a
    turn's own shape carries it to the scope step."""

    def get(self, _kind, _default=None):
        return _Conforms()


class _Port:
    """A model port. Never dispatched: every case is refused before."""


def test_a_chat_turn_reaching_its_scope_step_is_refused_not_dropped(
        composed_turns) -> None:
    """A composed host with the released validators and a model port, so a
    well-formed turn reaches step 5. At `047bb4fa` step 5 opened with a
    deferred `from openxdox import doxbench_scope`, and the connection dropped.
    The scope authority is now the one registered at `column_seams.scope`,
    openDox's own default here, and the scope is refused in the released
    failure envelope."""
    from opendox.serve_wire import DOXBENCH_ERR_TURN_SCOPE_REFUSED
    base, caps = composed_turns()
    status, body, raw = _call(base, "POST", "/actions/workbench/chat-turn",
                              body=_json(_chat_turn()),
                              token=caps["console_token"])
    assert body.get("error") == DOXBENCH_ERR_TURN_SCOPE_REFUSED, (status, raw)
    assert body.get("client_turn_id") == "honesty-turn-1", body


def test_a_document_abstract_past_step_one_is_refused_not_dropped(
        composed_turns) -> None:
    """A composed host that contributes the gate routes, so `gate` reads true
    and an abstract request passes step 1 and reaches its scope step, which
    reads the scope authority through its seam (batch L): refused, stated."""
    from opendox.serve_wire import DOXBENCH_ERR_TURN_SCOPE_REFUSED
    base, caps = composed_turns(_gate())
    assert caps["actions"]["gate"] is True, caps
    status, body, raw = _call(base, "POST",
                              "/actions/workbench/document-abstract",
                              body=_json(_ABSTRACT),
                              token=caps["console_token"])
    assert body.get("error") == DOXBENCH_ERR_TURN_SCOPE_REFUSED, (status, raw)


@pytest.fixture()
def composed_turns(tmp_path):
    """`build(*contributions)`: `composed`'s host, with the released
    validators and a model port declared, as a plane that can run a turn has
    them. Yields `(base, capabilities)`."""
    from opendox import serve

    repo = _repository(tmp_path, identity=True)
    out = _snapshot(tmp_path, repo)
    servers = []

    def build(*contributed):
        bindings = [binding for binding, _mixin in contributed]
        mixins = [mixin for _binding, mixin in contributed]
        httpd = serve.build_server(
            WEB, out, repo, port=0, actor="brett",
            route_extensions=(_Contribution(bindings, mixins),)
            if contributed else (),
            schema_validator_factory=_EveryKind,
            model_port_factory=_Port)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        servers.append((httpd, worker))
        base = httpd.server_address[:2]
        return base, _capabilities(base)

    try:
        yield build
    finally:
        for httpd, worker in servers:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=10)


# ---------------------------------------------------------------------------
# 6 — model intake and approval: not offered where no record can be written
# ---------------------------------------------------------------------------
#
# RULED by Brett Heap, 2026-10-02, "Refuse by name, hide intake
# (Recommended)". The enrolment ends in a recorded approval, a governed
# gate-action record that only a HOST's gate writes; openDox's own default
# writes none. So with no host's gate registered the surface answers
# `offered: false` with a stated reason, even beside a hand-written broker
# block, and the intake act and the approval refuse naming the seam, writing
# nothing. A host that registers its gate is offered the flow, and its
# approval is recorded.

#: The pending declaration a hand-written document carries, for the binding
#: `_BINDING` declares.
_PENDING = {"binding_id": "honesty-binding", "status": "pending",
            "install_posture": "single-operator", "proposed_by": "brett",
            "proposed_at": "2026-10-02T00:00:00Z"}

#: The intake act's declared facts, on its query string.
_INTAKE = ("/actions/workbench/model-intake?binding=honesty-intake"
           "&label=Honesty&provider=honesty-provider"
           "&endpoint=https%3A%2F%2Fprovider.invalid%2Fturn"
           "&dialect=xfactory-prompt-v1&kind=api_key")


def _declare(tmp_path: Path, repo: Path) -> Path:
    """A binding declared with `opendox model-binding add`, and a declarations
    document written BY HAND beside it, naming a broker and the binding's
    pending declaration. Returns the document's path."""
    import yaml
    from opendox import doxbench_intake

    added, status = run_module(tmp_path, "opendox.cli", "model-binding", "add",
                               "--repo-root", str(repo), *_BINDING)
    assert status == 0, added.stderr_text()
    path = doxbench_intake.declarations_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "schema_version": doxbench_intake.SCHEMA_VERSION,
        "kind": doxbench_intake.DECLARATIONS_KIND,
        "broker": {"kind": doxbench_intake.BROKER_KIND,
                   "argv": ["honesty-broker", "intake"]},
        "declarations": [dict(_PENDING)],
    }, sort_keys=False), encoding="utf-8")
    return path


def test_a_standalone_server_does_not_offer_an_intake_it_could_not_approve(
        tmp_path, monkeypatch) -> None:
    from opendox import column_seams
    from opendox.serve_wire import (DOXBENCH_ERR_APPROVAL_REFUSED,
                                    DOXBENCH_ERR_INTAKE_REFUSED)
    _clean_environment(monkeypatch)
    repo = _repository(tmp_path, identity=True)
    document = _declare(tmp_path, repo)
    before = document.read_bytes()
    child, base, caps = _standalone(tmp_path, repo)
    try:
        # THE TOKEN IS NOT ON `/capabilities` (plan 034 T104): a standalone
        # plane delivers it in the opened URL, through its private copy.
        assert "console_token" not in caps, caps
        token = child.console_token(base[1])
        assert caps["actions"]["session"] is True and token, caps
        status, surface, raw = _call(base, "GET", "/workbench/model-intake",
                                     token=token)
        assert status == 200, raw
        # a broker block is declared, and still the flow is not offered
        assert surface["offered"] is False, surface
        assert surface["reason"] == column_seams.GATE_RECORDS_REFUSAL, surface
        assert surface["auth_kinds"] == [] and surface["dialects"] == []
        intake = _call(base, "POST", _INTAKE, body=b"not-a-real-credential",
                       token=token)
        assert intake[1].get("error") == DOXBENCH_ERR_INTAKE_REFUSED, intake
        assert intake[1]["reason"] == column_seams.GATE_RECORDS_REFUSAL
        approval = _call(base, "POST", "/actions/workbench/model-approval",
                         body=_json({"binding": "honesty-binding"}),
                         token=token)
        assert approval[1].get("error") == DOXBENCH_ERR_APPROVAL_REFUSED
        assert approval[1]["reason"] == column_seams.GATE_RECORDS_REFUSAL
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()
    assert child.refused() == [], child.refused()
    # nothing was written: the declaration is still pending, no record exists
    assert document.read_bytes() == before
    assert not (repo / "ideation" / "dashboard" / "gate-records").exists()


class _HostGate:
    """A HOST's gate: openDox's own default for every name, except that it
    WRITES the gate-action record the default refuses to, into a list."""

    def __init__(self) -> None:
        from opendox import column_seams, default_columns
        for name in (*column_seams.GATE_CALLABLES, *column_seams.GATE_VALUES):
            if name not in type(self).__dict__:
                setattr(self, name, getattr(default_columns.GATE, name))
        self.__name__ = "tests.test_capability_honesty._HostGate"
        self.written: list[tuple[str, dict]] = []

    def build_gate_action_record(self, **fields):
        return dict(fields)

    def validate_gate_action_record(self, record):
        assert record["action"] and record["actor"], record

    def HumanGate(self, root, prefixes, *, human_actor):  # noqa: N802
        return (root, tuple(prefixes), human_actor)

    def write_gate_action_record(self, human, records_dir, record):
        self.written.append((records_dir, record))
        return Path(human[0]) / records_dir / "honesty.gate-action.yaml"


@pytest.fixture()
def host_gate():
    """A host's gate registered at `column_seams.gate` for the case, as a host
    registers it at process start, and dropped afterwards. Whatever this
    process registered before (a default an earlier case read) is dropped
    first: the swap is deliberate."""
    from opendox import column_seams
    gate = _HostGate()
    column_seams.gate.unregister()
    column_seams.gate.register(gate)
    try:
        yield gate
    finally:
        column_seams.gate.unregister()


class _HostTrust:
    """A HOST's trust policy that admits the console intake's hand-off, as a
    host offering the intake registers one (T100 follow-on, A5): openDox's
    own per-machine trust admits no intake, so under it the surface is not
    offered. It trusts no binding."""

    def verdict(self, binding, *, root):
        from opendox import doxbench_trust
        return doxbench_trust.TrustVerdict.untrusted_for(
            binding, root=root, basis=doxbench_trust.BASIS_HOST,
            reason="this stand-in host trusts no binding")

    def record(self, binding, *, root):
        return self.verdict(binding, root=root)

    def intake_verdict(self, binding, *, root):
        from opendox import doxbench_trust
        return doxbench_trust.TrustVerdict.trusted_for(
            binding, root=root, basis=doxbench_trust.BASIS_HOST)


def test_a_host_that_registers_its_gate_is_offered_intake_and_approves(
        tmp_path, host_gate) -> None:
    import yaml
    from opendox import doxbench_intake, doxbench_trust, serve

    doxbench_trust.unregister()
    doxbench_trust.register(_HostTrust())
    repo = _repository(tmp_path, identity=True)
    document = _declare(tmp_path, repo)
    out = _snapshot(tmp_path, repo)
    httpd = serve.build_server(WEB, out, repo, port=0, actor="brett")
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        base = httpd.server_address[:2]
        caps = _capabilities(base)
        token = caps["console_token"]
        status, surface, raw = _call(base, "GET", "/workbench/model-intake",
                                     token=token)
        assert status == 200, raw
        assert surface["offered"] is True and "reason" not in surface, surface
        assert surface["auth_kinds"], surface
        status, approved, raw = _call(
            base, "POST", "/actions/workbench/model-approval",
            body=_json({"binding": "honesty-binding"}), token=token)
        assert status == 200 and approved.get("ok") is True, raw
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)
    # the host's gate wrote the record, BEFORE the document moved
    assert len(host_gate.written) == 1, host_gate.written
    records_dir, record = host_gate.written[0]
    assert record["action"] == doxbench_intake.GATE_ACTION_APPROVE_MODEL
    assert record["model_declaration"] == "honesty-binding"
    stored = yaml.safe_load(document.read_text(encoding="utf-8"))
    assert stored["declarations"][0]["status"] == doxbench_intake.STATUS_APPROVED
    assert stored["declarations"][0]["approved_by"] == "brett"


def test_whether_a_gate_record_can_be_written_follows_the_registration(
        host_gate) -> None:
    """The predicate itself: a host's registration answers true; openDox's
    own default, registered by an entry point, answers false; and asking reads
    nothing, so it closes no default's window."""
    from opendox import column_seams
    assert column_seams.gate_records_writable() is True
    column_seams.gate.unregister()
    assert column_seams.gate_records_writable() is False
    column_seams.register_defaults()
    assert column_seams.gate_records_writable() is False
    # still replaceable: asking did not read the default
    column_seams.gate.register(host_gate)
    assert column_seams.gate_records_writable() is True
