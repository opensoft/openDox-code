"""The HANDLER-CONTRIBUTION FACET — R1Q1 (a), Brett Heap, openxFactory#656
comment `5817152735`: "A handler-contribution facet is composed into
`BoundDashboardHandler`, so the lanes mixin can be dropped."

Plan 034 T010. A host profile, or a route extension, declares
`HANDLER_CONTRIBUTIONS`: the mixin classes holding the methods its bindings
name. `serve.build_server` composes them into the class it binds, and
`route_extension.resolve_handlers` is unchanged, so every binding is still
checked against the class that will dispatch it. The module docstring of
`src/route_extension.py` carries the argument and the refusals.

WHAT IT ASSERTS

1. THE TWO CASES THE TASK NAMES. A binding that names a method only a
   contributed mixin has RESOLVES, against the composed class, and not against
   the core alone. A binding that names a method no class has is REFUSED at
   wiring time.
2. THE CONTRIBUTED METHOD MEETS THE LIVE HANDLER. It is dispatched by name on
   the composed class, so it reads the core's gating state off `self`, exactly
   as a core route does. That is the whole safety argument of the route seam,
   and the facet must not weaken it.
3. A CONTRIBUTION MAY ONLY ADD. Each refusal the module docstring lists is
   asserted: a shadowed core name, a clash between contributions, the object
   protocol, shared ancestry, a malformed or doubled declaration, and a layout
   `type()` itself cannot compose.
4. ABSENCE IS NOT A DEFECT. A contributor that declares nothing composes the
   core alone, and the core's MRO stays a prefix of the composed class's.
5. THE SERVER IS WIRED THROUGH IT. `opendox.serve` cannot be imported until
   T011 lands, because `serve.py:199` still reaches openxFactory's pre-carve
   package. So `build_server`'s body is READ with `ast`, as
   `tests/test_profile_registration.py` reads it (plan 034, tasks.md
   § Phase 1). T011's PR adds the case through `build_server` itself.

`--noconftest` SAFE, and it imports neither `opendox.serve` nor `opendox.cli`.
The stand-in core handler below is built on the same stdlib class the real one
is, so the names a contribution could shadow are the real stdlib's.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import ast
import http.server
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import route_extension  # noqa: E402
from import_scan import imported_modules  # noqa: E402

MODULE = ROOT / "src" / "route_extension.py"
SERVE = ROOT / "src" / "opendox" / "serve.py"

RouteBinding = route_extension.RouteBinding
RouteBindingError = route_extension.RouteBindingError


# ---------------------------------------------------------------------------
# the stand-ins
# ---------------------------------------------------------------------------

class _CoreColumn:
    """A core column mixin, as `DashboardHandler` composes its own."""

    def _serve_core_column(self, head_only):
        return ("core column", head_only)


class _CoreHandler(_CoreColumn, http.server.SimpleHTTPRequestHandler):
    """The stand-in for `DashboardHandler`: a column, the stdlib handler, and
    the class attributes `build_server` binds."""

    loopback: bool = True
    capabilities: dict = {"actions": {}}
    route_bindings: tuple = ()

    def _send_json(self, status, obj):
        return (status, obj)


class _Lanes:
    """A contributed column: the methods ITS bindings name, and a helper."""

    def _serve_lane(self, head_only):
        # Reads the CORE's gating state off `self`, which only the composed
        # class can answer: the point of dispatching against the live handler.
        return self._send_json(200, {"lane": True, "loopback": self.loopback,
                                     "head_only": head_only})

    def _handle_lane_action(self):
        return self._lane_helper()

    def _lane_helper(self):
        return self._send_json(202, {"accepted": True})


class _Projection:
    """A second contributed column, with names of its own."""

    def _serve_projection(self, head_only):
        return ("projection", head_only)


LANE_BINDINGS = (
    RouteBinding("GET", "/lane.json", False, "_serve_lane"),
    RouteBinding("POST", "/actions/lane", False, "_handle_lane_action"),
)


class _Profile:
    """A host profile that declares one contribution."""

    ROUTE_EXTENSIONS: tuple = ()
    HANDLER_CONTRIBUTIONS = (_Lanes,)


class _Extension:
    """A route extension that declares its OWN contribution, beside its routes."""

    HANDLER_CONTRIBUTIONS = (_Projection,)

    def routes(self):
        return (RouteBinding("GET", "/projection.json", False,
                             "_serve_projection"),)


class _Bare:
    """A contributor that declares no facet at all."""


def _composed(contributors, namespace=None):
    contributions = route_extension.collect_handler_contributions(
        contributors, base=_CoreHandler)
    return route_extension.compose_handler(
        "BoundHandler", _CoreHandler, contributions,
        namespace if namespace is not None else {"route_bindings": ()})


def _instance(cls):
    """An instance WITHOUT running the stdlib `__init__`, which would handle a
    request off a socket. `tests/test_session_confinement.py` does the same."""
    return object.__new__(cls)


# ---------------------------------------------------------------------------
# 1. the two cases T010 names
# ---------------------------------------------------------------------------

def test_a_binding_naming_a_method_only_a_contributed_mixin_has_resolves():
    """Resolves against the COMPOSED class, and only there. The refusal against
    the core alone is asserted first, so the method is proved to come from the
    contribution and not from somewhere the core already reached."""
    with pytest.raises(RouteBindingError, match="_serve_lane"):
        route_extension.resolve_handlers(LANE_BINDINGS, _CoreHandler)
    bound = _composed((_Profile(),))
    route_extension.resolve_handlers(LANE_BINDINGS, bound)
    assert _Lanes in bound.__mro__


def test_a_binding_naming_a_method_no_class_has_is_refused_at_wiring_time():
    """The contribution composes, and a binding naming a method that neither
    the core nor any contribution has is still refused before the server binds.
    That is `resolve_handlers`' refusal, unchanged and still reached."""
    bound = _composed((_Profile(),))
    stray = RouteBinding("GET", "/nowhere.json", False, "_serve_nowhere")
    with pytest.raises(RouteBindingError) as caught:
        route_extension.resolve_handlers(LANE_BINDINGS + (stray,), bound)
    assert "_serve_nowhere" in str(caught.value)
    assert "_serve_lane" not in str(caught.value), (
        "the contributed method resolved, so only the stray may be named")


# ---------------------------------------------------------------------------
# 2. the contributed method meets the live handler
# ---------------------------------------------------------------------------

def test_a_contributed_method_is_dispatched_against_the_live_handler():
    """`getattr(handler, binding.handler)`, as `serve.py`'s `_route` does it.
    The method reads `self.loopback` and calls `self._send_json`, which only the
    core defines, so `self` is proved to be the composed handler."""
    bound = _composed((_Profile(),), {"route_bindings": LANE_BINDINGS,
                                      "loopback": False})
    handler = _instance(bound)
    read, write = LANE_BINDINGS
    assert getattr(handler, read.handler)(True) == (
        200, {"lane": True, "loopback": False, "head_only": True})
    assert getattr(handler, write.handler)() == (202, {"accepted": True})
    assert handler.route_bindings == LANE_BINDINGS


# ---------------------------------------------------------------------------
# 3. where contributions come from, and in what order
# ---------------------------------------------------------------------------

def test_a_route_extension_declares_its_own_contribution_as_a_profile_does():
    """The profile's first, then each extension's, in the order given, which
    is the order `build_server` passes: the profile, then the extensions it
    collected bindings from."""
    got = route_extension.collect_handler_contributions(
        (_Profile(), _Extension()), base=_CoreHandler)
    assert got == (_Lanes, _Projection)
    bound = route_extension.compose_handler("BoundHandler", _CoreHandler, got,
                                            {})
    route_extension.resolve_handlers(LANE_BINDINGS + _Extension().routes(),
                                     bound)


def test_the_core_handler_stays_first_and_its_mro_a_prefix():
    """The core's MRO is untouched and the contributions sit after it, ahead of
    `object` alone. So nothing a contribution holds can precede a core class."""
    bound = _composed((_Profile(), _Extension()))
    core = _CoreHandler.__mro__
    assert bound.__mro__[0] is bound
    assert bound.__mro__[1:len(core)] == core[:-1]
    assert bound.__mro__[len(core):] == (_Lanes, _Projection, object)


@pytest.mark.parametrize("contributor", (_Bare(), type("_None", (), {
    route_extension.HANDLER_FACET: None})()), ids=("absent", "declared None"))
def test_a_contributor_that_declares_nothing_composes_the_core_alone(contributor):
    """Presence, not truthiness: an absent facet and a declared `None` both
    contribute nothing, and the composed class is then exactly the
    `type(name, (core,), namespace)` a server bound before the facet existed."""
    assert route_extension.declared_handler_contributions(contributor) == ()
    bound = _composed((contributor,))
    assert bound.__mro__ == (bound,) + _CoreHandler.__mro__
    assert bound.__bases__ == (_CoreHandler,)


def test_a_declared_empty_tuple_is_a_declaration_of_nothing():
    class _Empty:
        HANDLER_CONTRIBUTIONS = ()

    assert route_extension.declared_handler_contributions(_Empty()) == ()


# ---------------------------------------------------------------------------
# 4. a contribution may only ADD
# ---------------------------------------------------------------------------

def _contributor(*mixins):
    return type("_Contributor", (), {route_extension.HANDLER_FACET: mixins})()


@pytest.mark.parametrize("name,defined_on", (
    ("_send_json", "_CoreHandler"),           # a core method
    ("_serve_core_column", "_CoreColumn"),    # a core column's method
    ("loopback", "_CoreHandler"),             # a core gating attribute
    ("log_message", "BaseHTTPRequestHandler"),  # the stdlib handler's own
))
def test_a_contribution_that_shadows_the_core_is_refused(name, defined_on):
    """Composed after the core, a shadowing name would be silently unreached;
    composed before it, it would replace a core method. Either is refused, and
    the refusal names where the core defines it."""
    shadowing = type("_Shadowing", (), {name: lambda self, *a: None})
    with pytest.raises(RouteBindingError) as caught:
        route_extension.collect_handler_contributions(
            (_contributor(shadowing),), base=_CoreHandler)
    message = str(caught.value)
    assert name in message and defined_on in message
    assert "may only ADD" in message


def test_two_contributions_defining_one_name_are_refused():
    """Which one answered would be decided by assembly order."""
    other = type("_OtherLanes", (), {"_serve_lane": lambda self, h: None})
    with pytest.raises(RouteBindingError) as caught:
        route_extension.collect_handler_contributions(
            (_Profile(), _contributor(other)), base=_CoreHandler)
    message = str(caught.value)
    assert "_serve_lane" in message
    assert "_Lanes" in message and "_OtherLanes" in message


@pytest.mark.parametrize("hook", ("__getattr__", "__getattribute__", "__init__",
                                  "__init_subclass__", "__call__"))
def test_a_contribution_reaching_the_object_protocol_is_refused(hook):
    """`__getattr__` shadows nothing and would still answer every missing
    attribute the stdlib handler probes for (`hasattr(self, "do_PUT")`), and
    `__getattribute__` would sit in front of every gate the core reads. So
    any dunder beyond class bookkeeping is refused, shadowing or not."""
    hooked = type("_Hooked", (), {hook: lambda self, *a, **k: None})
    with pytest.raises(RouteBindingError, match="OBJECT PROTOCOL"):
        route_extension.collect_handler_contributions(
            (_contributor(hooked),), base=_CoreHandler)


def test_class_bookkeeping_is_not_mistaken_for_the_object_protocol():
    """A docstring, an annotation, an instance store and `__slots__` are what a
    class carries for being a class. None of them is a hook."""

    class _Tidy:
        """Documented."""

        __slots__ = ()
        noted: int

        def _handle_tidy(self):
            self._tidied = True

    assert route_extension.collect_handler_contributions(
        (_contributor(_Tidy),), base=_CoreHandler) == (_Tidy,)


@pytest.mark.parametrize("mixin,because", (
    (_CoreColumn, "already in"),
    (type("_SubCore", (_CoreHandler,), {}), "subclasses the core handler"),
    (type("_ColumnKin", (_CoreColumn,), {"_kin": lambda self: None}),
     "shares ancestry"),
), ids=("a core base", "a subclass of the core", "kin of a core column"))
def test_a_contribution_entangled_with_the_core_is_refused(mixin, because):
    """A declaration that composes nothing, a second handler, or a mixin whose
    ancestry would reorder the core's MRO."""
    with pytest.raises(RouteBindingError, match=because):
        route_extension.collect_handler_contributions(
            (_contributor(mixin),), base=_CoreHandler)


@pytest.mark.parametrize("declared,because", (
    (_Lanes, "not a tuple of classes"),
    ("_Lanes", "not a tuple of classes"),
    (7, "not a tuple of classes"),
    ([_Lanes], "not a tuple of classes"),
    ({_Lanes}, "not a tuple of classes"),
    ((mixin for mixin in (_Lanes,)), "not a tuple of classes"),
    ((_Lanes(),), "is not a class"),
    ((lambda self: None,), "is not a class"),
), ids=("a bare class", "a string", "an int", "a list", "a set", "a generator",
        "an instance", "a function"))
def test_a_malformed_declaration_is_refused(declared, because):
    """A TUPLE of classes, and nothing looser. A set's iteration order would
    decide the composed MRO, and a generator would declare its mixins once and
    nothing on the next build."""
    contributor = type("_Malformed", (), {
        route_extension.HANDLER_FACET: declared})()
    with pytest.raises(RouteBindingError, match=because):
        route_extension.declared_handler_contributions(contributor)


class _Unprintable:
    """An object whose `repr` raises, as an object this module cannot vet may."""

    def __repr__(self):
        raise RuntimeError("this repr refuses to be formatted")


@pytest.mark.parametrize("declared", (_Unprintable(), (_Unprintable(),)),
                         ids=("the facet itself", "an item of the facet"))
def test_a_refusal_never_raises_while_formatting_what_it_refuses(declared):
    """The refusal is `RouteBindingError`, never the `repr`'s own exception: a
    refusal that fails while formatting itself replaces the reader's problem
    with a worse one."""
    contributor = type("_Malformed", (), {
        route_extension.HANDLER_FACET: declared})()
    with pytest.raises(RouteBindingError, match="a _Unprintable"):
        route_extension.declared_handler_contributions(contributor)
    with pytest.raises(RouteBindingError, match="a _Unprintable is not a class"):
        route_extension.compose_handler("BoundHandler", _CoreHandler,
                                        (_Unprintable(),), {})


def test_a_mixin_declared_twice_is_refused_whoever_declares_it():
    for contributors in ((_contributor(_Lanes, _Lanes),),
                         (_Profile(), _contributor(_Lanes))):
        with pytest.raises(RouteBindingError, match="declared twice"):
            route_extension.collect_handler_contributions(
                contributors, base=_CoreHandler)


def test_a_contributed_name_the_composed_class_sets_itself_is_refused():
    """A class attribute in the namespace would shadow the contributed name."""
    with pytest.raises(RouteBindingError, match="never be reached"):
        route_extension.compose_handler(
            "BoundHandler", _CoreHandler, (_Lanes,), {"_serve_lane": None})


def test_compose_handler_repeats_the_checks_where_it_makes_the_class():
    """A caller that skips `collect_handler_contributions` is not a way round
    the refusals: the function that creates the class checks them itself."""
    shadowing = type("_Shadowing", (), {"_send_json": lambda self, *a: None})
    with pytest.raises(RouteBindingError, match="may only ADD"):
        route_extension.compose_handler("BoundHandler", _CoreHandler,
                                        (shadowing,), {})
    with pytest.raises(RouteBindingError, match="more than once"):
        route_extension.compose_handler("BoundHandler", _CoreHandler,
                                        (_Lanes, _Lanes), {})


def test_classes_type_cannot_compose_are_refused_not_raised_as_typeerror():
    """Two slotted mixins with slots of their own conflict in layout. `type()`
    raises `TypeError`, and the build must see the module's one refusal."""
    left = type("_Left", (), {"__slots__": ("_left",)})
    right = type("_Right", (), {"__slots__": ("_right",)})
    with pytest.raises(RouteBindingError, match="cannot be composed"):
        route_extension.compose_handler("BoundHandler", _CoreHandler,
                                        (left, right), {})


def test_collect_finds_what_type_cannot_compose_before_the_build_does():
    """The PREFLIGHT. `collect_handler_contributions` runs where the bindings
    are collected, before the build does any expensive work, and it composes
    the contributions once itself. So a conflict only `type()` can find refuses
    there, rather than after the snapshot source and the sessions are up."""
    left = type("_Left", (), {"__slots__": ("_left",)})
    right = type("_Right", (), {"__slots__": ("_right",)})
    with pytest.raises(RouteBindingError, match="cannot be composed"):
        route_extension.collect_handler_contributions(
            (_contributor(left, right),), base=_CoreHandler)


def test_compose_handler_takes_the_contributions_as_a_tuple():
    with pytest.raises(RouteBindingError, match="as a tuple"):
        route_extension.compose_handler("BoundHandler", _CoreHandler,
                                        [_Lanes], {})
    with pytest.raises(RouteBindingError, match="as a tuple"):
        route_extension.compose_handler("BoundHandler", _CoreHandler,
                                        (m for m in (_Lanes,)), {})


# ---------------------------------------------------------------------------
# 5. the seam stays neutral, and the server is wired through it
# ---------------------------------------------------------------------------

def test_the_facet_leaves_the_extension_point_standard_library_only():
    """`route_extension` travels with both sides of the carve, so it imports
    the standard library and nothing else: no core module names a contributor,
    and this one names no package at all."""
    third_party = sorted({module for module, _line in imported_modules(MODULE)
                          if module.split(".")[0] not in sys.stdlib_module_names})
    assert third_party == [], third_party


def _build_server() -> ast.FunctionDef:
    tree = ast.parse(SERVE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_server":
            return node
    raise AssertionError("serve.py no longer defines build_server()")


def _seam_calls(function: ast.FunctionDef) -> dict[str, list[ast.Call]]:
    calls: dict[str, list[ast.Call]] = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "route_extension":
            calls.setdefault(node.func.attr, []).append(node)
    return calls


def test_build_server_composes_the_class_it_binds_through_the_facet():
    """Read by `ast`, because `opendox.serve` cannot yet be imported (T011).

    `build_server` collects the contributions off the host profile and the
    extensions it collected bindings from, composes the bound class with
    `DashboardHandler` as its base, and resolves the bindings against THAT
    class, in that order. No bare `type(...)` builds the bound class any more.
    """
    function = _build_server()
    calls = _seam_calls(function)
    for seam in ("collect_bindings", "collect_handler_contributions",
                 "compose_handler", "resolve_handlers"):
        assert len(calls.get(seam, ())) == 1, (
            f"build_server() must call route_extension.{seam} once; found "
            f"{len(calls.get(seam, ()))}")
    (collect,) = calls["collect_handler_contributions"]
    (contributors,) = collect.args
    assert isinstance(contributors, ast.Tuple)
    first, *rest = contributors.elts
    assert isinstance(first, ast.Name) and first.id == "profile_openxfactory", (
        "the host profile is the first contributor")
    assert [ast.unparse(node) for node in rest] == ["*contributed"], (
        "then every extension the bindings were collected from")
    assert [ast.unparse(k.value) for k in collect.keywords
            if k.arg == "base"] == ["DashboardHandler"]
    (compose,) = calls["compose_handler"]
    assert [ast.unparse(a) for a in compose.args[:3]] == [
        "'BoundDashboardHandler'", "DashboardHandler", "handler_contributions"]
    (resolve,) = calls["resolve_handlers"]
    assert [ast.unparse(a) for a in resolve.args] == ["route_bindings", "bound"]
    order = [calls[seam][0].lineno for seam in (
        "collect_bindings", "collect_handler_contributions",
        "compose_handler", "resolve_handlers")]
    assert order == sorted(order), f"out of order: {order}"
    bare = [node.lineno for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "type"]
    assert bare == [], f"a bare type(...) still builds a class at {bare}"
