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
   `403 model_capability_unavailable`.
5. THE CHAT RAIL. Mounted over an empty catalog with no intake flow, the rail
   shows "No model configured" and how to configure one, visibly and before
   any turn, while the send button keeps its existing sentence byte for byte.
   The line shows in that state only. Its spelling is held to the Python
   twin's.

`omp` is `doxbench_bridge.HARNESS_COMMAND`. A case that means "no harness"
says so with `harness_present=lambda: False`, or with a PATH holding no `omp`,
and asserts it.

Plan 034's T082 adds 16.5 here (every other surface, with no model), and
T078–T080 add the configured turn over a stand-in OpenAI-compatible server.
F16.1's last line runs this file whole once all of them have landed (T083).

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from opendox import doxbench_binding as binding_mod
from opendox import doxbench_bridge as bridge_mod
from opendox import doxbench_install as inst
from opendox import doxbench_intake as intake_mod
from opendox import doxbench_model
from opendox import serve_wire
from opendox import validator as own
from opendox.serve_workbench import WorkbenchRoutes
from session_fixtures import GATE_TEST_PRINCIPALS
from standalone_child import Child, fresh_repository

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


def test_a_turn_is_refused_model_capability_unavailable(standalone) -> None:
    """A schema-valid turn, which no rail sends with no model selected but any
    client can, is refused with the fixed code and the contract's failure
    envelope, and the child spawns no harness (none is on its PATH, and the
    no-model port spawns nothing)."""
    base, token, _child = standalone
    request = yaml.safe_load(
        (EXAMPLES / "workbench-chat-turn-v2-loaded-set.example.yaml").read_text(
            encoding="utf-8"))
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
    this.disabled = false; this.value = '';
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join('');
  }
  set textContent(value) { this.children = []; this._text = String(value); }
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

async function mount(catalog, { intake = null } = {}) {
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
  const loading = shown();
  release();
  await rail.ready;
  if (intake !== null) rail.intakeOffer(intake);
  const send = byClass(host, "doxchat-send")[0];
  return { loading, shown: shown(), exists: Boolean(line()), turns,
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
  // the pure verdict over states a mount does not reach in one shot: a
  // failure recorded beside an adopted empty catalog keeps its own remedy
  pure: {
    emptyAdopted: noModelConfiguredRemedy({ models: [], catalogFailure: null }),
    emptyThenUnreadable: noModelConfiguredRemedy(
      { models: [], catalogFailure: "unreadable" }),
    emptyThenStaleToken: noModelConfiguredRemedy(
      { models: [], catalogFailure: "console_required" }),
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


def test_a_catalog_of_unavailable_entries_is_no_model_too(rail) -> None:
    assert rail["onlyUnavailable"]["shown"] == doxbench_model.NO_MODEL_CONFIGURED_REMEDY


def test_the_line_shows_in_that_state_only(rail) -> None:
    """Not while the catalog is loading (nothing is known yet), not with a
    model available, not when the catalog could not be read (that has its
    own remedy), and not where the intake flow is offered (its option is the
    remedy's home)."""
    for case in ("empty", "onlyUnavailable", "available", "unreadable", "intakeOffered"):
        assert rail[case]["exists"] is True, case
        assert rail[case]["loading"] is None, case
    assert rail["available"]["shown"] is None
    assert rail["unreadable"]["shown"] is None
    assert rail["intakeOffered"]["shown"] is None
    assert rail["pure"] == {"emptyAdopted": doxbench_model.NO_MODEL_CONFIGURED_REMEDY,
                            "emptyThenUnreadable": None, "emptyThenStaleToken": None}
