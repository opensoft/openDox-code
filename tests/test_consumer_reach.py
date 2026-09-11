"""The direction, asserted from openDox's side — BUILD slice 2.

openDox is the NEUTRAL product. openXdox pins it (`split-opendox` § 4.2, RULED
OQ-2) and openDox pins nothing back, so **a neutral openDox with no `openxdox`
installed is the normal case**, and a module of this package that cannot be
imported without one is the wrong-direction edge `design.md`:243 forbids:
*"What must not survive is the direction, not the calls."*

WHY THE TEST IS "DOES IT IMPORT" AND NOT "COUNT THE IMPORT STATEMENTS."
openXdox-code's `tests/test_dependency_direction.py` keeps a per-module RATCHET
over this repository's `openxdox` imports (`OPENDOX_BACK_IMPORTS`), measured by
AST over `ast.Import` / `ast.ImportFrom` nodes. That census is the right shape
for a consumer measuring a repository it does not write — and it has a blind
spot this slice found the hard way:

    def _candidates(..., records_dir: str = gate_console.DEFAULT_RECORDS_DIR):

A DEFAULT ARGUMENT is evaluated when the `def` executes, which is at import
time. Rewrite `from openxdox import gate_console` into a late-bound stand-in and
the census falls by one while the module still cannot be imported without
openXdox — the reach simply stops being an `Import` node. `branch_session.py`
(NINE such sites) and `serve.py` (2) are exactly that case, and both were
reverted out of slice 2 rather than shipped as a census that reads better than
the tree. (Slice 2 wrote "7" here and openXdox-code's ratchet file repeats it;
both are counted and corrected in slice 2b, because a number a later audit
reads off a comment is worth no more than the count behind it.) **So this file asserts the thing the census is a proxy for**: the module
imports, in a subprocess, with `openxdox` made unimportable.

BUILD SLICE 2b is what that reversion was waiting for: `defaults.py` gives
openDox its own spelling of the three values those eleven default-argument
sites read — `DEFAULT_RECORDS_DIR` at `branch_session.py`'s nine,
`DEFAULT_INDEX_NAME` and `PEEK_TTL_SECONDS` at `serve.py`'s two — so the reach
can be removed at the site rather than renamed at the import line, and `branch_session` moves from the recorded half to the asserted half
below. That move is the point of the second test: it FAILED on the slice-2b
commit that made the module importable, and this act is the answer it asked
for.

`--noconftest` safe and dependency-free: `.github/workflows/validate.yml` runs
this file beside `tests/test_leg_shape.py`, and the repository's root
`conftest.py` is not loaded for either.

A CREATED FILE with no manifest row (RULED OQ-C); it sits under a declared root
and is named to the arrival verifier as
`--allow-created tests/test_consumer_reach.py`.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

#: The package openDox must not require. Spelled once here rather than
#: imported from `opendox.consumer_reach`, because this file must hold even if
#: that module is the thing that broke.
CONSUMER_PACKAGE = "openxdox"

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PACKAGE = SRC / "opendox"

#: Blocks `openxdox` at the finder, whatever the environment has installed, so
#: the proof holds on a developer machine with openXdox-code on the path and in
#: CI where it is simply absent. A `sys.modules[...] = None` entry is the
#: documented way to make an import raise `ModuleNotFoundError` for a name.
_BLOCK_CONSUMER = """
import sys
sys.modules["openxdox"] = None
"""


def _import_in_subprocess(module: str, *, consumer_blocked: bool) -> subprocess.CompletedProcess:
    """`import <module>` in a fresh interpreter, with `openxdox` absent or not."""
    program = (_BLOCK_CONSUMER if consumer_blocked else "") + f"import {module}\n"
    return subprocess.run([sys.executable, "-c", textwrap.dedent(program)],
                          capture_output=True, text=True, cwd=str(ROOT))


# --------------------------------------------------------------------------
# 1 — the claim this slice actually makes
# --------------------------------------------------------------------------

#: Every module this slice converted to the late seam, and which therefore MUST
#: import with no consumer present. Adding a module here is the whole of the
#: claim a future slice makes; removing one is a regression that has to be
#: argued for on a pull request.
NEUTRAL_MODULES = (
    "opendox.workbench",
    "opendox.serve_workbench",
    "opendox.consumer_reach",
    # BUILD slice 2b. NINE default-argument reads of
    # `gate_console.DEFAULT_RECORDS_DIR` (:1740, :1859, :1878, :4179, :4217,
    # :4254, :4287, :4504, :4991) — evaluated where the `def` sits, so no
    # stand-in could defer them — now read `opendox.defaults`, which is
    # openDox's own spelling of a value openDox owns. openXdox-code's drift
    # guard holds the two spellings together. It is ONE constant at nine sites,
    # not two constants: `DEFAULT_BRANCH_PREFIX` is not reached from this
    # module and `defaults.py` does not carry it.
    "opendox.branch_session",
)

#: Modules that STILL require the consumer at import time, with the reason. They
#: are listed so the suite is a census of the whole surface rather than of its
#: good half, and each entry names what has to land for it to move up.
#:
#: Modules that still cannot be imported with the consumer blocked — with the
#: reason, and with the PACKAGE NAME whose absence is what actually stops them.
#:
#: THE SECOND FIELD IS SLICE 2b STEP 4's DOING, and it is the whole content of
#: this record now. Both remaining entries are blocked by `ideation_dashboard`,
#: NOT by `openxdox`: the consumer reaches that used to stop them are gone, and
#: what is left is the OTHER cross-column reach — openxFactory's PRE-CARVE
#: package name, a `stays_openxfactory_adapter` row (RULING DQ-1) present at
#: neither carve destination, censused two lines down at
#: `test_no_module_under_src_names_the_pre_carve_package_at_import_time` and
#: owed to a later act. Recording only "still reaching" would have let that
#: substitution pass unread: the test would stay green on a nonzero exit while
#: the thing it was written to measure had actually been fixed.
#:
#: So the test below now asserts the blocker BY NAME, and — for an entry whose
#: recorded blocker is not the consumer — asserts that `openxdox` is NOT what
#: the failure names. That turns each of these two rows from a placeholder into
#: a claim: *this module's consumer reach is gone; it waits on something else.*
STILL_REACHING = {
    "opendox.cli": ("cli.py itself no longer names the consumer at import time "
                    "(step 3), and opendox.serve no longer does either (step "
                    "4); it imports serve, and so inherits serve's remaining "
                    "pre-carve reach",
                    "ideation_dashboard"),
    "opendox.serve": ("serve.py's consumer reaches are gone (step 4): the two "
                      "mixin bases are late columns, the two build_server "
                      "defaults read opendox.defaults, and the registry and "
                      "re-export blocks are late bindings. What remains is "
                      "`from ideation_dashboard import serve_openxfactory_"
                      "lanes` at :181 and :199, whose rewrite target exists at "
                      "neither carve destination",
                      "ideation_dashboard"),
}


@pytest.mark.parametrize("module", NEUTRAL_MODULES)
def test_the_neutral_modules_import_with_no_consumer_installed(module: str) -> None:
    """openDox's own modules do not require the layer that pins openDox."""
    done = _import_in_subprocess(module, consumer_blocked=True)
    assert done.returncode == 0, (
        f"`import {module}` FAILED with `openxdox` unimportable, so openDox "
        f"still requires the layer that pins it:\n{done.stderr}\n"
        "openXdox pins openDox and openDox pins nothing back (split-opendox "
        "§ 4.2, RULED OQ-2): a neutral openDox must import with no consumer "
        "present. This is the assertion the openXdox-side per-module ratchet "
        "cannot make, because a default-argument reach is not an Import node")


@pytest.mark.parametrize("module", sorted(STILL_REACHING))
def test_the_reaching_modules_are_recorded_as_reaching(module: str) -> None:
    """The other half, recorded rather than asserted away — and it MUST fail.

    A module that starts importing is not a failure of this repository, it is
    a slice landing; the test then tells the author to move it into
    `NEUTRAL_MODULES`, which is where the claim is made. Recording it this way
    is what stops the list above from silently becoming a list of two.
    """
    _reason, blocker = STILL_REACHING[module]
    done = _import_in_subprocess(module, consumer_blocked=True)
    assert done.returncode != 0, (
        f"`import {module}` now SUCCEEDS with no `openxdox` — good, and the "
        f"record in this file is out of date. Move {module!r} from "
        "STILL_REACHING into NEUTRAL_MODULES in the same act, so the claim is "
        "asserted rather than merely no longer contradicted, and lower "
        "openXdox-code's OPENDOX_BACK_IMPORTS ratchet to the new census")
    # A NONZERO EXIT IS NOT THE CLAIM. A syntax error, a missing `yaml`, or
    # any other breakage would exit nonzero too and would sit here forever
    # being read as "still reaching" — a record that stays green by being
    # broken. So the failure must be the BLOCKED IMPORT and nothing else.
    last = done.stderr.strip().splitlines()[-1] if done.stderr.strip() else ""
    assert last.startswith(("ModuleNotFoundError", "ImportError")), (
        f"`import {module}` failed for a reason that is NOT a blocked import, "
        f"so this record is masking a defect:\n{done.stderr}")
    assert blocker in last, (
        f"`import {module}` raised an import error naming something other "
        f"than {blocker!r}, which is what this record says blocks it — a real "
        f"missing dependency, or a moved blocker, not a layering edge:\n"
        f"{done.stderr}")
    if blocker != CONSUMER_PACKAGE:
        # THE HALF THAT MADE THE SECOND FIELD NECESSARY. This row claims the
        # module's CONSUMER reach is gone and that it waits on something else.
        # Without this line the claim is untested: an `openxdox` reach could
        # come back on a line after the one that raises, and the row would go
        # on reading "still reaching" — true, but no longer about openXdox.
        assert CONSUMER_PACKAGE not in last, (
            f"`import {module}` is recorded as blocked by {blocker!r} with its "
            f"consumer reach removed, but the failure names "
            f"{CONSUMER_PACKAGE!r}:\n{done.stderr}")


# --------------------------------------------------------------------------
# 2 — the seam itself, exercised at run time
# --------------------------------------------------------------------------

def test_importing_the_seam_resolves_nothing() -> None:
    """Constructing a stand-in performs no import.

    The whole value of the module is that `import opendox.consumer_reach` is
    free; a stand-in that resolved eagerly would be an import statement wearing
    a different hat.
    """
    done = _import_in_subprocess("opendox.consumer_reach", consumer_blocked=True)
    assert done.returncode == 0, done.stderr


def test_first_attribute_access_refuses_naming_the_layering() -> None:
    from opendox import consumer_reach

    absent = consumer_reach.module("no_such_column", reason="a test's own")
    with pytest.raises(consumer_reach.ConsumerReachUnavailable) as caught:
        absent.anything
    message = str(caught.value)
    assert "openxdox.no_such_column" in message
    assert "RULED OQ-2" in message, (
        "the refusal must name the LAYERING — which way the pin runs — rather "
        "than reading as a missing-module accident")
    assert isinstance(caught.value.__cause__, ModuleNotFoundError), (
        "the original ModuleNotFoundError is chained, so a reader still gets "
        "the import machinery's own account beneath the layering one")


def test_a_consumer_module_that_exists_and_raises_is_re_raised_untouched() -> None:
    """`except ImportError` wholesale would blame the layering for a bug.

    A consumer module that IS present and fails while executing — because one
    of ITS dependencies is missing — must surface as that failure, not as
    `ConsumerReachUnavailable`, or the reader is sent to the wrong repository.
    """
    from opendox import consumer_reach

    reach = consumer_reach.module("cheerfully_broken", reason="a test's own")
    broken = ModuleNotFoundError("No module named 'jsonschema'", name="jsonschema")

    def _raise(_dotted: str):
        raise broken

    original = consumer_reach.importlib.import_module
    consumer_reach.importlib.import_module = _raise
    try:
        with pytest.raises(ModuleNotFoundError) as caught:
            reach.anything
    finally:
        consumer_reach.importlib.import_module = original
    assert caught.value is broken
    assert not isinstance(caught.value, consumer_reach.ConsumerReachUnavailable)


def test_resolution_forwards_to_the_real_module_and_caches(tmp_path: Path) -> None:
    from opendox import consumer_reach

    module_object = type(sys)("openxdox.pretend")
    module_object.ANSWER = 42
    module_object.verb = lambda x: x * 2
    reach = consumer_reach.module("pretend", reason="a test's own")
    sys.modules["openxdox.pretend"] = module_object
    # The fake PARENT is removed again below only if this test created it.
    # Leaving an empty `openxdox` package in `sys.modules` would make every
    # later test in the process see an importable-but-empty consumer instead
    # of normal import behaviour — including this file's own seam tests.
    parent_was_created = "openxdox" not in sys.modules
    if parent_was_created:
        sys.modules["openxdox"] = type(sys)("openxdox")
    try:
        assert reach.ANSWER == 42
        assert reach.resolve() is module_object
        assert reach.resolve() is module_object, "the resolved module is cached"
        assert consumer_reach.function(reach, "verb")(3) == 6, (
            "a late callable forwards arguments and the return value")
    finally:
        sys.modules.pop("openxdox.pretend", None)
        if parent_was_created:
            sys.modules.pop("openxdox", None)


def test_a_dunder_lookup_does_not_resolve_the_consumer() -> None:
    """`copy`, `pickle`, `inspect` and pytest all probe for dunders.

    Resolving openXdox because something asked for `__wrapped__` would fire the
    reach at a moment no verb chose — and, with the consumer absent, would turn
    an innocuous introspection into `ConsumerReachUnavailable`.
    """
    from opendox import consumer_reach

    reach = consumer_reach.module("never_resolved", reason="a test's own")
    with pytest.raises(AttributeError):
        reach.__wrapped__
    assert "unresolved" in repr(reach)


@pytest.fixture()
def pretend_corpus_root():
    """A stand-in for `openxdox.corpus_root` carrying a `SCANNED_ROOTS` tuple.

    Installed in `sys.modules` rather than imported, so the test holds on a
    machine with openXdox-code present and in CI where it is absent — and the
    fake PARENT is removed again only if this fixture created it, because
    leaving an empty `openxdox` package behind would make every later test in
    the process see an importable-but-empty consumer.
    """
    module_object = type(sys)("openxdox.corpus_root")
    module_object.SCANNED_ROOTS = ("contracts", "docs", "openspec")
    sys.modules["openxdox.corpus_root"] = module_object
    parent_was_created = "openxdox" not in sys.modules
    if parent_was_created:
        sys.modules["openxdox"] = type(sys)("openxdox")
    try:
        yield module_object
    finally:
        sys.modules.pop("openxdox.corpus_root", None)
        if parent_was_created:
            sys.modules.pop("openxdox", None)


def test_constructing_a_constant_resolves_nothing() -> None:
    """The laziness claim, made for the VALUE member of the family.

    `scanned_roots` is built at `consumer_reach` import time, in a package that
    must import with no consumer present. If construction resolved, the module
    that exists to remove import-time reaches would itself be one.
    """
    from opendox import consumer_reach

    absent = consumer_reach.constant(
        consumer_reach.module("no_such_column", reason="a test's own"), "ROOTS")
    assert "no_such_column.ROOTS" in repr(absent)
    assert "<late consumer value" in repr(absent), (
        "repr must not resolve either: a debugger, a logging call and pytest's "
        "own assertion rewriting all reach for it, and resolving there would "
        "fire the reach at a moment no verb chose")


def test_the_sequence_operations_a_re_exported_constant_meets(
        pretend_corpus_root) -> None:
    """Every operation `SCANNED_ROOTS` is actually subjected to, forwarded.

    `cli.py`:228 iterates it; the rest are what a re-exported sequence constant
    meets from a caller who believes it is still the tuple it was. The point of
    the assertions is that the stand-in is INDISTINGUISHABLE from the tuple at
    these operations — anything less and the name could not have been left in
    place on a line the carve manifest does not declare.
    """
    from opendox import consumer_reach

    roots = consumer_reach.constant(
        consumer_reach.module("corpus_root", reason="a test's own"),
        "SCANNED_ROOTS")
    real = pretend_corpus_root.SCANNED_ROOTS

    assert list(roots) == list(real), "iteration — cli.py:228's `for root in ...`"
    assert len(roots) == 3
    assert "docs" in roots
    assert "no-such-root" not in roots
    assert roots[0] == "contracts"
    assert roots[-1] == "openspec"
    assert list(roots[1:]) == ["docs", "openspec"], "slicing is indexing too"
    assert roots == real, "equality against the real tuple"
    assert not (roots != real)
    assert roots != ("something", "else")
    assert bool(roots) is True
    assert str(roots) == str(real)
    assert hash(roots) == hash(real), (
        "a constant re-exported into a set or a dict key must hash as its value")
    assert roots.resolve() is real


def test_a_constant_does_not_forward_attribute_reads(pretend_corpus_root) -> None:
    """`__getattr__` is deliberately absent — the refusal is part of the design.

    An attribute read on a constant is almost always a caller who wanted the
    MODULE, and answering it would turn the value stand-in into the general
    facade this module refuses to be. It must fail as an `AttributeError`, the
    way the tuple it stands for would.
    """
    from opendox import consumer_reach

    roots = consumer_reach.constant(
        consumer_reach.module("corpus_root", reason="a test's own"),
        "SCANNED_ROOTS")
    with pytest.raises(AttributeError):
        roots.corpus_root_refusal


def test_an_unavailable_consumer_refuses_at_the_operation_not_at_the_binding() -> None:
    """The error path, and WHERE it fires: at use, naming the layering.

    With no consumer installed the binding is still constructed — that is the
    whole point — so the refusal has to arrive at the first operation, and it
    has to name which way the pin runs rather than reading as a missing-module
    accident.
    """
    from opendox import consumer_reach

    absent = consumer_reach.constant(
        consumer_reach.module("no_such_column", reason="a test's own"), "ROOTS")

    for operation in (lambda: list(absent),
                      lambda: len(absent),
                      lambda: "x" in absent,
                      lambda: absent[0],
                      lambda: absent == ("x",),
                      lambda: absent != ("x",),
                      lambda: hash(absent),
                      lambda: bool(absent),
                      lambda: str(absent),
                      lambda: absent.resolve()):
        with pytest.raises(consumer_reach.ConsumerReachUnavailable) as caught:
            operation()
        message = str(caught.value)
        assert "openxdox.no_such_column" in message
        assert "RULED OQ-2" in message
        assert isinstance(caught.value.__cause__, ModuleNotFoundError)


@pytest.fixture()
def pretend_column():
    """A stand-in for a consumer module carrying one handler-method COLUMN.

    The methods are written the way the real columns are — plain functions on a
    class, called with the live request handler as `self` — so what the test
    exercises is the forwarding contract and not a mock's idea of it.
    """
    module_object = type(sys)("openxdox.pretend_routes")

    class PretendRoutes:
        def _serve_thing(self, path, *, keyed=False):
            # Reads state off `self`, which is the whole point: the forwarder
            # must pass the HANDLER, not the column, as `self`.
            return f"{self.marker}:{path}:{keyed}"

        def _refuse_thing(self):
            return f"{self.marker}:refused"

    module_object.PretendRoutes = PretendRoutes
    sys.modules["openxdox.pretend_routes"] = module_object
    parent_was_created = "openxdox" not in sys.modules
    if parent_was_created:
        sys.modules["openxdox"] = type(sys)("openxdox")
    try:
        yield module_object
    finally:
        sys.modules.pop("openxdox.pretend_routes", None)
        if parent_was_created:
            sys.modules.pop("openxdox", None)


def _late_handler(consumer_reach, methods=("_serve_thing", "_refuse_thing")):
    """A `DashboardHandler`-shaped class over a late column, as `serve.py` builds one."""
    column = consumer_reach.route_column(
        consumer_reach.module("pretend_routes", reason="a test's own"),
        "PretendRoutes", methods)

    class Handler(column):
        marker = "handler"

    return column, Handler


def test_a_late_column_is_built_without_resolving_the_consumer() -> None:
    """The class statement runs at IMPORT time — this is the whole reason the

    column member exists. A base that resolved while being built would defer
    nothing: `DashboardHandler`'s bases are evaluated when `serve.py` loads.
    """
    from opendox import consumer_reach

    column, Handler = _late_handler(consumer_reach)
    assert Handler.marker == "handler"
    assert column.LATE_COLUMN == ("openxdox.pretend_routes", "PretendRoutes",
                                  ("_serve_thing", "_refuse_thing")), (
        "the triple openXdox-code's drift guard reads to hold the two surfaces "
        "together must name the module, the class and the method list")
    assert column._serve_thing.__name__ == "_serve_thing", (
        "the forwarder keeps the method's NAME, because a contributed binding "
        "is resolved against the bound class BY NAME at wiring time")


def test_the_forwarders_call_the_consumer_with_the_handler_as_self(
        pretend_column) -> None:
    """The contract: same function object, same `self`, same arguments.

    `route_extension.resolve_handlers` refuses a route that cannot be served
    before a socket is opened, and it resolves the handler by name against the
    BOUND CLASS — so a wrong method list or a forwarding signature that dropped
    an argument would leave imports green and break requests, which is exactly
    what this test is here to stop.
    """
    from opendox import consumer_reach

    _column, Handler = _late_handler(consumer_reach)
    handler = Handler()

    assert handler._serve_thing("/a/b") == "handler:/a/b:False", (
        "positional arguments forward, and `self` is the HANDLER — the column's "
        "method reads `self.marker`, which only the handler has")
    assert handler._serve_thing("/a/b", keyed=True) == "handler:/a/b:True", (
        "keyword arguments forward too")
    assert handler._refuse_thing() == "handler:refused"
    assert handler._serve_thing.__func__ is not \
        pretend_column.PretendRoutes._serve_thing, (
        "the BOUND method is the forwarder, not the column's function")


def test_a_late_column_answers_only_the_names_it_was_given(pretend_column) -> None:
    """No `__getattr__`, deliberately, and the absence is asserted.

    A handler instance is probed for absent attributes constantly — `http.server`
    asks `hasattr(self, "do_PUT")`, and `copy`, `pickle` and pytest all probe —
    so a base that answered those by importing openXdox would fire the reach at
    a moment no verb chose, and would raise `ConsumerReachUnavailable` where the
    caller was testing for `AttributeError`.
    """
    from opendox import consumer_reach

    _column, Handler = _late_handler(consumer_reach, methods=("_serve_thing",))
    handler = Handler()

    assert handler._serve_thing("/x") == "handler:/x:False"
    with pytest.raises(AttributeError):
        handler.do_PUT
    with pytest.raises(AttributeError):
        # Present on the consumer's column, absent from the NAMED list: a name
        # left out of the list is left out of the class, not silently proxied.
        handler._refuse_thing
    assert not hasattr(handler, "_refuse_thing")


def test_a_late_column_with_no_consumer_refuses_at_the_call() -> None:
    """Construction succeeds, the call refuses, and the refusal names the layering."""
    from opendox import consumer_reach

    column = consumer_reach.route_column(
        consumer_reach.module("no_such_column", reason="a test's own"),
        "NoRoutes", ("_serve_thing",))

    class Handler(column):
        marker = "handler"

    with pytest.raises(consumer_reach.ConsumerReachUnavailable) as caught:
        Handler()._serve_thing("/x")
    message = str(caught.value)
    assert "openxdox.no_such_column" in message
    assert "RULED OQ-2" in message
    assert isinstance(caught.value.__cause__, ModuleNotFoundError)


def test_a_column_standing_in_for_nothing_is_refused() -> None:
    """An empty method list would build a base that inherits nothing and hides it."""
    from opendox import consumer_reach

    with pytest.raises(ValueError, match="name the methods"):
        consumer_reach.route_column(
            consumer_reach.module("pretend_routes", reason="a test's own"),
            "PretendRoutes", ())


def test_the_two_live_columns_name_the_methods_serve_dispatches() -> None:
    """The real bindings, held against the names `serve.py` and § 2.4 rely on.

    `_serve_snapshot` is the one to watch: `/snapshot.json`'s HANDLER travelled
    to the projection column while its dispatch ARM stayed core, so `serve.py`
    itself calls `self._serve_snapshot`. Dropping it from the list would leave
    every import green and `/snapshot.json` broken.
    """
    from opendox import consumer_reach

    gate_module, gate_class, gate_methods = \
        consumer_reach.LateGateRoutes.LATE_COLUMN
    assert (gate_module, gate_class) == ("openxdox.serve_gate", "GateRoutes")
    assert "_handle_gate_action" in gate_methods, (
        "the route the § 2.4 gate binding declares")

    proj_module, proj_class, proj_methods = \
        consumer_reach.LateProjectionRoutes.LATE_COLUMN
    assert (proj_module, proj_class) == ("openxdox.serve_projection",
                                        "ProjectionRoutes")
    for required in ("_serve_snapshot", "_serve_index", "_serve_source",
                     "_refuse_bare_source"):
        assert required in proj_methods, (
            f"{required} is dispatched by name and must be on the column")


def test_the_prefix_is_refused_rather_than_doubled() -> None:
    from opendox import consumer_reach

    with pytest.raises(ValueError, match="WITHOUT"):
        consumer_reach.module("openxdox.gate_console", reason="a test's own")


# --------------------------------------------------------------------------
# 3 — the converted sites, and the blind spot that made this file necessary
# --------------------------------------------------------------------------

#: `module path -> the names this slice rebound to the late seam`. Each must be
#: reachable ONLY from a function body: a default argument, an annotation, a
#: decorator or a module-level expression would resolve the consumer at import
#: time and make the conversion a census trick.
CONVERTED_SITES = {
    "cli.py": ("gate_mod", "snapshot_mod"),
    "serve_workbench.py": ("registry_mod",),
    "workbench.py": ("find_validator",),
    # Slice 2b step 4. `consumer_reach` and `defaults` are deliberately NOT
    # listed: both ARE read at import time and must be. Constructing a stand-in
    # resolves nothing (`test_importing_the_seam_resolves_nothing`), and the two
    # late COLUMNS are mixin bases, which a class statement needs before its
    # first instance exists; `defaults` is openDox's own module, which is the
    # point of it. What must not be read at import time is a name BOUND to a
    # stand-in, and these are serve.py's two.
    "serve.py": ("registry_mod", "hosted_ref_refused", "resolve_source_path"),
}


def _import_time_uses(path: Path, names: frozenset[str]) -> list[tuple[int, str]]:
    """Every use of `names` that runs when the module is imported.

    The module body, module-level `if`/`try`/`with`, CLASS bodies, and — the
    case the openXdox-side census cannot see — a function's DEFAULTS,
    ANNOTATIONS and DECORATORS, which are evaluated where the `def` sits and
    not where it is called. Only a function BODY defers.
    """
    hits: list[tuple[int, str]] = []

    def used(node: ast.AST, why: str) -> None:
        for inner in ast.walk(node):
            # READS only. The one module-level STORE of each of these names is
            # the seam binding itself (`gate_mod = consumer_reach.gate_console`)
            # — the line this slice wrote, which resolves nothing.
            if isinstance(inner, ast.Name) and inner.id in names \
                    and isinstance(inner.ctx, ast.Load):
                hits.append((inner.lineno, f"{inner.id} ({why})"))

    def walk(body: list[ast.stmt], at_import_time: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if at_import_time:
                    args = node.args
                    for default in [*args.defaults, *(d for d in args.kw_defaults if d)]:
                        used(default, "default argument")
                    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs,
                                args.vararg, args.kwarg]:
                        if arg is not None and arg.annotation is not None:
                            used(arg.annotation, "annotation")
                    for decorator in node.decorator_list:
                        used(decorator, "decorator")
                    if node.returns is not None:
                        used(node.returns, "return annotation")
                continue
            if not at_import_time:
                continue
            nested: list[ast.stmt] = []
            for _field, value in ast.iter_fields(node):
                items = value if isinstance(value, list) else [value]
                for item in items:
                    if isinstance(item, ast.stmt):
                        nested.append(item)
                    elif isinstance(item, ast.AST):
                        used(item, "module level")
            walk(nested, True)

    walk(ast.parse(path.read_text(encoding="utf-8")).body, True)
    return sorted(set(hits))


@pytest.mark.parametrize("module_file", sorted(CONVERTED_SITES))
def test_a_converted_name_is_never_used_at_import_time(module_file: str) -> None:
    """The guard that would have caught the two reverts before they were made."""
    found = _import_time_uses(PACKAGE / module_file,
                              frozenset(CONVERTED_SITES[module_file]))
    assert found == [], (
        f"src/opendox/{module_file} uses a late-bound consumer name where it "
        f"runs AT IMPORT TIME: {found}. The stand-in would resolve `openxdox` "
        "there, so removing the import statement would lower openXdox-code's "
        "ratchet without removing the dependency — a census that reads better "
        "than the tree. Defer the use, or leave the import alone and ask for "
        "the declared-edit ruling")


def test_no_module_under_src_names_the_pre_carve_package_at_import_time() -> None:
    """`ideation_dashboard` is openxFactory's PRE-CARVE name, not a dependency.

    Recorded, not yet zero: `serve.py` reaches
    `ideation_dashboard.serve_openxfactory_lanes` twice at import time — a
    `stays_openxfactory_adapter` row (RULING DQ-1) present at NEITHER carve
    destination, so the carve's `import rewrites` class had nothing lawful to
    rewrite it to. It is the same defect class § 4.1 fixed on the openXdox
    side, and it is blocked here by the same undeclared lines as serve.py's
    `openxdox` reaches.
    """
    known = {"src/opendox/serve.py": 2}
    seen: dict[str, int] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom) and not node.level and \
                    (node.module or "").split(".")[0] == "ideation_dashboard":
                seen[rel] = seen.get(rel, 0) + 1
            elif isinstance(node, ast.Import) and any(
                    a.name.split(".")[0] == "ideation_dashboard" for a in node.names):
                seen[rel] = seen.get(rel, 0) + 1
    assert seen == known, (
        f"the pre-carve package name's import-time census moved: {seen} "
        f"(recorded {known}). A NEW one is an unapplied rewrite and must not "
        "be added to the record; a FALL is a slice landing and belongs in the "
        "same commit as this number")
