"""Chat's model configuration, with NO MODEL CONFIGURED: #1144's 16.4, which
plan 034's T081 realizes (requirement 17's third scenario, *"No model is
configured"*).

16.4 measured the gap at `1e4a57fb`. With no binding,
`declared_model_port_factory(...)()` resolved the harness declaration, and its
catalog offered `omp-local` as AVAILABLE with no `omp` on the PATH. So an install
with no model read as one with a model until a turn failed. This file holds the
state 16.4 asks for:

1. F16.1'S CATALOG BLOCK, AS WRITTEN. With no binding and no harness, the
   catalog offers no available entry.
2. THE DECLARATION, STATE BY STATE. No approved binding and no harness gives
   openDox's no-model port. A harness on the PATH gives the harness bridge, so
   the harness route stays, and resolving it spawns nothing. The binding
   states the port reads are each pinned:
   - a hand- or CLI-declared binding, which the intake document says nothing
     about, makes the port present;
   - a `pending` intake declaration is suppressed;
   - an `approved` one makes the port present;
   - an unreadable bindings document is read as declaring none.
3. THE PORT AND THE ACCESSOR. The no-model port is a `WorkbenchModelPort`,
   its catalog is empty, and its `dispatch` refuses without spawning or
   contacting anything. `serve_workbench`'s accessor answers it, and only it,
   as no port.
4. THE SERVED ROUTES, STANDALONE. A `generate-and-open` child with neither
   sibling importable (`tests/standalone_child.py`) answers the catalog route
   200 with no available entry. This is T085's falsifier's second half, and
   it needs T085's validators. The child also answers a schema-valid turn
   `403 model_capability_unavailable`, and the same turn without the console
   token `console_required`.
   THE TURN ROUTE'S ORDER (the holder's ruling on the hoist, option (a)): a
   console, body, kind, schema or parse defect answers first in every
   posture; with no port, the no-model refusal answers before a scope,
   identity or limits defect and the scope is never read; with a port, every
   defect answers what it answered before the hoist.
5. THE CHAT RAIL. Mounted over an EMPTY catalog with no intake flow, the rail
   shows "No model configured" and how to configure one, visibly and before
   any turn, and announces it once through its polite live region, while the
   send button keeps its existing sentence byte for byte. The line shows in
   that state only: a catalog of configured models that are unavailable is
   not "no model configured". Its spelling is held to the Python twin's.

`omp` is `doxbench_bridge.HARNESS_COMMAND`. A case that means "no harness"
says so with `harness_present=lambda: False`, or with a PATH holding no `omp`,
and asserts it.

Plan 034's T082 adds 16.5 here (every other surface, with no model), and
T078–T080 add the configured turn over a stand-in OpenAI-compatible server.
F16.1's last line runs this file whole once all of them have landed (T083).

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import copy
import dataclasses
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from opendox import doxbench_binding as binding_mod
from opendox import doxbench_bridge as bridge_mod
from opendox import doxbench_hash
from opendox import doxbench_install as inst
from opendox import doxbench_intake as intake_mod
from opendox import doxbench_model
from opendox import doxbench_turns
from opendox import serve_wire
from opendox import validator as own
from opendox.serve_workbench import WorkbenchRoutes
from session_fixtures import GATE_TEST_PRINCIPALS
from standalone_child import Child, fresh_repository, run_module

ROOT = Path(__file__).resolve().parent.parent
PLAIN = ROOT / "tests" / "fixtures" / "plain-documents"
EXAMPLES = ROOT / "tests" / "fixtures" / "spec-examples"
CHAT_VIEW_JS = ROOT / "src" / "opendox" / "web" / "views" / "doxbench-chat.js"
CHAT_MODEL_JS = ROOT / "src" / "opendox" / "web" / "views" / "doxbench-chat-model.js"
NODE = shutil.which("node")

#: The console's human, one of the suite's declared principals.
ACTOR = "tester"

#: The rail's existing configured-none sentence, which add-doxchat-model-intake
#: §1 keeps byte for byte.
CONFIGURED_NONE = ("chat is unavailable — no approved model is configured; both "
                   "editors remain fully usable.")


def _no_omp_path(tmp_path: Path) -> str:
    """This process's PATH with every directory holding `omp` left out."""
    kept = [entry for entry in os.environ.get("PATH", "").split(os.pathsep)
            if entry and shutil.which(bridge_mod.HARNESS_COMMAND, path=entry) is None]
    path = os.pathsep.join(kept)
    assert shutil.which(bridge_mod.HARNESS_COMMAND, path=path) is None
    return path


def _fake_omp(tmp_path: Path) -> Path:
    """A directory holding an executable named `omp`, which is never run."""
    bin_dir = tmp_path / "harness-bin"
    bin_dir.mkdir()
    omp = bin_dir / bridge_mod.HARNESS_COMMAND
    omp.write_text("#!/bin/sh\necho 'a fake harness must never run' >&2\nexit 97\n",
                   encoding="utf-8")
    omp.chmod(0o755)
    return bin_dir


def _binding(**overrides) -> binding_mod.ModelProviderBinding:
    fields = dict(id="a-provider", label="A provider", provider="a-provider",
                  credential_ref="opref-0000000000000000", auth_kind="api_key",
                  approved_by="tester", endpoint="https://provider.invalid/turn",
                  dialect=binding_mod.DIALECT_XFACTORY_PROMPT_V1,
                  broker_argv=("a-broker",))
    fields.update(overrides)
    return binding_mod.ModelProviderBinding(**fields)


def _declare(checkout: Path, binding=None) -> binding_mod.ModelProviderBinding:
    """A binding declared in the checkout's bindings document, as
    `opendox model-binding add` declares one."""
    binding = binding or _binding()
    binding_mod.BindingStore(binding_mod.bindings_path(checkout)).add(binding)
    return binding


def _resolve(tmp_path: Path, checkout: Path, *, harness: bool, spawn=None):
    return inst.declared_model_port_factory(
        tmp_path / "sessions", checkout_root=checkout, spawn=spawn,
        harness_present=lambda: harness)()


@pytest.fixture
def checkout(tmp_path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    return root


class _NoSpawn:
    """A `spawn` seam that records any call. Resolving a port must not call it."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("a child process was spawned")


# ---------------------------------------------------------------------------
# 1 — F16.1's catalog block, as written
# ---------------------------------------------------------------------------

_F16_1_CATALOG_BLOCK = textwrap.dedent('''
    import pathlib, sys
    from opendox import doxbench_install as inst
    root = pathlib.Path(sys.argv[1]) / "no-model"
    root.mkdir()
    port = inst.declared_model_port_factory(root / "sessions", checkout_root=root)()
    offered = [e.model_id for e in port.catalog().available_entries()]
    assert not offered, f"no model is configured, yet the catalog offers {offered}"
    print("no model configured: the catalog offers nothing")
    ''')


def test_F16_1s_catalog_block_with_no_binding_and_no_harness(tmp_path) -> None:
    """#1144's F16.1, its 16.4 block word for word, in a process whose PATH
    holds no `omp` (F16.1's own precondition). At `047bb4fa` it failed with
    `['omp-local']`."""
    done = subprocess.run(
        [sys.executable, "-", str(tmp_path)], input=_F16_1_CATALOG_BLOCK,
        capture_output=True, text=True, cwd=ROOT, timeout=120,
        env=dict(os.environ, PATH=_no_omp_path(tmp_path)))
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "no model configured: the catalog offers nothing"


# ---------------------------------------------------------------------------
# 2 — the declaration, state by state
# ---------------------------------------------------------------------------

def test_no_binding_and_no_harness_is_the_no_model_port(tmp_path, checkout) -> None:
    spawn = _NoSpawn()
    port = _resolve(tmp_path, checkout, harness=False, spawn=spawn)
    assert port is doxbench_model.NO_MODEL_CONFIGURED
    assert port.catalog().available_entries() == ()
    assert spawn.calls == []


def test_the_harness_route_stays_where_the_harness_is_installed(
        tmp_path, checkout, monkeypatch) -> None:
    """With `omp` on the PATH, the default probe finds it, and the harness
    bridge answers exactly as it always has. Resolving it spawns nothing."""
    monkeypatch.setenv("PATH", str(_fake_omp(tmp_path)) + os.pathsep
                       + _no_omp_path(tmp_path))
    assert inst.harness_installed() is True
    spawn = _NoSpawn()
    port = inst.declared_model_port_factory(
        tmp_path / "sessions", checkout_root=checkout, spawn=spawn)()
    assert isinstance(port, bridge_mod.OmpHarnessBridge)
    assert [entry.model_id for entry in port.catalog().available_entries()] == \
        [inst.HARNESS_MODEL_ID]
    assert spawn.calls == []


def test_the_default_probe_reads_the_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", _no_omp_path(tmp_path))
    assert inst.harness_installed() is False
    monkeypatch.setenv("PATH", str(_fake_omp(tmp_path)))
    assert inst.harness_installed() is True


def test_a_hand_declared_binding_makes_the_port_present(tmp_path, checkout) -> None:
    """A binding `opendox model-binding add` declares writes the bindings
    document alone, and the intake document says nothing about it, so it is
    never `pending`. That is how a standalone install configures a model
    without the console's approval route."""
    binding = _declare(checkout)
    from opendox import doxbench_provider as provider_mod
    port = _resolve(tmp_path, checkout, harness=False)
    assert isinstance(port, provider_mod.BrokeredProviderPort)
    assert [e.model_id for e in port.catalog().available_entries()] == [binding.id]


def _intake(checkout: Path) -> intake_mod.DeclarationStore:
    return intake_mod.DeclarationStore(intake_mod.declarations_path(checkout))


def _pending(binding_id: str) -> intake_mod.ModelDeclaration:
    return intake_mod.ModelDeclaration(
        binding_id=binding_id, status=intake_mod.STATUS_PENDING,
        install_posture=intake_mod.POSTURE_SINGLE_OPERATOR, proposed_by="tester",
        proposed_at="2026-10-02T00:00:00Z")


def test_a_pending_declaration_is_suppressed(tmp_path, checkout, capsys) -> None:
    binding = _declare(checkout)
    _intake(checkout).propose(_pending(binding.id))
    assert _resolve(tmp_path, checkout, harness=False) is \
        doxbench_model.NO_MODEL_CONFIGURED
    assert "pending human approval" in capsys.readouterr().err


def test_an_approved_declaration_makes_the_port_present(tmp_path, checkout) -> None:
    binding = _declare(checkout)
    store = _intake(checkout)
    store.propose(_pending(binding.id))
    store.approve(binding.id, issued_by="tester", approved_by="tester",
                  expires_at="2027-01-01T00:00:00Z", audit_ref="audit-0001")
    from opendox import doxbench_provider as provider_mod
    assert isinstance(_resolve(tmp_path, checkout, harness=False),
                      provider_mod.BrokeredProviderPort)


def test_an_unreadable_bindings_document_is_read_as_declaring_none(
        tmp_path, checkout, capsys) -> None:
    path = binding_mod.bindings_path(checkout)
    path.parent.mkdir(parents=True)
    path.write_text("schema_version: 9\nkind: something-else\n", encoding="utf-8")
    assert _resolve(tmp_path, checkout, harness=False) is \
        doxbench_model.NO_MODEL_CONFIGURED
    assert "reading it as declaring no binding" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 3 — the port, and the accessor that answers it as no port
# ---------------------------------------------------------------------------

def test_the_no_model_port_is_a_port_that_offers_nothing_and_refuses(monkeypatch) -> None:
    port = doxbench_model.NO_MODEL_CONFIGURED
    assert isinstance(port, doxbench_model.WorkbenchModelPort)
    assert port.catalog() is doxbench_model.EMPTY_CATALOG
    doxbench_model.validated_timeout_seconds(port.timeout_seconds)

    def refused(*args, **kwargs):
        raise AssertionError("dispatch reached a process or the network")

    import socket
    monkeypatch.setattr(subprocess, "Popen", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
    with pytest.raises(doxbench_model.NoModelConfiguredError) as raised:
        port.dispatch(object())
    assert str(raised.value) == doxbench_model.NO_MODEL_CONFIGURED_REMEDY


class _Plane:
    """The two facts `_workbench_model_port` reads, and nothing else."""

    capabilities = {"actions": {"session": True}}

    def __init__(self, factory):
        self.model_port_factory = factory


def test_the_accessor_answers_the_no_model_port_as_no_port() -> None:
    accessor = WorkbenchRoutes._workbench_model_port
    assert accessor(_Plane(inst.no_model_port_factory)) is None
    other = doxbench_model.NoModelConfigured()
    assert accessor(_Plane(lambda: other)) is other, \
        "only THE no-model port is absence; anything else is a port"
    real = object()
    assert accessor(_Plane(lambda: real)) is real


# ---------------------------------------------------------------------------
# 4 — the served routes, standalone
# ---------------------------------------------------------------------------

_URL = re.compile(r"(http://([0-9.]+):([0-9]+))/index\.html$")


def _request(base, method, path, *, body=None, headers=None):
    connection = http.client.HTTPConnection(*base, timeout=30)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, json.loads(response.read() or b"null")
    finally:
        connection.close()


@pytest.fixture
def standalone(tmp_path, monkeypatch):
    """A `generate-and-open` child over T050's fixture, with neither sibling
    importable, no binding, and a PATH holding no `omp`. Answers
    `(base, console token, child)`."""
    assert ACTOR in GATE_TEST_PRINCIPALS
    repo = fresh_repository(PLAIN, tmp_path)
    monkeypatch.setenv("PATH", _no_omp_path(tmp_path))   # the child inherits it
    child = Child(tmp_path, "opendox.cli", "generate-and-open",
                  "--repo-root", str(repo), "--repository", "fixture",
                  "--no-open", "--port", "0", "--run-dir", str(tmp_path / "run"),
                  "--actor", ACTOR)
    try:
        match = child.wait_for_line(_URL)
        base = (match.group(2), int(match.group(3)))
        status, capabilities = _request(base, "GET", "/capabilities")
        assert status == 200 and capabilities["actions"]["session"] is True
        yield base, capabilities["console_token"], child
        assert child.interrupt() == 0, child.stderr_text()
        assert child.refused() == [], child.refused()
        assert "Traceback" not in child.stderr_text(), child.stderr_text()
    finally:
        child.kill()


def test_the_served_catalog_offers_no_available_entry(standalone) -> None:
    """T085's falsifier, whole: the served catalog route answers standalone,
    with no available entry, in an envelope openDox's own validator accepts."""
    base, token, _child = standalone
    status, envelope = _request(base, "GET", "/workbench/model-catalog",
                                headers={"X-XF-Console-Token": token})
    assert status == 200, envelope
    assert envelope["kind"] == serve_wire.DOXBENCH_MODEL_CATALOG_KIND
    assert own.validate(envelope) == []
    assert [m for m in envelope["models"] if m["available"]] == []


def _example_turn() -> dict:
    return yaml.safe_load(
        (EXAMPLES / "workbench-chat-turn-v2-loaded-set.example.yaml").read_text(
            encoding="utf-8"))


def test_a_turn_is_refused_model_capability_unavailable(standalone) -> None:
    """A schema-valid turn, which no rail sends with no model selected but any
    client can, is refused with the fixed code and the contract's failure
    envelope, and the child spawns no harness (none is on its PATH, and the
    no-model port spawns nothing). The CONSOLE verdict still comes first: the
    same turn without the console token is refused `console_required`, so an
    unauthenticated caller learns nothing about the model posture."""
    base, token, _child = standalone
    request = _example_turn()
    status, body = _request(
        base, "POST", "/actions/workbench/chat-turn",
        body=json.dumps(request).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    console = serve_wire.DOXBENCH_ERR_CONSOLE_REQUIRED
    assert (status, body["error"]) == (serve_wire.doxbench_error_status(console),
                                       console), body
    status, body = _request(
        base, "POST", "/actions/workbench/chat-turn",
        body=json.dumps(request).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-XF-Console-Token": token})
    code = serve_wire.DOXBENCH_ERR_MODEL_CAPABILITY_UNAVAILABLE
    assert status == serve_wire.doxbench_error_status(code) == 403, body
    assert body["error"] == code, body
    assert body["kind"] == serve_wire.DOXBENCH_CHAT_TURN_V2_FAILURE_KIND
    assert body["client_turn_id"] == request["client_turn_id"]
    assert own.validate(body) == [], own.report(own.validate(body))


# ---------------------------------------------------------------------------
# 4b — the turn route's ORDER, with and without a port (the holder's ruling
# on 0a12dc58: option (a), with an ordering test)
# ---------------------------------------------------------------------------

class _OfferingNothing:
    """A CONFIGURED port whose catalog offers nothing: reaching its catalog is
    step 7 (`model_unavailable`), and reaching `dispatch` would be a defect."""

    timeout_seconds = 30.0

    def catalog(self):
        return doxbench_model.EMPTY_CATALOG

    def dispatch(self, prompt_envelope):
        raise AssertionError("a turn with a defect was dispatched")


class _Registry:
    """The server's scope truth for one key: found, or not. Every read is
    recorded, so a case can assert the scope was never read."""

    def __init__(self, found: bool, root: Path):
        self.found, self.root, self.reads = found, root, []

    def resolve(self, repository, ref):
        self.reads.append((repository, ref))
        if not self.found:
            return None
        return SimpleNamespace(source_root=str(self.root), repository=repository,
                               ref=ref, session_base=None,
                               read_bytes=lambda: b"{}")


class _TurnRoute(WorkbenchRoutes):
    """`_handle_workbench_chat_turn` itself, over openDox's real validators
    (T085) and its real identity checks, with only the HTTP plumbing replaced:
    the console verdict, the bounded body read, and the reply."""

    loopback = True
    capabilities = {"actions": {"session": True}}
    actor = ACTOR

    def __init__(self, payload, *, port_factory, root, console=None,
                 body_bound=None, parsed=True, scope_found=True):
        self.payload, self.console, self.body_bound = payload, console, body_bound
        self.parsed = parsed
        self.model_port_factory = port_factory
        self.schema_validator_factory = own.doxbench_validators
        self.source = SimpleNamespace(registry=_Registry(scope_found, root))
        self.sent = []

    def _not_the_human_console(self):
        return self.console

    def _read_bounded_json_body(self, max_bytes, dimension):
        if self.body_bound is not None:
            return None, self.body_bound
        return self.payload, None

    def _parse_workbench_chat_turn_v2_body(self, payload):
        # "parse": a validator more permissive than the release would let a
        # body through that the parser still refuses
        if not self.parsed:
            return None
        return WorkbenchRoutes._parse_workbench_chat_turn_v2_body(payload)

    def _send_json(self, status, obj):
        self.sent.append((status, obj))


@pytest.fixture
def scope_stand_in(monkeypatch):
    """openxdox's scope module, which openDox's suite does not install (T084
    routes step 5 without it): a key type, the confinement error, and a scope
    that resolves. Revalidation against that projection is a no-op here, so
    step 5's verdict is exactly the registry's: found, or not."""
    scope = types.ModuleType("openxdox.doxbench_scope")

    @dataclasses.dataclass(frozen=True)
    class ScopeKey:
        repository: str
        ref: str
        tile_kind: str
        tile_id: str

    class ScopeConfinementError(ValueError):
        pass

    scope.ScopeKey = ScopeKey
    scope.ScopeConfinementError = ScopeConfinementError
    scope.session_created_paths_for_scope = lambda *args, **kwargs: ()
    scope.resolve_scope = lambda *args, **kwargs: SimpleNamespace()
    package = types.ModuleType("openxdox")
    package.doxbench_scope = scope
    monkeypatch.setitem(sys.modules, "openxdox", package)
    monkeypatch.setitem(sys.modules, "openxdox.doxbench_scope", scope)
    monkeypatch.setattr(doxbench_turns, "revalidate_scope", lambda **kwargs: None)


def _defective(defect: str) -> tuple[dict | None, dict]:
    """The example turn with one defect, and the route arguments it needs."""
    turn = copy.deepcopy(_example_turn())
    if defect == "console":
        return turn, {"console": "no console token was presented"}
    if defect == "not an object":
        return None, {}
    if defect == "body over its bound":
        return turn, {"body_bound": {"dimension": "request_body_bytes",
                                     "measured": 1_048_577, "maximum": 1_048_576}}
    if defect == "kind":
        turn["kind"] = "workbench-chat-turn"          # the retired v1 kind
    elif defect == "schema":
        del turn["message"]
    elif defect == "parse":
        return turn, {"parsed": False}
    elif defect == "scope":
        return turn, {"scope_found": False}
    elif defect == "identity":
        turn["buffers"][0]["content"] += "edited after hashing\n"
    elif defect == "limits":
        # within the schema's 1 MiB `maxLength`, past step 6's 400 000 bytes
        big = "a" * (doxbench_hash.MAX_BUFFER_BYTES + 1)
        digest = doxbench_hash.sha256_hex(big, max_bytes=None)
        turn["buffers"][1].update(content=big, content_hash=digest, base_hash=digest)
    else:
        assert defect == "none", defect
    return turn, {}


#: Each defect's verdict WITH a configured port: today's order, unchanged.
_WITH_A_PORT = {
    "console": serve_wire.DOXBENCH_ERR_CONSOLE_REQUIRED,
    "body over its bound": serve_wire.DOXBENCH_ERR_REQUEST_LIMIT_EXCEEDED,
    "not an object": "invalid_body",
    "kind": serve_wire.DOXBENCH_ERR_UNRECOGNIZED_TURN_KIND,
    "schema": serve_wire.DOXBENCH_ERR_INVALID_TURN_REQUEST,
    "parse": serve_wire.DOXBENCH_ERR_INVALID_TURN_REQUEST,
    "scope": serve_wire.DOXBENCH_ERR_TURN_SCOPE_REFUSED,
    "identity": serve_wire.DOXBENCH_ERR_CONTENT_IDENTITY_MISMATCH,
    "limits": serve_wire.DOXBENCH_ERR_REQUEST_LIMIT_EXCEEDED,
    "none": serve_wire.DOXBENCH_ERR_MODEL_UNAVAILABLE,     # step 7, after step 6
}

#: The defects that still answer FIRST with no port: the console, the body,
#: the kind, the schema and the parse. Every later one yields to the
#: no-model verdict.
_BEFORE_THE_MODEL_VERDICT = ("console", "body over its bound", "not an object",
                             "kind", "schema", "parse")

_NO_PORT = {"no model configured": inst.no_model_port_factory, "no factory": None}


@pytest.mark.parametrize("defect", sorted(_WITH_A_PORT))
@pytest.mark.parametrize("posture", ["a port", *_NO_PORT])
def test_the_turn_routes_order_with_and_without_a_port(
        defect, posture, scope_stand_in, tmp_path) -> None:
    """A console, body, kind, schema or parse defect answers first in every
    posture. With no port (no model configured, or no factory), the no-model
    refusal answers before a scope, identity or limits defect, and the scope
    is never read. With a port, every defect answers what it answered before
    the hoist, and a well-formed turn reaches step 7."""
    payload, arguments = _defective(defect)
    port = _OfferingNothing()
    route = _TurnRoute(payload, root=tmp_path,
                       port_factory=(lambda: port) if posture == "a port"
                       else _NO_PORT[posture], **arguments)
    route._handle_workbench_chat_turn()
    assert len(route.sent) == 1, route.sent
    status, body = route.sent[0]
    expected = (_WITH_A_PORT[defect]
                if posture == "a port" or defect in _BEFORE_THE_MODEL_VERDICT
                else serve_wire.DOXBENCH_ERR_MODEL_CAPABILITY_UNAVAILABLE)
    assert body["error"] == expected, (posture, defect, body)
    if expected != "invalid_body":
        assert status == serve_wire.doxbench_error_status(expected)
    if posture != "a port":
        assert route.source.registry.reads == [], "the scope was read"


# ---------------------------------------------------------------------------
# 5 — the chat rail: "No model configured", and how to configure one
# ---------------------------------------------------------------------------

def test_the_rails_remedy_is_spelled_as_the_python_twin() -> None:
    source = CHAT_VIEW_JS.read_text(encoding="utf-8")
    match = re.search(r'export const NO_MODEL_CONFIGURED_REMEDY =\s*("(?:[^"\\]|\\.)*");',
                      source)
    assert match, "the rail declares NO_MODEL_CONFIGURED_REMEDY as one literal"
    assert json.loads(match.group(1)) == doxbench_model.NO_MODEL_CONFIGURED_REMEDY
    remedy = doxbench_model.NO_MODEL_CONFIGURED_REMEDY
    assert remedy.startswith("No model configured.")
    assert '"opendox model-binding add"' in remedy and '"omp"' in remedy


_RAIL_HARNESS = r"""
class Node {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = []; this.attributes = {}; this.listeners = {};
    this.className = ''; this._text = ''; this.hidden = false;
    this.disabled = false; this.value = ''; this.writes = [];
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join('');
  }
  set textContent(value) {
    this.children = []; this._text = String(value); this.writes.push(this._text);
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  append(...kids) { for (const k of kids) this.appendChild(k); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name)
      ? this.attributes[name] : null;
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  focus() {}
  walk() { return this.children.reduce((a, c) => a.concat(c.walk()), [this]); }
}
const doc = { createElement: (tag) => new Node(tag), activeElement: null };
const byClass = (root, cls) => root.walk().filter(
  (n) => String(n.className).split(' ').includes(cls));

import { mountDoxBenchChatRail, NO_MODEL_CONFIGURED_REMEDY,
         noModelConfiguredRemedy } from "./doxbench-chat.mjs";

const KEY = { repository: "fixture", ref: "main", tile_kind: "staged",
              tile_id: "a-topic" };
const ENTRY = { model_id: "model-a", label: "A model", provider_class: "local",
  available: true, input_limit_bytes: 800000, output_limit_bytes: 900000,
  data_handling: "on this host" };
const OFF = { ...ENTRY, model_id: "model-off", available: false };
const bufferOf = (kind, path) => ({ kind, path, base_ref: "main",
  base_revision: "r1", base_hash: { algorithm: "sha256", hex: "c".repeat(64) },
  current_hash: { algorithm: "sha256", hex: "d".repeat(64) },
  hash_pending: false, content: "# " + kind, dirty: false });
const editorState = () => ({ active_buffer: "document", buffers: {
  outline: bufferOf("outline", "docs/outline.md"),
  document: bufferOf("document", "docs/detail.md") } });

async function mount(catalog, { intake = null, intakeFirst = false } = {}) {
  const host = new Node("div"); host.ownerDocument = doc;
  let turns = 0;
  let release;
  const gate = new Promise((res) => { release = res; });
  const rail = mountDoxBenchChatRail(host, {
    scopeKey: KEY,
    transports: { catalog: async () => { await gate; return catalog(); },
                  chatTurn: async () => { turns += 1; return null; } },
    editorState });
  const line = () => byClass(host, "doxchat-no-model")[0] || null;
  const shown = () => (line() && !line().hidden) ? line().textContent : null;
  const announce = byClass(host, "doxchat-announce")[0];
  // how many times the polite region was written the remedy
  const announced = () => announce.writes.filter(
    (text) => text === NO_MODEL_CONFIGURED_REMEDY).length;
  const loading = shown();
  if (intake !== null && intakeFirst) rail.intakeOffer(intake);
  release();
  await rail.ready;
  if (intake !== null && !intakeFirst) rail.intakeOffer(intake);
  const onArrival = announced();
  // render() runs on every keystroke: type twice and count again
  const composer = byClass(host, "doxchat-composer")[0];
  for (const value of ["w", "wh"]) {
    composer.value = value;
    for (const fn of composer.listeners.input || []) fn({ target: composer });
  }
  const send = byClass(host, "doxchat-send")[0];
  return { loading, shown: shown(), exists: Boolean(line()), turns,
           announcePolite: announce.getAttribute("aria-live"),
           announcedOnArrival: onArrival, announcedAfterTyping: announced(),
           sendDisabled: send.disabled === true, sendTitle: send.title,
           srNote: (byClass(host, "doxchat-unavailable")[0] || {}).textContent };
}

const empty = () => ({ schema_version: 1, kind: "workbench-model-catalog", models: [] });
const out = {
  remedy: NO_MODEL_CONFIGURED_REMEDY,
  empty: await mount(empty),
  onlyUnavailable: await mount(() => ({ schema_version: 1,
    kind: "workbench-model-catalog", models: [OFF] })),
  available: await mount(() => ({ schema_version: 1,
    kind: "workbench-model-catalog", models: [ENTRY] })),
  unreadable: await mount(() => null),
  intakeOffered: await mount(empty, { intake: true }),
  intakeFirst: await mount(empty, { intake: true, intakeFirst: true }),
  // the pure verdict over states a mount does not reach in one shot: a
  // failure recorded beside an adopted empty catalog keeps its own remedy
  pure: {
    emptyAdopted: noModelConfiguredRemedy({ models: [], catalogFailure: null }),
    emptyThenUnreadable: noModelConfiguredRemedy(
      { models: [], catalogFailure: "unreadable" }),
    emptyThenStaleToken: noModelConfiguredRemedy(
      { models: [], catalogFailure: "console_required" }),
    // a configured model the broker refused: kept, `available: false`
    onlyUnavailable: noModelConfiguredRemedy({ models: [OFF], catalogFailure: null }),
  },
};
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def rail(tmp_path_factory) -> dict:
    if NODE is None:
        pytest.skip("node not available for the chat rail's no-model probe")
    work = tmp_path_factory.mktemp("no-model-rail")
    source = CHAT_VIEW_JS.read_text(encoding="utf-8").replace(
        "./doxbench-chat-model.js", "./doxbench-chat-model.mjs")
    (work / "doxbench-chat.mjs").write_text(source, encoding="utf-8")
    shutil.copy(CHAT_MODEL_JS, work / "doxbench-chat-model.mjs")
    harness = work / "harness.mjs"
    harness.write_text(_RAIL_HARNESS, encoding="utf-8")
    done = subprocess.run([NODE, str(harness)], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_rail_shows_no_model_configured_and_how_before_any_turn(rail) -> None:
    empty = rail["empty"]
    assert empty["shown"] == doxbench_model.NO_MODEL_CONFIGURED_REMEDY
    assert empty["turns"] == 0, "shown before any turn, and no turn was sent"
    assert empty["sendDisabled"] is True
    # the send button's own reason is the existing sentence, byte for byte
    assert empty["srNote"] == CONFIGURED_NONE
    assert empty["sendTitle"] == CONFIGURED_NONE


def test_a_configured_model_that_is_unavailable_is_not_no_model(rail) -> None:
    """After a broker refusal `BrokeredProviderPort.catalog()` keeps the
    binding with `available: false` (doxbench_provider.py). That operator HAS
    a model configured, and telling them to declare a binding would send them
    to the wrong repair: the line is for an EMPTY catalog only. The send
    button's configured-none sentence still states the posture."""
    only_unavailable = rail["onlyUnavailable"]
    assert only_unavailable["shown"] is None
    assert only_unavailable["announcedAfterTyping"] == 0
    assert only_unavailable["sendDisabled"] is True
    assert rail["pure"]["onlyUnavailable"] is None


def test_the_remedy_is_announced_once_when_it_arrives(rail) -> None:
    """The catalog settles asynchronously with no focus change, so the line's
    text also goes to the rail's polite live region -- once: render() runs on
    every keystroke, and a re-write of the same sentence would re-announce it."""
    empty = rail["empty"]
    assert empty["announcePolite"] == "polite"
    assert empty["announcedOnArrival"] == 1
    assert empty["announcedAfterTyping"] == 1, "typing re-announced the remedy"
    for case in ("available", "onlyUnavailable", "unreadable", "intakeFirst"):
        assert rail[case]["announcedAfterTyping"] == 0, case


def test_the_line_shows_in_that_state_only(rail) -> None:
    """Not while the catalog is loading (nothing is known yet), not with a
    model available, not when the catalog could not be read (that has its
    own remedy), and not where the intake flow is offered (its option is the
    remedy's home)."""
    for case in ("empty", "onlyUnavailable", "available", "unreadable",
                 "intakeOffered", "intakeFirst"):
        assert rail[case]["exists"] is True, case
        assert rail[case]["loading"] is None, case
    assert rail["available"]["shown"] is None
    assert rail["unreadable"]["shown"] is None
    assert rail["intakeOffered"]["shown"] is None
    assert rail["intakeFirst"]["shown"] is None
    assert rail["pure"] == {"emptyAdopted": doxbench_model.NO_MODEL_CONFIGURED_REMEDY,
                            "emptyThenUnreadable": None, "emptyThenStaleToken": None,
                            "onlyUnavailable": None}


# ---------------------------------------------------------------------------
# 6 — 16.5: every other surface works with no model (plan 034's T082)
# ---------------------------------------------------------------------------
#
# #1144's 16.5: "Documents, generation, the views, sessions and saving answer
# exactly as they do with a model configured." So each request below is sent
# TWICE, to two standalone `generate-and-open` children over the SAME commit (the
# second checkout is a byte copy of the first, `.git` included):
#
# * "no model": no binding, and no `omp` on the PATH;
# * "a binding": the copy, after `opendox model-binding add` declared one, which
#   is how a standalone user configures a model (the holder's binding states, at
#   openDox-code#74).
#
# Each answer must be AN ANSWER: an HTTP response, never a dropped connection,
# with no sibling import refused while it was made. And the two answers must be
# EQUAL, once the one value that is per-process by design (the console token) is
# set aside. A surface that only refuses standalone must refuse alike, and write
# nothing.
#
# FIVE CASES NEED T084, which routes the reaches that still drop a connection
# standalone (plan 034's T084; #1144 4.3's batch-L addendum, RULED `5920216845`
# item 1; and `5961364221` item 1 for model approval). Each is marked
# `xfail(strict=True)` and names T084, so CI stays green now and the marker turns
# red the moment T084's code makes the case pass. When T084 lands, T082 merges
# `main` and removes the markers in that merge.

#: The two postures, in the order every case reports them.
POSTURES = ("no model", "a binding")

#: The binding the configured posture declares, field by field, through the CLI.
_BINDING_ARGS = ("--id", "a-provider", "--label", "A provider",
                 "--provider", "a-provider",
                 "--credential-ref", "opref-0000000000000000",
                 "--auth-kind", "api_key", "--credential-approver", ACTOR,
                 "--endpoint", "https://provider.invalid/turn",
                 "--dialect", binding_mod.DIALECT_XFACTORY_PROMPT_V1,
                 "--", "a-broker")

#: A fixture document both checkouts carry.
_DOCUMENT = "notes-rain-barrel-leak.md"


@dataclasses.dataclass(frozen=True)
class _Answer:
    """One request's answer, or the fact that the connection dropped."""

    status: int | None          # None: no HTTP response at all
    content_type: str | None
    body: bytes
    reached: tuple[str, ...]    # sibling imports the child refused meanwhile

    @property
    def dropped(self) -> bool:
        return self.status is None

    def comparable(self):
        """What two postures must agree on. A JSON body is compared as data,
        with the per-process console token set aside; any other body, byte for
        byte."""
        body = self.body
        if (self.content_type or "").startswith("application/json"):
            body = json.loads(self.body or b"null")
            if isinstance(body, dict):
                body = {k: v for k, v in body.items() if k != "console_token"}
        return self.status, self.content_type, body


@dataclasses.dataclass
class _Posture:
    name: str
    repo: Path
    child: Child
    base: tuple[str, int]
    token: str

    def ask(self, method: str, path: str, body=None) -> _Answer:
        before = len(self.child.refused())
        headers = {"X-XF-Console-Token": self.token}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        connection = http.client.HTTPConnection(*self.base, timeout=30)
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            answer = (response.status, response.getheader("Content-Type"),
                      response.read())
        except (http.client.HTTPException, OSError):
            answer = (None, None, b"")
        finally:
            connection.close()
        return _Answer(*answer, tuple(self.child.refused()[before:]))

    def checkout(self) -> tuple[str, str]:
        """The checkout's HEAD and its full status, untracked files included."""
        def run(*args):
            return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                                  capture_output=True, text=True).stdout
        return run("rev-parse", "HEAD"), run("status", "--porcelain",
                                             "--untracked-files=all")


@pytest.fixture(scope="module")
def postures(tmp_path_factory):
    """The two standalone children. The environment is set only while they
    start, because each child copies it then."""
    from opendox import actor_identity as actor_mod
    work = tmp_path_factory.mktemp("no-model-surfaces")
    started: dict[str, _Posture] = {}
    try:
        with pytest.MonkeyPatch.context() as patch:
            for name in (actor_mod.GATEWAY_ENV, actor_mod.PRINCIPAL_ENV,
                         actor_mod.ALLOWLIST_ENV):
                patch.delenv(name, raising=False)
            patch.setenv(actor_mod.ROSTER_ENV, ", ".join(GATE_TEST_PRINCIPALS))
            patch.setenv("PATH", _no_omp_path(work))
            # select-to-edit launches the editor; `true` exits at once
            patch.setenv("EDITOR", "true")
            no_model = fresh_repository(PLAIN, work / "no-model")
            bound = work / "a-binding" / no_model.name
            shutil.copytree(no_model, bound, symlinks=True)
            added, status = run_module(work / "add", "opendox.cli", "model-binding",
                                       "add", "--repo-root", str(bound),
                                       *_BINDING_ARGS)
            assert status == 0, added.stderr_text()
            assert added.refused() == [], added.refused()
            assert binding_mod.bindings_path(bound).is_file()
            for name, repo in zip(POSTURES, (no_model, bound)):
                slug = name.replace(" ", "-")
                child = Child(work / f"child-{slug}", "opendox.cli",
                              "generate-and-open", "--repo-root", str(repo),
                              "--repository", "fixture", "--no-open", "--port", "0",
                              "--run-dir", str(work / f"run-{slug}"),
                              "--actor", ACTOR)
                started[name] = _Posture(name, repo, child, ("", 0), "")
                match = child.wait_for_line(_URL)
                base = (match.group(2), int(match.group(3)))
                status, capabilities = _request(base, "GET", "/capabilities")
                assert status == 200 and capabilities["actions"]["session"] is True
                started[name].base = base
                started[name].token = capabilities["console_token"]
        yield started
        for posture in started.values():
            assert posture.child.interrupt() == 0, posture.child.stderr_text()
    finally:
        for posture in started.values():
            posture.child.kill()


def _alike(postures, method: str, path: str, body=None) -> list[_Answer]:
    """The same request, to both postures: each an answer, and equal."""
    answers = [postures[name].ask(method, path, body) for name in POSTURES]
    for name, answer in zip(POSTURES, answers):
        assert not answer.dropped, f"{method} {path} dropped the connection ({name})"
        assert answer.reached == (), f"{method} {path} reached {answer.reached} ({name})"
    assert answers[0].comparable() == answers[1].comparable(), (method, path)
    return answers


def _a_refusal(answers, *, code: str | None = None) -> None:
    for answer in answers:
        assert 400 <= answer.status < 500, answer
        body = json.loads(answer.body)
        assert body.get("ok") is not True, body
        if code is not None:
            assert body["error"] == code, body


def _needs_t084(why: str):
    return pytest.mark.xfail(strict=True, reason=f"needs T084: {why}")


# ---- openDox's own settings documents are not the user's documents ----
#
# `opendox model-binding add` writes its bindings document INTO the checkout
# (`doxbench_binding.DEFAULT_BINDINGS_RELPATH`), where its operator can read and
# commit it. openDox's standalone corpus reads the working tree, so until T082
# that document joined the corpus as a `source` document, and every document,
# generation and view answer changed the moment a model was configured
# (measured at openDox-code#74 `9061b22a`). RULED by the holder, 2026-10-02,
# option (a): openDox's standalone corpus default, `WorkingTreeCorpus`, leaves
# out openDox's own settings documents, by exact path. Every assertion below is
# over the FULL listing, written out, with nothing subtracted from it.

#: A user's own documents under the same directory as the settings documents,
#: one of them with the bindings document's very file name. Each IS listed: the
#: rule names two paths, not a directory and not a file name.
_USER_DOCUMENTS_BESIDE_SETTINGS = (
    "ideation/dashboard/notes.md",
    "ideation/dashboard/archive/model-provider-bindings.yaml",
)


def _fixture_keys(*extra: str) -> list[str]:
    """The full listing a checkout of the fixture holds, plus `extra`."""
    return sorted([p.name for p in PLAIN.iterdir() if p.is_file()] + list(extra))


def _write(root: Path, relpath: str, text: str = "schema_version: 1\n") -> None:
    (root / relpath).parent.mkdir(parents=True, exist_ok=True)
    (root / relpath).write_text(text, encoding="utf-8")


def _commit_all(root: Path) -> str:
    from standalone_child import git
    git(root, "add", "-A")
    git(root, "commit", "-qm", "settings and notes")
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


def _listed(adapter, root: Path, revision: str | None = None) -> list[str]:
    from opendox import corpus_adapter
    corpus = adapter.resolve(corpus_adapter.CorpusRef(
        name="home", location=str(root), revision=revision))
    return [d.key for d in adapter.list_documents(corpus)]


def test_openDoxs_settings_documents_are_declared_once() -> None:
    """The two default paths, by their own constants, and the very tuple the
    standalone corpus's default reads."""
    import inspect
    from opendox.runtime import local_git_adapter as lga
    assert intake_mod.SETTINGS_DOCUMENTS == (binding_mod.DEFAULT_BINDINGS_RELPATH,
                                             intake_mod.DEFAULT_DECLARATIONS_RELPATH)
    default = inspect.signature(lga.WorkingTreeCorpus).parameters["excluded"].default
    assert default is intake_mod.SETTINGS_DOCUMENTS


@pytest.mark.parametrize("entry", ["opendox.cli", "opendox.serve"])
def test_the_standalone_corpus_lists_neither_settings_document(entry, tmp_path) -> None:
    """Through each entry point's own default home factory: the bindings
    document `model-binding add` writes, and the declarations document, are
    not listed, untracked or COMMITTED, nor at a pinned revision. A user's
    documents beside them are."""
    import importlib
    factory = importlib.import_module(entry)._default_home_factory
    root = fresh_repository(PLAIN, tmp_path)
    _declare(root)
    _write(root, intake_mod.DEFAULT_DECLARATIONS_RELPATH)
    for relpath in _USER_DOCUMENTS_BESIDE_SETTINGS:
        _write(root, relpath, "title: mine\nsummary: a note of my own\n")
    adapter, _ref = factory(root)
    expected = _fixture_keys(*_USER_DOCUMENTS_BESIDE_SETTINGS)
    assert _listed(adapter, root) == expected, "untracked"
    head = _commit_all(root)
    tracked = subprocess.run(["git", "-C", str(root), "ls-files"], check=True,
                             capture_output=True, text=True).stdout.split()
    assert binding_mod.DEFAULT_BINDINGS_RELPATH in tracked
    assert _listed(adapter, root) == expected, "committed"
    assert _listed(adapter, root, head) == expected, "at a pinned revision"


def test_a_whole_corpus_check_names_only_what_the_corpus_lists(tmp_path) -> None:
    """A committed bindings document, edited after the commit, is not reported
    by a whole-corpus check, since the corpus does not list it. A user's
    edited document beside it is reported, and the bindings document is
    reported when a caller names it (Copilot at openDox-code#76,
    r4170556938)."""
    from opendox import corpus_adapter
    from opendox.runtime import local_git_adapter as lga
    root = fresh_repository(PLAIN, tmp_path)
    _declare(root)
    _write(root, _USER_DOCUMENTS_BESIDE_SETTINGS[0], "title: mine\nsummary: v1\n")
    _commit_all(root)
    bindings = root / binding_mod.DEFAULT_BINDINGS_RELPATH
    bindings.write_text(bindings.read_text(encoding="utf-8") + "# edited\n",
                        encoding="utf-8")
    _write(root, _USER_DOCUMENTS_BESIDE_SETTINGS[0], "title: mine\nsummary: v2\n")
    adapter = lga.WorkingTreeCorpus()
    corpus = adapter.resolve(corpus_adapter.CorpusRef(name="home", location=str(root)))
    assert [f.subject for f in adapter.check(corpus)] == [
        _USER_DOCUMENTS_BESIDE_SETTINGS[0]]
    named = (corpus_adapter.DocumentId(corpus="home",
                                       key=binding_mod.DEFAULT_BINDINGS_RELPATH),)
    assert [f.subject for f in adapter.check(corpus, named)] == [
        binding_mod.DEFAULT_BINDINGS_RELPATH]


def test_a_corpus_told_to_leave_out_nothing_lists_every_file(tmp_path) -> None:
    from opendox.runtime import local_git_adapter as lga
    root = fresh_repository(PLAIN, tmp_path)
    _declare(root)
    assert _listed(lga.WorkingTreeCorpus(excluded=()), root) == _fixture_keys(
        binding_mod.DEFAULT_BINDINGS_RELPATH)


# ---- documents ----

@pytest.mark.parametrize(("method", "path", "body"), [
    ("GET", "/snapshot.json", None),
    ("GET", f"/source/{_DOCUMENT}", None),
    ("GET", f"/source/fixture@main/{_DOCUMENT}", None),
    ("GET", "/source", None),                                  # refused alike
    ("POST", "/actions/edit",                                  # select-to-edit
     {"path": _DOCUMENT, "repository": "fixture", "ref": "main"}),
], ids=["snapshot", "source", "keyed-source", "bare-source", "select-to-edit"])
def test_documents_answer_alike(postures, method, path, body) -> None:
    _alike(postures, method, path, body)


# ---- generation ----

def test_generation_answers_alike(postures, tmp_path) -> None:
    """The `generate` verb, run over each checkout as a lone openDox, writes the
    same snapshot, and it is the one each posture serves."""
    written = []
    for name in POSTURES:
        output = tmp_path / f"{name.replace(' ', '-')}.json"
        child, status = run_module(tmp_path / f"generate-{name.replace(' ', '-')}",
                                   "opendox.cli", "generate",
                                   "--repo-root", str(postures[name].repo),
                                   "--repository", "fixture", "--output", str(output))
        assert status == 0, child.stderr_text()
        assert child.refused() == [], child.refused()
        written.append(output.read_bytes())
    assert written[0] == written[1]
    served = _alike(postures, "GET", "/snapshot.json")
    assert json.loads(served[0].body) == json.loads(written[0])


# ---- the views ----

@pytest.mark.parametrize("path", [
    "/index.html", "/app.js", "/styles.css", "/views/display.js",
    "/views/wheel.js", "/views/wheel-model.js", "/views/doc-wheel.js",
    "/views/lens.js", "/views/lens-model.js", "/capabilities",
])
def test_the_views_are_served_alike(postures, path) -> None:
    _alike(postures, "GET", path)


_VIEW_MODELS = r"""
const W = await import(process.argv[2]);
const L = await import(process.argv[3]);
const snapshot = JSON.parse(await new Promise((resolve) => {
  let text = ""; process.stdin.on("data", (c) => { text += c; });
  process.stdin.on("end", () => resolve(text));
}));
process.stdout.write(JSON.stringify({
  wheel: W.buildWheelModel(snapshot),
  lens: L.buildLensModel(snapshot, ""),
  documents: L.docSummaries(snapshot),
}));
"""


def test_the_wheel_and_the_lens_render_alike(postures, tmp_path) -> None:
    """The wheel's and the lens's view-models, built by the browser's own
    modules from what each posture serves, are equal."""
    if NODE is None:
        pytest.skip("node not available for the wheel and lens models")
    views = ROOT / "src" / "opendox" / "web" / "views"
    script = tmp_path / "view-models.mjs"
    script.write_text(_VIEW_MODELS, encoding="utf-8")
    models = []
    for answer in _alike(postures, "GET", "/snapshot.json"):
        done = subprocess.run(
            [NODE, str(script), (views / "wheel-model.js").as_uri(),
             (views / "lens-model.js").as_uri()],
            input=answer.body.decode("utf-8"), capture_output=True, text=True,
            timeout=60)
        assert done.returncode == 0, done.stderr
        models.append(json.loads(done.stdout))
    assert models[0]["wheel"]["wheels"], "the wheel built no reel"
    assert models[0] == models[1]


# ---- sessions ----

@pytest.mark.parametrize("verb", ["share-session", "abandon-session", "open-pr"])
def test_a_session_verb_is_refused_alike_and_writes_nothing(postures, verb) -> None:
    """With no session there is nothing to share, abandon or open a pull
    request for: each verb is refused alike, and neither checkout changes."""
    before = [postures[name].checkout() for name in POSTURES]
    _a_refusal(_alike(postures, "POST", f"/actions/gate/{verb}", {}))
    assert [postures[name].checkout() for name in POSTURES] == before


_THREAD = ("/workbench/thread?repository=fixture&ref=main&tile_kind=staged"
           f"&tile_id=notes-rain-barrel-leak&document={_DOCUMENT}")


@pytest.mark.parametrize(("path",), [
    pytest.param("/project-register.json", marks=_needs_t084(
        "the project register's openxdox reach (serve_project.py:271) answers "
        "through its seam")),
    pytest.param(_THREAD, marks=_needs_t084(
        "the thread read's openxdox scope reach (serve_workbench.py:560) answers "
        "through the doxBench scope seam")),
], ids=["project-register", "thread"])
def test_a_session_read_answers_alike(postures, path) -> None:
    _alike(postures, "GET", path)


@_needs_t084("capability honesty (5920216845 item 1): standalone, actions.gate and "
             "actions.refresh read false, so the session controls are hidden")
def test_the_session_controls_are_hidden_alike(postures) -> None:
    for answer in _alike(postures, "GET", "/capabilities"):
        actions = json.loads(answer.body)["actions"]
        assert actions["gate"] is False and actions["refresh"] is False, actions


# ---- saving ----

@pytest.mark.parametrize("verb", ["first-edit", "edit-document", "create-document"])
def test_saving_is_refused_alike_and_writes_nothing(postures, verb) -> None:
    """Saving needs a live session, and standalone there is none (`5961651355`):
    each save verb is refused alike, and neither checkout changes."""
    before = [postures[name].checkout() for name in POSTURES]
    _a_refusal(_alike(postures, "POST", f"/actions/gate/{verb}",
                      {"path": _DOCUMENT, "content": "# changed\n"}))
    assert [postures[name].checkout() for name in POSTURES] == before


# ---- the model's own settings surfaces, which answer alike too ----

def test_intake_is_not_offered_alike(postures) -> None:
    """`5961364221` item 1: standalone, the intake surface answers `offered:
    false` with the reason, whether or not a binding is declared."""
    from opendox import doxbench_intake
    for answer in _alike(postures, "GET", "/workbench/model-intake"):
        surface = json.loads(answer.body)
        assert surface["offered"] is False, surface
        assert surface["reason"] == doxbench_intake.NO_BROKER_NOTICE, surface


@_needs_t084("model approval (serve_workbench.py:1231) answers the gate seam's named "
             "refusal standalone (5961364221 item 1)")
def test_model_approval_is_refused_alike_and_writes_nothing(postures) -> None:
    before = [postures[name].checkout() for name in POSTURES]
    _a_refusal(_alike(postures, "POST", "/actions/workbench/model-approval",
                      {"binding": "a-provider"}))
    assert [postures[name].checkout() for name in POSTURES] == before


@_needs_t084("the document abstract's openxdox reach (serve_workbench.py:2640) moves "
             "below its step-one check, which refuses once actions.gate reads false")
def test_the_document_abstract_is_refused_alike(postures) -> None:
    _a_refusal(_alike(postures, "POST", "/actions/workbench/document-abstract", {}),
               code=serve_wire.DOXBENCH_ERR_MODEL_CAPABILITY_UNAVAILABLE)
