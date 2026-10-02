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


def _assert_every_true_flag_answers(base: tuple[str, int], caps: dict) -> None:
    """Case 3: every `actions` key is accounted for, and each that reads true
    has a route that answers something other than `unknown_action`."""
    actions = caps["actions"]
    assert set(actions) == set(GOVERNED), (
        f"the actions map has keys this test does not account for: "
        f"{sorted(set(actions) ^ set(GOVERNED))}")
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
        _assert_every_true_flag_answers(base, caps)
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
    _assert_every_true_flag_answers(base, caps)


def test_a_gate_only_host_reads_only_gate_true(composed) -> None:
    base, caps = composed(_gate())
    assert caps["actions"]["gate"] is True, caps
    assert caps["actions"]["refresh"] is False, caps
    _assert_every_true_flag_answers(base, caps)


def test_a_refresh_only_host_reads_only_refresh_true(composed) -> None:
    base, caps = composed(_refresh())
    assert caps["actions"]["refresh"] is True, caps
    assert caps["actions"]["gate"] is False, caps
    _assert_every_true_flag_answers(base, caps)


def test_the_same_host_with_nothing_contributed_reads_both_false(composed) -> None:
    """The control: the same checkout, actor and bind, and no contribution."""
    base, caps = composed()
    assert caps["actor"] == "brett", caps
    assert caps["actions"]["gate"] is False and caps["actions"]["refresh"] is False
    assert caps["actions"]["session"] is True
    _assert_every_true_flag_answers(base, caps)


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
