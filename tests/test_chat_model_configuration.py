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
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
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


def _no_omp_path(tmp_path: Path, path: str | None = None) -> str:
    """This process's PATH (or `path`) with `omp` taken out and EVERY OTHER
    COMMAND KEPT, in order. A directory holding `omp` is replaced by a mirror
    of it under `tmp_path`: a symlink to each of its other entries. Dropping
    the whole directory would drop whatever else it holds, `git` among them,
    and a child that cannot find `git` fails before the case it exists for
    (Copilot at openDox-code#74 9551f20d, r4170794383)."""
    harness = bridge_mod.HARNESS_COMMAND
    mirrors = Path(tempfile.mkdtemp(prefix="path-without-omp-", dir=tmp_path))
    kept = []
    for index, entry in enumerate(
            (os.environ.get("PATH", "") if path is None else path).split(os.pathsep)):
        if not entry:
            continue
        if shutil.which(harness, path=entry) is None:
            kept.append(entry)
            continue
        mirror = mirrors / str(index)
        mirror.mkdir()
        # ABSOLUTE targets: a relative PATH entry names a directory relative
        # to the current directory, and a relative link would resolve from
        # the mirror instead (Copilot at openDox-code#74 4ef7575a,
        # r4170839174).
        for item in sorted(Path(os.path.abspath(entry)).iterdir()):
            if item.name != harness:
                (mirror / item.name).symlink_to(item)
        kept.append(str(mirror))
    without = os.pathsep.join(kept)
    assert shutil.which(harness, path=without) is None
    return without


def test_a_path_without_omp_keeps_every_other_command(tmp_path) -> None:
    """A directory that holds `omp` beside another command keeps the other
    command, in its place in the order."""
    shared = tmp_path / "shared-bin"
    shared.mkdir()
    for name in (bridge_mod.HARNESS_COMMAND, "fixture-git"):
        tool = shared / name
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    path = os.pathsep.join([str(before), str(shared), str(after)])
    without = _no_omp_path(tmp_path, path).split(os.pathsep)
    assert len(without) == 3, "a directory holding omp was dropped whole"
    assert without[0] == str(before) and without[2] == str(after), without
    assert shutil.which(bridge_mod.HARNESS_COMMAND, path=os.pathsep.join(without)) is None
    found = shutil.which("fixture-git", path=os.pathsep.join(without))
    assert found is not None and Path(found).parent == Path(without[1]), found
    assert Path(found).resolve() == (shared / "fixture-git").resolve()


def test_a_relative_path_entry_without_omp_keeps_its_commands(
        tmp_path, monkeypatch) -> None:
    """A RELATIVE PATH entry holding `omp`: its other commands still resolve,
    from anywhere, to the same files."""
    shared = tmp_path / "shared-bin"
    shared.mkdir()
    for name in (bridge_mod.HARNESS_COMMAND, "fixture-git"):
        tool = shared / name
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    assert shutil.which("fixture-git", path="shared-bin") is not None
    without = _no_omp_path(tmp_path, "shared-bin")
    monkeypatch.chdir(ROOT)                      # a child's own directory
    assert shutil.which(bridge_mod.HARNESS_COMMAND, path=without) is None
    found = shutil.which("fixture-git", path=without)
    assert found is not None, without
    assert Path(found).resolve() == (shared / "fixture-git").resolve()


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
    # `--local`: the single-user install. Since plan 034 T070 an unflagged
    # `generate-and-open` is HOSTED, and with no issuer it refuses (13.5)
    # before it serves anything.
    child = Child(tmp_path, "opendox.cli", "generate-and-open", "--local",
                  "--repo-root", str(repo), "--repository", "fixture",
                  "--no-open", "--port", "0", "--run-dir", str(tmp_path / "run"),
                  "--actor", ACTOR)
    try:
        match = child.wait_for_line(_URL)
        base = (match.group(2), int(match.group(3)))
        status, capabilities = _request(base, "GET", "/capabilities")
        assert status == 200 and capabilities["actions"]["session"] is True
        # a standalone plane delivers its token through the private copy, and
        # never on `/capabilities` (plan 034 T104)
        assert "console_token" not in capabilities, sorted(capabilities)
        yield base, child.console_token(base[1]), child
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
    """A scope authority at openDox's scope seam (`opendox.column_seams.scope`,
    plan 034 T084), standing in for openDox's own default and for any host's:
    a scope that resolves, no live session, and no session-created path.
    Revalidation against that projection is a no-op here, so step 5's verdict
    is exactly the registry's: found, or not. The seam's state is restored
    exactly afterwards, so a default another case registered and read is put
    back as it was."""
    from opendox import column_seams
    seam = column_seams.scope
    held = (seam._registered, seam._is_default, seam._default_read)
    seam.unregister()
    seam.register(SimpleNamespace(
        resolve_scope=lambda *args, **kwargs: SimpleNamespace(),
        is_live_session_ref=lambda *args, **kwargs: False,
        session_created_paths_for_scope=lambda *args, **kwargs: ()))
    monkeypatch.setattr(doxbench_turns, "revalidate_scope", lambda **kwargs: None)
    try:
        yield
    finally:
        seam._registered, seam._is_default, seam._default_read = held


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
    the hoist, and a well-formed turn reaches step 7.

    The declared model factory runs AT MOST ONCE per turn: once where the
    turn reaches the model verdict, never where an earlier defect answers
    (Copilot at openDox-code#74 8104fa6e, r4170882125)."""
    payload, arguments = _defective(defect)
    port = _OfferingNothing()
    declared = (lambda: port) if posture == "a port" else _NO_PORT[posture]
    resolved = []

    def counted():
        resolved.append(posture)
        return declared()

    route = _TurnRoute(payload, root=tmp_path,
                       port_factory=None if declared is None else counted,
                       **arguments)
    route._handle_workbench_chat_turn()
    reaches_the_verdict = defect not in _BEFORE_THE_MODEL_VERDICT
    assert len(resolved) == (1 if reaches_the_verdict and declared is not None
                             else 0), (posture, defect, resolved)
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
