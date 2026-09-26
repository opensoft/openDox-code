"""The two doxBench SEAMS: the schema validators and the status-exemption rail
(`add-neutral-product-standalone-operability` task 4.3; plan 034 task T027).

Two of the eight deferred reaches into the publisher that #1144's F4.1 scan
names, both into openxFactory's `ideation_dashboard` package, at `1e4a57fb`:

  * `serve_wire.py:1369`, `default_doxbench_validators`, which imported
    `ideation_dashboard.doxbench_contracts` for the doxBench schema
    validators; and
  * `doxbench_packet.py:177`, `_status_exemption`, which imported
    `ideation_dashboard.doxbench_status_exemption`, the `Status:` read the
    packet assembler's exemption rail marks sources with.

Each is now a SEAM a host fills with one registration at process start, and
each FAILS CLOSED, naming itself and its registration call, when nothing is
registered (4.2's discipline, requirement 5's third scenario). openxFactory
registers its own (plan 034's T046). openDox's standalone defaults are T085's.

WHAT IT ASSERTS, FOR EACH SEAM

1. NOTHING REGISTERED REFUSES, AND THE REFUSAL NAMES ITS REMEDY. The assertion
   is on the refusal's class and its words, because the reach it replaced
   ALSO failed where the package was absent. Only the named seam tells the
   two apart.
2. THE FAILURE STAYS CLOSED WHERE IT IS CAUGHT. The model routes' own
   resolver turns the validators' refusal into no validators, so the routes
   refuse with their fixed codes. The packet assembler refuses to assemble,
   and the rail's names on the module answer `AttributeError`, so
   `hasattr` stays honest.
3. AN IMPORTABLE `ideation_dashboard` IS NOT REACHED. A booby-trapped package
   is put in `sys.modules`, and nothing touches it.
4. A REGISTERED IMPLEMENTATION ANSWERS THROUGH THE SEAM: the factory per call,
   never cached; the rail's names as the rail's own objects, and the packet's
   sources marked by the rail's own verdicts.
5. THE REGISTRATION DISCIPLINE: one registration, idempotent for the same
   object, refused for a different one, and a rail that could not mark a
   source is refused when it is registered.
6. THE STATIC HALF: the seams' functions make no deferred reach into the
   publisher or the consumer, read by `ast` the way F4.1's scan reads the
   whole package.

`--noconftest` SAFE, like every file `validate` runs today. It imports
`opendox.serve_wire`, `opendox.serve_workbench` and `opendox.doxbench_packet`,
which import with no sibling present, and neither `opendox.serve` nor
`opendox.cli` (plan 034, tasks.md § Phase 1: those two modules do not import
in a lone checkout until T011 lands).

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

from opendox import doxbench_packet as pk
from opendox import serve_wire
from opendox import serve_workbench
from opendox.doxbench_scope_types import ScopeKey, ScopeProjection

#: #1144 task 4.3's F4.1 scan, word for word: the four packages no deferred
#: reach in openDox may name.
FOREIGN = ("openxdox", "ideation_dashboard", "corpus_adapter_openxfactory",
           "doc_health")

#: Each seam's own functions, and the readers that resolve through it.
VALIDATOR_SEAM_FUNCTIONS = (
    "register_doxbench_validators", "unregister_doxbench_validators",
    "doxbench_validators_registered", "default_doxbench_validators")
RAIL_SEAM_FUNCTIONS = (
    "register_status_exemption", "unregister_status_exemption",
    "status_exemption_registered", "_status_exemption", "exemption_rail",
    "__getattr__")

#: The two modules the replaced reaches imported, and their parent package.
IDEATION_DASHBOARD_MODULES = (
    "ideation_dashboard", "ideation_dashboard.doxbench_contracts",
    "ideation_dashboard.doxbench_status_exemption")

SCOPE = ScopeKey(repository="plain-repo", ref="main", tile_kind="staged",
                 tile_id="a-topic")
EVIDENCE_REF = "notes/evidence.md"
EXEMPT_TEXT = "Status: kept\n\nEXEMPT-ME: the stand-in rail exempts this.\n"


@pytest.fixture(autouse=True)
def _empty_seams():
    """Every test starts with NOTHING registered at either seam, and puts back
    what it found.

    Both seams are process-global by design (ONE registration each, for the
    process), so a teardown that only unregistered would strip a registration
    some other part of the process made at its start.

    Read through `getattr` with a default, so that against a tree WITHOUT the
    seams each test fails on its own assertion rather than all of them erroring
    here, which is what makes this file's red run legible."""
    found = {
        "validators": (serve_wire, "_doxbench_validators_factory",
                       "unregister_doxbench_validators",
                       "register_doxbench_validators"),
        "rail": (pk, "_status_exemption_rail", "unregister_status_exemption",
                 "register_status_exemption"),
    }
    previous = {key: getattr(module, slot, None)
                for key, (module, slot, _u, _r) in found.items()}
    for module, _slot, unregister, _register in found.values():
        getattr(module, unregister, lambda: None)()
    yield
    for key, (module, _slot, unregister, register) in found.items():
        getattr(module, unregister, lambda: None)()
        if previous[key] is not None:
            getattr(module, register)(previous[key])


class _TrapModule(types.ModuleType):
    """A module that records every non-dunder attribute anybody asks it for."""

    def __init__(self, name: str, touched: list[str]) -> None:
        super().__init__(name)
        self.__dict__["_touched"] = touched
        self.__path__ = []          # a package, so its submodules can be imported

    def __getattr__(self, attr: str):
        if not attr.startswith("__"):
            self._touched.append(f"{self.__name__}.{attr}")
        raise AttributeError(attr)


@pytest.fixture
def trapped_ideation_dashboard(monkeypatch) -> list[str]:
    """`ideation_dashboard` and both modules the replaced reaches imported,
    importable and booby-trapped. Returns the list of what was touched."""
    touched: list[str] = []
    for name in IDEATION_DASHBOARD_MODULES:
        monkeypatch.setitem(sys.modules, name, _TrapModule(name, touched))
    return touched


def _projection(*context_paths: str) -> ScopeProjection:
    return ScopeProjection(
        key=SCOPE, title="a topic", keywords=(), source_revision="rev-1",
        sections=(), context_paths=tuple(context_paths), editable_paths=(),
        outline_path=None, active_document_candidates=())


class _Knowledge:
    """A stand-in knowledge boundary that finds one evidence source."""

    class _Profile:
        profile_id = "stand-in-retrieval"

    class _Hit:
        def __init__(self, ref: str) -> None:
            self.ref = ref

    class _Source:
        def __init__(self, text: str) -> None:
            self.text = text

    def profile(self):
        return self._Profile()

    def search(self, query, *, confined_to, limit, thread_signals):
        return [self._Hit(EVIDENCE_REF)] if EVIDENCE_REF in confined_to else []

    def get_source(self, ref, *, confined_to):
        return self._Source(EXEMPT_TEXT)


class _StandInRail:
    """A host's rail, at the names the packet module reads, and one more."""

    EXEMPT_STATUSES = frozenset({"kept"})

    def __init__(self) -> None:
        self.read: list[str] = []

    def lifecycle_status(self, text: str) -> str | None:
        self.read.append(text)
        return "stand-in: kept" if "EXEMPT-ME" in text else None

    def is_compression_exempt(self, text: str) -> bool:
        return "EXEMPT-ME" in text


def _evidence(text: str = EXEMPT_TEXT) -> pk.PacketSource:
    return pk.PacketSource(ref=EVIDENCE_REF, kind=pk.SOURCE_EVIDENCE, text=text,
                           status=None, compression_exempt=False)


# ==========================================================================
# THE doxBench SCHEMA-VALIDATORS SEAM (`serve_wire.py:1369` at 1e4a57fb)
# ==========================================================================

def test_with_nothing_registered_the_default_factory_refuses_naming_the_seam():
    assert serve_wire.doxbench_validators_registered() is False
    with pytest.raises(serve_wire.DoxbenchValidatorsNotRegistered) as refused:
        serve_wire.default_doxbench_validators()
    message = str(refused.value)
    assert message == serve_wire.DOXBENCH_VALIDATORS_NOT_REGISTERED
    assert "doxBench-validators seam" in message
    assert "opendox.serve_wire.register_doxbench_validators(" in message
    # ...and not the reach it replaced, which failed on a missing module.
    assert not isinstance(refused.value, ImportError)
    assert "ideation_dashboard" not in message


def test_the_model_routes_resolver_turns_the_refusal_into_no_validators():
    """`build_server` binds `default_doxbench_validators` as the handler's
    `schema_validator_factory`, and the model routes read it through
    `WorkbenchRoutes._doxbench_validators`, which answers None on any factory
    failure, so both routes refuse with their fixed codes. Driven here on a
    stand-in handler, because `opendox.serve` does not import before T011."""
    handler = types.SimpleNamespace(
        schema_validator_factory=serve_wire.default_doxbench_validators)
    assert serve_workbench.WorkbenchRoutes._doxbench_validators(handler) is None


def _outcome(call):
    """What `call()` raised, or None: taken whole, so that what it TOUCHED is
    asserted first and a reach shows as the reach rather than as its crash."""
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - the caller asserts on it
        return exc
    return None


def test_an_importable_ideation_dashboard_is_never_reached_by_the_validators(
        trapped_ideation_dashboard):
    outcome = _outcome(serve_wire.default_doxbench_validators)
    assert trapped_ideation_dashboard == [], (
        f"the validators reached the publisher's package: "
        f"{trapped_ideation_dashboard}")
    assert isinstance(outcome, serve_wire.DoxbenchValidatorsNotRegistered)


def test_a_registered_factory_answers_per_call_and_is_never_cached():
    calls: list[int] = []
    released = {"workbench-model-catalog": object()}

    def factory():
        calls.append(1)
        return released

    assert serve_wire.register_doxbench_validators(factory) is factory
    assert serve_wire.doxbench_validators_registered() is True
    assert serve_wire.default_doxbench_validators() is released
    assert serve_wire.default_doxbench_validators() is released
    assert len(calls) == 2, "the factory runs per request, so a repin is seen"

    handler = types.SimpleNamespace(
        schema_validator_factory=serve_wire.default_doxbench_validators)
    assert serve_workbench.WorkbenchRoutes._doxbench_validators(handler) is released


def test_a_registered_factorys_own_failure_reaches_the_caller_unchanged():
    class PinError(Exception):
        pass

    def factory():
        raise PinError("the pinned contract could not be read")

    serve_wire.register_doxbench_validators(factory)
    with pytest.raises(PinError):
        serve_wire.default_doxbench_validators()
    handler = types.SimpleNamespace(
        schema_validator_factory=serve_wire.default_doxbench_validators)
    assert serve_workbench.WorkbenchRoutes._doxbench_validators(handler) is None


@pytest.mark.parametrize("not_a_factory", [None, {"kind": "validator"}, 3])
def test_only_a_callable_factory_can_be_registered(not_a_factory):
    with pytest.raises(TypeError, match="takes the host's validators factory"):
        serve_wire.register_doxbench_validators(not_a_factory)
    assert serve_wire.doxbench_validators_registered() is False


def test_one_validators_registration():
    def first():
        return {"first": object()}

    def second():
        return {"second": object()}

    serve_wire.register_doxbench_validators(first)
    assert serve_wire.register_doxbench_validators(first) is first
    with pytest.raises(serve_wire.DoxbenchValidatorsAlreadyRegistered) as refused:
        serve_wire.register_doxbench_validators(second)
    assert "opendox.serve_wire.unregister_doxbench_validators()" in str(
        refused.value)
    assert set(serve_wire.default_doxbench_validators()) == {"first"}

    serve_wire.unregister_doxbench_validators()
    assert serve_wire.doxbench_validators_registered() is False
    with pytest.raises(serve_wire.DoxbenchValidatorsNotRegistered):
        serve_wire.default_doxbench_validators()


# ==========================================================================
# THE STATUS-EXEMPTION SEAM (`doxbench_packet.py:177` at 1e4a57fb)
# ==========================================================================

def test_with_nothing_registered_the_rail_refuses_naming_the_seam():
    assert pk.status_exemption_registered() is False
    with pytest.raises(pk.StatusExemptionNotRegistered) as refused:
        pk.exemption_rail((_evidence(),))
    message = str(refused.value)
    assert message == pk.STATUS_EXEMPTION_NOT_REGISTERED
    assert "status-exemption seam" in message
    assert "opendox.doxbench_packet.register_status_exemption(" in message
    assert EXEMPT_TEXT not in message, "a packet refusal discloses no content"
    # A PACKET refusal, so a caller that maps packet refusals to a fixed code
    # maps this one too; and not the reach it replaced.
    assert isinstance(refused.value, pk.PacketError)
    assert not isinstance(refused.value, ImportError)
    assert "ideation_dashboard" not in message


def test_with_nothing_registered_no_packet_is_assembled():
    """The rail runs inside the assembler, so a packet with no reader for its
    sources' `Status:` is refused rather than assembled with every source
    unmarked. The reduced posture too: it is the same pipeline."""
    with pytest.raises(pk.StatusExemptionNotRegistered):
        pk.assemble_packet(projection=_projection(EVIDENCE_REF), scope=SCOPE,
                           selected_key=None, loaded_keys=(), query="evidence",
                           knowledge=_Knowledge(), clock=lambda: 100.0)
    with pytest.raises(pk.StatusExemptionNotRegistered):
        pk.reduced_packet(projection=_projection(), scope=SCOPE,
                          selected_key=None, loaded_keys=(),
                          clock=lambda: 100.0)


@pytest.mark.parametrize("name", sorted(pk._STATUS_EXEMPTION_NAMES))
def test_with_nothing_registered_the_rails_names_are_an_honest_attribute_error(name):
    with pytest.raises(AttributeError) as raised:
        getattr(pk, name)
    assert name in str(raised.value)
    assert "status-exemption seam" in str(raised.value)
    assert isinstance(raised.value.__cause__, pk.StatusExemptionNotRegistered)
    # The whole point: hasattr and getattr-with-default degrade, not raise.
    assert hasattr(pk, name) is False
    assert getattr(pk, name, "default") == "default"


def test_an_importable_ideation_dashboard_is_never_reached_by_the_rail(
        trapped_ideation_dashboard):
    outcome = _outcome(lambda: pk.exemption_rail((_evidence(),)))
    probed = _outcome(lambda: getattr(pk, "lifecycle_status"))
    assert trapped_ideation_dashboard == [], (
        f"the rail reached the publisher's package: {trapped_ideation_dashboard}")
    assert isinstance(outcome, pk.StatusExemptionNotRegistered)
    assert isinstance(probed, AttributeError)


def test_a_registered_rail_marks_the_packets_sources():
    rail = _StandInRail()
    assert pk.register_status_exemption(rail) is rail
    assert pk.status_exemption_registered() is True

    (marked,) = pk.exemption_rail((_evidence(),))
    assert (marked.status, marked.compression_exempt) == ("stand-in: kept", True)
    (plain,) = pk.exemption_rail((_evidence("Status: other\n\nordinary\n"),))
    assert (plain.status, plain.compression_exempt) == (None, False)

    packet = pk.assemble_packet(
        projection=_projection(EVIDENCE_REF), scope=SCOPE, selected_key=None,
        loaded_keys=(), query="evidence", knowledge=_Knowledge(),
        clock=lambda: 100.0)
    (evidence,) = packet.of_kind(pk.SOURCE_EVIDENCE)
    assert (evidence.status, evidence.compression_exempt) == ("stand-in: kept", True)
    assert EXEMPT_TEXT in rail.read


def test_the_rails_names_answer_as_the_registered_rails_own_objects():
    rail = _StandInRail()
    pk.register_status_exemption(rail)
    assert pk.lifecycle_status == rail.lifecycle_status
    assert pk.is_compression_exempt == rail.is_compression_exempt
    assert pk.EXEMPT_STATUSES is rail.EXEMPT_STATUSES
    # A module registered as the rail answers its names by identity, which is
    # how openxFactory's own module is read through this one.
    module = types.ModuleType("a_hosts_rail")
    module.lifecycle_status = rail.lifecycle_status
    module.is_compression_exempt = rail.is_compression_exempt
    pk.unregister_status_exemption()
    pk.register_status_exemption(module)
    assert pk.lifecycle_status is module.lifecycle_status


def test_a_name_the_registered_rail_does_not_carry_is_an_attribute_error():
    pk.register_status_exemption(_StandInRail())
    with pytest.raises(AttributeError) as raised:
        pk._STATUS_RE
    assert "_STATUS_RE" in str(raised.value)
    assert hasattr(pk, "status_word") is False
    # A name outside the rail's seven is this module's own ordinary refusal.
    with pytest.raises(AttributeError) as ordinary:
        pk.definitely_not_a_packet_name
    assert "doxbench_packet" in str(ordinary.value)
    assert "status-exemption" not in str(ordinary.value)


def test_a_rail_whose_lazy_load_fails_is_an_attribute_error_too():
    """The refusal this module translated when it imported the rail by name,
    kept for a rail that loads what it reads on first use."""
    class _LazyRail(_StandInRail):
        def __getattr__(self, name):
            raise ModuleNotFoundError(f"No module named 'a_hosts_{name}'")

    pk.register_status_exemption(_LazyRail())
    with pytest.raises(AttributeError) as raised:
        pk.STATUS_SCAN_LINES
    assert isinstance(raised.value.__cause__, ModuleNotFoundError)
    assert hasattr(pk, "STATUS_SCAN_LINES") is False


@pytest.mark.parametrize("not_a_rail", [
    None, object(), types.SimpleNamespace(lifecycle_status=lambda text: None),
    types.SimpleNamespace(lifecycle_status="ratified",
                          is_compression_exempt=lambda text: False),
])
def test_a_rail_that_could_not_mark_a_source_is_refused_when_registered(not_a_rail):
    with pytest.raises(TypeError, match="takes the host's status-exemption rail"):
        pk.register_status_exemption(not_a_rail)
    assert pk.status_exemption_registered() is False


def test_one_rail_registration():
    first, second = _StandInRail(), _StandInRail()
    pk.register_status_exemption(first)
    assert pk.register_status_exemption(first) is first
    with pytest.raises(pk.StatusExemptionAlreadyRegistered) as refused:
        pk.register_status_exemption(second)
    assert "opendox.doxbench_packet.unregister_status_exemption()" in str(
        refused.value)
    pk.exemption_rail((_evidence(),))
    assert first.read and not second.read

    pk.unregister_status_exemption()
    assert pk.status_exemption_registered() is False
    with pytest.raises(pk.StatusExemptionNotRegistered):
        pk.exemption_rail((_evidence(),))


# ==========================================================================
# THE STATIC HALF: no deferred reach in either seam
# ==========================================================================

def _named(node: ast.AST) -> list[str]:
    """F4.1's `named()`, word for word: every import, and every
    `import_module`/`__import__` call with a literal name."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.level == 0 and node.module else []
    if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
            and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("import_module", "__import__"):
        return [node.args[0].value] if isinstance(node.args[0].value, str) else []
    return []


def _foreign_reaches(module, function_names: tuple[str, ...]) -> list[str]:
    path = Path(module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    functions = {node.name: node for node in tree.body
                 if isinstance(node, ast.FunctionDef)}
    missing = [name for name in function_names if name not in functions]
    assert missing == [], f"the seam's functions are not in {path.name}: {missing}"
    return [f"{path.name}:{node.lineno}: {name}  [in {fn}]"
            for fn in function_names
            for node in ast.walk(functions[fn])
            for name in _named(node)
            if any(name == f or name.startswith(f + ".") for f in FOREIGN)]


@pytest.mark.parametrize("module,function_names", [
    (serve_wire, VALIDATOR_SEAM_FUNCTIONS),
    (pk, RAIL_SEAM_FUNCTIONS),
], ids=["serve_wire", "doxbench_packet"])
def test_neither_seam_reaches_the_publisher_or_the_consumer(module, function_names):
    hits = _foreign_reaches(module, function_names)
    assert hits == [], "a deferred reach into the publisher or the consumer:\n  " \
        + "\n  ".join(hits)


def test_the_static_check_would_catch_the_reaches_it_replaced():
    """The negative control, because the assertion above proves an ABSENCE.
    The two bodies these seams replaced, in their own words, are caught."""
    replaced = (
        "def default_doxbench_validators():\n"
        "    from ideation_dashboard import doxbench_contracts\n"
        "    return doxbench_contracts.validators()\n"
        "def _status_exemption():\n"
        "    import ideation_dashboard.doxbench_status_exemption as rail\n"
        "    return rail\n"
    )
    caught = [name for function in ast.parse(replaced).body
              for node in ast.walk(function) for name in _named(node)
              if any(name == f or name.startswith(f + ".") for f in FOREIGN)]
    assert caught == ["ideation_dashboard",
                      "ideation_dashboard.doxbench_status_exemption"]
