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
   asserted: a shadowed core name, a name the core sets on its instances, a
   clash between contributions, the object protocol, a data descriptor, a
   metaclass of the contribution's own, shared ancestry, a malformed or
   doubled declaration, and an MRO `type()` itself cannot compose. Classes are
   compared by identity, and no refusal raises while it formats what it
   refuses.
4. ABSENCE IS NOT A DEFECT. A contributor that declares nothing composes the
   core alone, and the core's MRO stays a prefix of the composed class's.
5. THE SERVER IS WIRED THROUGH IT. `build_server`'s body is READ with `ast`,
   as `tests/test_profile_registration.py` reads it, for what no single build
   shows. That is the order of the seam calls, and the fact that a name the
   bound class sets is refused before the build's first side effect.
6. AND IT SERVES. Since T011 removed `serve.py`'s two import-time reaches,
   `opendox.serve` imports in a lone checkout, so section 6 drives
   `build_server` itself. A contributed route is served against the live
   handler. A contribution that cannot be composed is refused beside the
   bindings, BEFORE the snapshot source is bootstrapped. A binding that no
   class answers is refused at the END of the build, by `resolve_handlers`.
   That refusal checks the class that will dispatch the route, and the build
   composes that class last, from values its own work computes.

`--noconftest` SAFE. Sections 1 to 5 import neither `opendox.serve` nor
`opendox.cli`; section 6 imports `opendox.serve` inside its fixture.
The stand-in core handler below is built on the same stdlib class the real one
is, so the names a contribution could shadow are the real stdlib's.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import abc
import ast
import contextlib
import functools
import http.server
import sys
import typing
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


@pytest.mark.parametrize("name,assigned_by", (
    ("path", "BaseHTTPRequestHandler"),
    ("wfile", "StreamRequestHandler"),
    ("_headers_buffer", "BaseHTTPRequestHandler"),
    ("server", "BaseRequestHandler"),
    ("directory", "SimpleHTTPRequestHandler"),
))
def test_a_contribution_named_like_the_cores_instance_state_is_refused(
        name, assigned_by):
    """The stdlib handler sets these on each INSTANCE, so no class's `dir()`
    lists them, and the shadowing refusal alone would pass them (Copilot's
    review of #40 at `353d418`). They are measured from the core's source, and
    the refusal names the class that sets each one."""
    assert name not in dir(_CoreHandler)
    named = type("_Named", (), {name: lambda self, *args: None})
    with pytest.raises(RouteBindingError, match="INSTANCE") as caught:
        route_extension.collect_handler_contributions(
            (_contributor(named),), base=_CoreHandler)
    message = str(caught.value)
    assert name in message and assigned_by in message
    assert "may only ADD" in message


def test_instance_state_is_refused_because_a_binding_would_dispatch_the_cores_value():
    """Why the refusal above exists. Composed WITHOUT the facet's checks, a
    contributed method named `path` passes `resolve_handlers`, which looks on
    the class. But the stdlib handler sets `self.path` to the request path on
    every request, so the live handler answers the name with a string."""
    named = type("_Named", (), {"path": lambda self, head_only: None})
    unchecked = type("Unchecked", (_CoreHandler, named), {})
    binding = RouteBinding("GET", "/named.json", False, "path")
    route_extension.resolve_handlers((binding,), unchecked)
    handler = _instance(unchecked)
    handler.path = "/named.json"          # what `parse_request` does
    assert not callable(getattr(handler, binding.handler))


class _StatefulCore(_CoreHandler):
    """A core handler that keeps state of its own on each instance, in every
    form of assignment the measurement reads."""

    def _begin(self):
        self._session = object()
        self._first, (self._second, *self._rest) = 1, (2, 3)
        self._count: int = 0
        self._count += 1
        for self._cursor in ():
            pass
        with contextlib.nullcontext() as self._held:
            pass
        setattr(self, "_actor", None)


@pytest.mark.parametrize("name", ("_session", "_first", "_second", "_rest",
                                  "_count", "_cursor", "_held", "_actor"))
def test_the_measurement_reads_every_form_of_assignment_on_self(name):
    assert route_extension._instance_state(_StatefulCore)[name] is _StatefulCore
    named = type("_Named", (), {name: lambda self: None})
    with pytest.raises(RouteBindingError, match="_StatefulCore"):
        route_extension.collect_handler_contributions(
            (_contributor(named),), base=_StatefulCore)


class _ReceiverCore(_CoreHandler):
    """A core handler whose methods name their receivers otherwise, in each
    kind of method the measurement reads and in the two kinds it must not."""

    def _begin(handler):
        handler._via_handler = object()

    if True:
        def _conditional(request):
            setattr(request, "_via_request", None)

    _labelled = (lambda this: setattr(this, "_via_lambda", 1))

    @classmethod
    def _register(klass):
        klass._registry = {}

    @staticmethod
    def _helper(other):
        other._on_another_object = True

    class _Nested:
        def _own(self):
            self._nested_only = True


@pytest.mark.parametrize("name", ("_via_handler", "_via_request", "_via_lambda",
                                  "_registry"))
def test_the_measurement_reads_each_method_through_its_own_receiver(name):
    """A receiver need not be called `self` (Copilot's review of #40 at
    `1abb631`). Each method is read through its first positional parameter:
    a method, one defined under an `if`, and a class-level `lambda`. A
    `classmethod`'s receiver is the class, and a name the core sets on its
    class at run time would replace a contributed one there."""
    assert route_extension._instance_state(_ReceiverCore)[name] is _ReceiverCore
    named = type("_Named", (), {name: lambda self: None})
    with pytest.raises(RouteBindingError, match="_ReceiverCore"):
        route_extension.collect_handler_contributions(
            (_contributor(named),), base=_ReceiverCore)


def test_the_measurement_does_not_read_what_is_not_the_receiver():
    """A `staticmethod` has no receiver, so what it assigns lands on some
    other object. A nested class's methods receive that class's instances."""
    state = route_extension._instance_state(_ReceiverCore)
    assert "_on_another_object" not in state
    assert "_nested_only" not in state


def test_a_core_class_without_readable_source_measures_as_assigning_nothing():
    """`object`, and a class built at run time, have no source to read. They
    add no names, and the rest of the MRO is still measured."""
    built = type("_Built", (_CoreHandler,), {})
    assert route_extension._assigned_on_self(object) == frozenset()
    assert route_extension._assigned_on_self(built) == frozenset()
    named = type("_Named", (), {"path": lambda self: None})
    with pytest.raises(RouteBindingError, match="INSTANCE"):
        route_extension.collect_handler_contributions(
            (_contributor(named),), base=built)


def test_a_build_that_composes_nothing_measures_nothing(monkeypatch):
    """The measurement reads source, so it runs only for a build that has a
    contribution to check. That includes the preflight."""
    measured = []

    def recording(klass):
        measured.append(klass)
        return frozenset()

    monkeypatch.setattr(route_extension, "_assigned_on_self", recording)
    route_extension.collect_handler_contributions((_Bare(),), base=_CoreHandler)
    route_extension.compose_handler("BoundHandler", _CoreHandler, (), {})
    assert measured == []
    route_extension.collect_handler_contributions((_Profile(),),
                                                  base=_CoreHandler)
    assert measured[:len(_CoreHandler.__mro__)] == list(_CoreHandler.__mro__)


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


class _ColumnRoot:
    """A plain column that a non-class base resolves to."""

    def _serve_rooted(self, head_only):
        return head_only


class _ResolvesToColumnRoot:
    def __mro_entries__(self, bases):
        return (_ColumnRoot,)


class _Resolved(_ResolvesToColumnRoot()):
    """A mixin whose base was RESOLVED at class creation, as a generic alias's
    base is. The class statement records the base as written in
    `__orig_bases__`."""

    def _serve_resolved(self, head_only):
        return head_only


_T = typing.TypeVar("_T")


class _GenericLanes(typing.Generic[_T]):
    def _serve_generic(self, head_only):
        return head_only


def test_a_resolved_base_is_class_bookkeeping_not_the_object_protocol():
    """A class statement writes `__orig_bases__` by itself whenever a base
    resolves through `__mro_entries__` (Copilot's review of #40 at `c450a4a`).
    It records the bases as written, so it is bookkeeping, and a mixin that
    carries it composes. A `typing.Generic` mixin is still refused, for the
    hooks `Generic` itself defines."""
    assert "__orig_bases__" in vars(_Resolved)
    assert route_extension.collect_handler_contributions(
        (_contributor(_Resolved),), base=_CoreHandler) == (_Resolved,)
    bound = route_extension.compose_handler("BoundHandler", _CoreHandler,
                                            (_Resolved,), {})
    route_extension.resolve_handlers((
        RouteBinding("GET", "/resolved.json", False, "_serve_resolved"),
        RouteBinding("GET", "/rooted.json", False, "_serve_rooted"),
    ), bound)
    with pytest.raises(RouteBindingError, match="OBJECT PROTOCOL") as caught:
        route_extension.collect_handler_contributions(
            (_contributor(_GenericLanes),), base=_CoreHandler)
    assert "__init_subclass__" in str(caught.value)


class _TypeParameterised[T]:
    """A PEP 695 generic mixin. Its class statement writes `__type_params__`
    by itself, and it takes `typing.Generic` as an implicit base."""

    def _serve_generic(self, head_only: T) -> T:
        return head_only


def test_a_generic_mixin_is_refused_for_the_hooks_generic_brings_not_its_type_params():
    """`__type_params__` is class bookkeeping, so the refusal does not name it
    (Copilot's review of #40 at `1bd2087`). A generic mixin is still refused,
    by design. `typing.Generic`, its implicit base, defines `__init_subclass__`
    and `__class_getitem__`, so composing it would run `Generic`'s hook on the
    handler class. The unchecked composition shows the hook writing
    `__parameters__` there."""
    assert "__type_params__" in vars(_TypeParameterised)
    assert typing.Generic in _TypeParameterised.__mro__
    with pytest.raises(RouteBindingError, match="OBJECT PROTOCOL") as caught:
        route_extension.collect_handler_contributions(
            (_contributor(_TypeParameterised),), base=_CoreHandler)
    message = str(caught.value)
    assert "__init_subclass__" in message and "__class_getitem__" in message
    assert "__type_params__" not in message
    unchecked = type("Unchecked", (_CoreHandler, _TypeParameterised), {})
    assert vars(unchecked)["__parameters__"] == ()


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


class _SetOnly:
    """A descriptor that defines `__set__` alone."""

    def __set__(self, instance, value):
        pass


class _DeleteOnly:
    """A descriptor that defines `__delete__` alone."""

    def __delete__(self, instance):
        pass


@pytest.mark.parametrize("mixin", (
    type("_ReadOnly", (), {"wfile": property(lambda self: None)}),
    type("_Settable", (), {"wfile": property(lambda self: None,
                                             lambda self, value: None)}),
    type("_Slotted", (), {"__slots__": ("wfile",)}),
    type("_Setter", (), {"wfile": _SetOnly()}),
    type("_Deleter", (), {"wfile": _DeleteOnly()}),
), ids=("a read-only property", "a property with a setter", "a named slot",
        "a __set__ descriptor", "a __delete__ descriptor"))
def test_a_contribution_carrying_a_data_descriptor_is_refused(mixin):
    """`wfile` is the stream the stdlib handler sets on each request, so no
    class's `dir()` lists it and the shadowing refusal cannot see it. A data
    descriptor of that name would intercept the core's own assignment (a
    read-only one would make it raise), so any data descriptor is refused."""
    assert "wfile" not in dir(_CoreHandler)
    with pytest.raises(RouteBindingError, match="DATA DESCRIPTORS") as caught:
        route_extension.collect_handler_contributions(
            (_contributor(mixin),), base=_CoreHandler)
    assert "wfile" in str(caught.value)


def test_a_bookkeeping_name_may_hold_a_data_descriptor_only_where_the_core_answers_it():
    """Class bookkeeping passes the object-protocol refusal by NAME, so its
    value is checked too. The core answers `__dict__` itself, ahead of the
    contribution in the MRO, so a contributed `__dict__` is never reached. A
    core without annotations does not answer `__annotations__`, so a
    contributed data descriptor under that name would answer on every
    instance, and it is refused."""
    smuggled = property(lambda self: {"smuggled": True})
    shadowed = type("_Shadowed", (), {"__dict__": smuggled,
                                      "_serve_shadowed": lambda self, h: None})
    bound = _composed((_contributor(shadowed),))
    assert _instance(bound).__dict__ == {}
    plain = type("_PlainCore", (http.server.SimpleHTTPRequestHandler,), {})
    assert "__annotations__" not in dir(plain)
    annotating = type("_Annotating", (), {"__annotations__": smuggled})
    with pytest.raises(RouteBindingError, match="DATA DESCRIPTORS") as caught:
        route_extension.collect_handler_contributions(
            (_contributor(annotating),), base=plain)
    assert "__annotations__" in str(caught.value)


def test_methods_and_plain_values_are_what_a_contribution_carries():
    """A method, a `staticmethod`, a `classmethod` and a plain constant are
    what a column of methods carries. So is a callable that is not a
    descriptor, which is looked up unchanged on the class and on an
    instance."""

    class _Column:
        _LANE_LIMIT = 3
        _lane_sort = sorted

        def _serve_column(self, head_only):
            return head_only

        @staticmethod
        def _lane_key(name):
            return name.lower()

        @classmethod
        def _lane_kind(cls):
            return cls.__name__

    assert route_extension.collect_handler_contributions(
        (_contributor(_Column),), base=_CoreHandler) == (_Column,)
    bound = route_extension.compose_handler("BoundHandler", _CoreHandler,
                                            (_Column,), {})
    route_extension.resolve_handlers(
        (RouteBinding("GET", "/column.json", False, "_serve_column"),), bound)


class _TwoFaced:
    """A descriptor of a contribution's own that answers the class with a
    method and an instance with a value."""

    def __get__(self, instance, owner):
        return (lambda *args: None) if instance is None else 42


class _RebindingStaticmethod(staticmethod):
    """A `staticmethod` subclass whose `__get__` is its own."""

    def __get__(self, instance, owner=None):
        return 42 if instance is not None else super().__get__(instance, owner)


@pytest.mark.parametrize("value", (
    _TwoFaced(),
    functools.cached_property(lambda self: {}),
    functools.partialmethod(lambda self, lane, head_only: None, "lane"),
    _RebindingStaticmethod(lambda head_only: None),
), ids=("a __get__ of its own", "a cached_property", "a partialmethod",
        "a staticmethod subclass"))
def test_a_contribution_carrying_a_descriptor_that_is_not_a_method_is_refused(value):
    """Python binds a function, a `staticmethod` and a `classmethod` the same
    way on the class and on an instance. Any other descriptor may answer the
    two differently, and `resolve_handlers` checks each binding on the class.
    The test is on the exact type, so a subclass with a `__get__` of its own
    is refused too (Copilot's review of #40 at `0084434`)."""
    carrying = type("_Carrying", (), {"_serve_carried": value})
    with pytest.raises(RouteBindingError, match="not methods") as caught:
        route_extension.collect_handler_contributions(
            (_contributor(carrying),), base=_CoreHandler)
    assert "_serve_carried" in str(caught.value)


def test_a_non_method_descriptor_is_refused_because_its_binding_would_fail_at_request_time():
    """Why the refusal above exists. Composed WITHOUT the facet's checks, a
    binding naming `_TwoFaced` passes `resolve_handlers`, which looks on the
    class, while a live handler answers the name with a value."""
    carrying = type("_Carrying", (), {"_serve_carried": _TwoFaced()})
    unchecked = type("Unchecked", (_CoreHandler, carrying), {})
    binding = RouteBinding("GET", "/carried.json", False, "_serve_carried")
    route_extension.resolve_handlers((binding,), unchecked)
    assert not callable(getattr(_instance(unchecked), binding.handler))


class _Touchy(type):
    """A metaclass whose classes can be neither hashed nor compared. Defining
    `__eq__` sets `__hash__` to `None`, and this `__eq__` refuses as well."""

    def __eq__(cls, other):
        raise RuntimeError("this class refuses to be compared")

    __hash__ = None


class _Answering(type):
    """A metaclass that answers ANY name looked up on its classes."""

    def __getattr__(cls, name):
        return lambda self, *args: None


class _Nameless(type):
    """A metaclass whose classes refuse to say where they live."""

    def __getattribute__(cls, name):
        if name in ("__module__", "__qualname__"):
            raise RuntimeError("this class refuses to be named")
        return super().__getattribute__(name)


@pytest.mark.parametrize("mixin", (
    _Touchy("_TouchyLanes", (), {"_serve_touchy": lambda self, h: None}),
    _Answering("_AnsweringLanes", (), {"_serve_answering": lambda self, h: None}),
    _Nameless("_NamelessLanes", (), {"_serve_nameless": lambda self, h: None}),
    type("_AbstractLanes", (abc.ABC,), {"_serve_abstract": lambda self, h: None}),
), ids=("unhashable and uncomparable", "answers any name", "refuses to be named",
        "an ABC"))
def test_a_contribution_built_by_a_metaclass_of_its_own_is_refused(mixin):
    """The composed class would take the contribution's metaclass, and with it
    how the class itself is called, compared, hashed and named. So a metaclass
    that is not the core's is refused, by both entry points, and the refusal
    still names the mixin when its metaclass refuses to."""
    with pytest.raises(RouteBindingError, match="metaclass") as caught:
        route_extension.collect_handler_contributions(
            (_contributor(mixin),), base=_CoreHandler)
    assert mixin.__name__ in str(caught.value)
    with pytest.raises(RouteBindingError, match="metaclass"):
        route_extension.compose_handler("BoundHandler", _CoreHandler, (mixin,),
                                        {})


def test_a_metaclass_is_refused_because_it_would_pass_a_binding_no_instance_answers():
    """Why the refusal above exists. Composed WITHOUT the facet's checks, a
    mixin built by `_Answering` makes the composed class answer any name. So
    `resolve_handlers`, which looks each binding's method up on the class,
    passes a binding whose method no instance has. The request would then fail
    at dispatch, where the build should have been refused at wiring time."""
    answering = _Answering("_AnsweringLanes", (), {})
    unchecked = type("Unchecked", (_CoreHandler, answering), {})
    stray = RouteBinding("GET", "/nowhere.json", False, "_serve_nowhere")
    route_extension.resolve_handlers((stray,), unchecked)
    assert not hasattr(_instance(unchecked), "_serve_nowhere")
    with pytest.raises(RouteBindingError, match="metaclass"):
        route_extension.collect_handler_contributions(
            (_contributor(answering),), base=_CoreHandler)


class _IteratesNothing(tuple):
    """A tuple subclass that holds a mixin and iterates none of it."""

    def __iter__(self):
        return iter(())


@pytest.mark.parametrize("declared,because", (
    (_Lanes, "not a plain tuple of classes"),
    ("_Lanes", "not a plain tuple of classes"),
    (7, "not a plain tuple of classes"),
    ([_Lanes], "not a plain tuple of classes"),
    ({_Lanes}, "not a plain tuple of classes"),
    ((mixin for mixin in (_Lanes,)), "not a plain tuple of classes"),
    (_IteratesNothing((_Lanes,)), "not a plain tuple of classes"),
    ((_Lanes(),), "is not a class"),
    ((lambda self: None,), "is not a class"),
), ids=("a bare class", "a string", "an int", "a list", "a set", "a generator",
        "a tuple subclass", "an instance", "a function"))
def test_a_malformed_declaration_is_refused(declared, because):
    """A plain TUPLE of classes, and nothing looser. A set's iteration order
    would decide the composed MRO, a generator would declare its mixins once
    and nothing on the next build, and a tuple subclass may iterate however
    it likes: this one holds a mixin and iterates none."""
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


def test_classes_are_compared_by_identity_never_by_hash_or_equality():
    """A class whose metaclass refuses hashing and comparison reaches every
    refusal as `RouteBindingError`, never as the metaclass's own exception
    (Copilot's review of #40 at `6b429f7`, "Previously missed")."""
    one = _Touchy("_One", (), {"_one": lambda self: None})
    two = _Touchy("_Two", (), {"_two": lambda self: None})
    for contributors in ((_contributor(one, one),),
                         (_contributor(one), _contributor(one))):
        with pytest.raises(RouteBindingError, match="declared twice"):
            route_extension.collect_handler_contributions(
                contributors, base=_CoreHandler)
    with pytest.raises(RouteBindingError, match="more than once"):
        route_extension.compose_handler("BoundHandler", _CoreHandler,
                                        (one, one), {})
    with pytest.raises(RouteBindingError, match="metaclass"):
        route_extension.compose_handler("BoundHandler", _CoreHandler,
                                        (one, two), {})


class _Disguised:
    """An object whose reported `__class__` raises. `isinstance` consults the
    `__class__` an object reports, so an `isinstance` check would raise too."""

    @property
    def __class__(self):
        raise RuntimeError("this object refuses to say what it is")


def test_an_object_that_misreports_its_class_is_refused_not_raised():
    """The facet asks an object's REAL type what it is, never its reported
    `__class__`, so each of these is refused as what it is."""
    for declared in (_Disguised(), (_Disguised(),)):
        contributor = type("_Malformed", (), {
            route_extension.HANDLER_FACET: declared})()
        with pytest.raises(RouteBindingError, match="_Disguised"):
            route_extension.declared_handler_contributions(contributor)
    with pytest.raises(RouteBindingError,
                       match="_Disguised object at .* is not a class"):
        route_extension.compose_handler("BoundHandler", _CoreHandler,
                                        (_Disguised(),), {})


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


def _declared_ahead_of_its_own_subclass():
    """Two mixins no MRO can linearize. `_Root` is declared first, so it must
    precede `_Leaf` among the bases, and `_Leaf` derives from it, so it must
    follow it. Only `type()` finds that: neither mixin shadows, clashes or
    carries a hook."""
    root = type("_Root", (), {})
    leaf = type("_Leaf", (root,), {"_serve_leaf": lambda self, h: None})
    return root, leaf


def test_classes_type_cannot_compose_are_refused_not_raised_as_typeerror():
    """`type()` raises `TypeError` for the MRO, and the build must see the
    module's one refusal, with the `TypeError` as its cause."""
    with pytest.raises(RouteBindingError, match="cannot be composed") as caught:
        route_extension.compose_handler("BoundHandler", _CoreHandler,
                                        _declared_ahead_of_its_own_subclass(),
                                        {})
    assert isinstance(caught.value.__cause__, TypeError)


def test_collect_finds_what_type_cannot_compose_before_the_build_does():
    """The PREFLIGHT. `collect_handler_contributions` runs where the bindings
    are collected, before the build does any expensive work, and it composes
    the contributions once itself. So a conflict only `type()` can find refuses
    there, rather than after the snapshot source and the sessions are up."""
    with pytest.raises(RouteBindingError, match="cannot be composed"):
        route_extension.collect_handler_contributions(
            (_contributor(*_declared_ahead_of_its_own_subclass()),),
            base=_CoreHandler)


def test_compose_handler_takes_the_contributions_as_a_tuple():
    for contributions in ([_Lanes], (m for m in (_Lanes,)),
                          _IteratesNothing((_Lanes,))):
        with pytest.raises(RouteBindingError, match="as a plain tuple"):
            route_extension.compose_handler("BoundHandler", _CoreHandler,
                                            contributions, {})


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


def test_a_name_the_bound_class_sets_is_refused_before_build_servers_side_effects():
    """Read by `ast`, for the reason the test above is. `compose_handler`
    refuses a contributed name that the bound class sets in its own namespace,
    but it runs where the class is made, late in the build (Copilot's review
    of #40 at `353d418`).

    Every name `build_server` hands it, though, is declared in
    `DashboardHandler`'s own body, so it is in `dir(DashboardHandler)`. The
    shadowing refusal in `collect_handler_contributions` therefore refuses such
    a collision first. That call precedes the build's first side effect:
    `_head_of`, the snapshot source, and its `bootstrap()`."""
    function = _build_server()
    tree = ast.parse(SERVE.read_text(encoding="utf-8"))
    handler = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef)
                   and node.name == "DashboardHandler")
    declared = set()
    for node in handler.body:
        if isinstance(node, ast.Assign):
            declared |= {target.id for target in node.targets
                         if isinstance(target, ast.Name)}
        elif isinstance(node, ast.AnnAssign) \
                and isinstance(node.target, ast.Name):
            declared.add(node.target.id)
    calls = _seam_calls(function)
    (compose,) = calls["compose_handler"]
    namespace = compose.args[3]
    assert isinstance(namespace, ast.Dict)
    keys = [key.value for key in namespace.keys]
    assert keys, "build_server() hands compose_handler no namespace"
    assert sorted(set(keys) - declared) == [], (
        "a name the bound class sets that DashboardHandler does not declare "
        "is refused only where the class is made, after the side effects")
    (collect,) = calls["collect_handler_contributions"]
    effects = [node.lineno for node in ast.walk(function)
               if isinstance(node, ast.Call) and (
                   (isinstance(node.func, ast.Name)
                    and node.func.id == "_head_of")
                   or (isinstance(node.func, ast.Attribute)
                       and node.func.attr in ("SnapshotSource", "bootstrap")))]
    assert len(effects) >= 3, effects
    assert collect.lineno < min(effects), (collect.lineno, sorted(effects))


# ---------------------------------------------------------------------------
# 6. THE CASE THROUGH `build_server` (T011). `opendox.serve` imports now.
# ---------------------------------------------------------------------------
#
# THE PHASE-1 LIMIT IS LIFTED (plan 034 T055; research R7 measured it). A
# standalone `build_server` met three reaches into openXdox: the snapshot
# source (`registry_mod.SnapshotSource(...)`), `_checkout_real` (which
# imported `openxdox.corpus_root`), and `compute_capabilities`' two reads of
# `registry_mod.BINDING_*`. Phase 1's cases stood in for all three. Since T055
# each is read from a declared seam where `build_server` registers openDox's
# own default, so the predicate and the capabilities below are the real ones.
# The snapshot source stays injected, through `build_server`'s own
# `snapshot_source=` seam, for one reason: the refusal-order case reads whether
# its `bootstrap()` ran. Everything else `build_server` does runs for real, the
# composition first among it.

class _StandInSource:
    """An injected snapshot source: nothing registered, nothing baked. It
    records whether `bootstrap()` ran, so a refusal can be shown to come
    BEFORE the expensive work does."""

    refresh_binding = None
    baked_repository = None

    class registry:
        active = None

    def __init__(self):
        self.bootstrapped = False

    def bootstrap(self):
        self.bootstrapped = True


class _ServedLanes:
    """A contributed column over the REAL core handler."""

    def _serve_lane_probe(self, head_only):
        self._send_json(200, {"lane": "contributed", "loopback": self.loopback})


class _ServedLaneRoutes:
    def routes(self):
        return (RouteBinding("GET", "/lane-probe.json", False,
                             "_serve_lane_probe"),)


class _ServedExtra:
    def _serve_extra_probe(self, head_only):
        self._send_json(200, {"extra": "contributed"})


class _ExtraRoutes:
    """A caller's extension that declares its own mixin."""

    HANDLER_CONTRIBUTIONS = (_ServedExtra,)

    def routes(self):
        return (RouteBinding("GET", "/extra-probe.json", False,
                             "_serve_extra_probe"),)


class _HostProfile:
    SUBCOMMAND_EXTENSIONS: tuple = ()
    ROUTE_EXTENSIONS = (_ServedLaneRoutes(),)
    HANDLER_CONTRIBUTIONS = (_ServedLanes,)


@pytest.fixture()
def standalone(tmp_path):
    """`build_server` with a stand-in host profile, the injected source above,
    and the registry put back afterwards. The root conftest registers its own
    empty profile at process start, and it must find it again. The corpus-root
    predicate and the registry's bindings are the registered defaults, and
    `repo` is not a git repository, so the checkout is not real, as phase 1's
    stand-in answered."""
    from opendox import domain_profile, serve

    previous = domain_profile.current() if domain_profile.is_registered() else None
    domain_profile.unregister()
    (tmp_path / "web").mkdir()
    (tmp_path / "repo").mkdir()
    (tmp_path / "snapshot.json").write_text("{}", encoding="utf-8")
    source = _StandInSource()

    def build(profile, **kwargs):
        domain_profile.register(profile)
        return serve.build_server(
            tmp_path / "web", tmp_path / "snapshot.json", tmp_path / "repo",
            port=0, head="0" * 40, snapshot_source=source, **kwargs)

    build.source = source
    try:
        yield build
    finally:
        domain_profile.unregister()
        if previous is not None:
            domain_profile.register(previous)


def _get(httpd, path):
    import http.client
    import json
    import threading

    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        host, port = httpd.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=10)
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


def test_build_server_composes_the_declared_mixins_into_the_class_it_binds(
        standalone):
    """The profile's mixin and a caller extension's own, composed after the
    core handler, and a live request dispatched to each against the live
    handler. `self.loopback` is the bound server's own verdict."""
    from opendox import serve

    httpd = standalone(_HostProfile(), route_extensions=(_ExtraRoutes(),))
    bound = httpd.RequestHandlerClass.func
    core = serve.DashboardHandler.__mro__
    assert bound.__name__ == "BoundDashboardHandler"
    assert bound.__mro__[1:len(core)] == core[:-1]
    assert bound.__mro__[len(core):] == (_ServedLanes, _ServedExtra, object)
    assert _get(httpd, "/lane-probe.json") == (
        200, {"lane": "contributed", "loopback": True})


def test_a_caller_extensions_own_mixin_is_served(standalone):
    httpd = standalone(_HostProfile(), route_extensions=(_ExtraRoutes(),))
    assert _get(httpd, "/extra-probe.json") == (200, {"extra": "contributed"})


def test_build_server_refuses_a_binding_no_class_answers(standalone):
    """Without the mixin, the lane binding names a method no class has, and the
    server refuses to start. That is `resolve_handlers`' refusal, reached.

    It is the one refusal raised AFTER the snapshot source is bootstrapped, as
    the last assertion pins. `resolve_handlers` checks the class that will
    dispatch the route, and `build_server` composes that class last, because
    its namespace carries values the build computes. A check against an
    earlier class would be a check against a class that never dispatches."""

    class _Undeclared(_HostProfile):
        HANDLER_CONTRIBUTIONS = ()

    with pytest.raises(RouteBindingError, match="_serve_lane_probe"):
        standalone(_Undeclared())
    assert standalone.source.bootstrapped is True


def test_build_server_refuses_a_shadowing_contribution_before_its_work(
        standalone):
    """A contribution that would replace a core method refuses the build
    BEFORE the snapshot source is bootstrapped, beside the bindings."""

    class _Shadowing:
        def _send_json(self, status, obj):
            return None

    class _Shadower(_HostProfile):
        HANDLER_CONTRIBUTIONS = (_Shadowing,)

    with pytest.raises(RouteBindingError, match="may only ADD"):
        standalone(_Shadower())
    assert standalone.source.bootstrapped is False


def test_a_profile_that_declares_nothing_binds_the_core_alone(standalone):
    """The root conftest's empty profile, or any host with no column of its
    own, composes nothing. The core handler names no descendant's column, and
    no module of the package that openDox cannot import sits in its MRO."""
    from opendox import serve

    class _Empty:
        SUBCOMMAND_EXTENSIONS: tuple = ()
        ROUTE_EXTENSIONS: tuple = ()

    httpd = standalone(_Empty())
    try:
        bound = httpd.RequestHandlerClass.func
        assert bound.__mro__ == (bound,) + serve.DashboardHandler.__mro__
        assert not [klass for klass in serve.DashboardHandler.__mro__
                    if klass.__module__.split(".")[0] == "ideation_dashboard"]
    finally:
        httpd.server_close()


def test_build_server_refuses_what_type_cannot_compose_before_its_work(
        standalone):
    """The preflight, through the real core. An MRO no class can take is
    refused beside the bindings, before the snapshot source is bootstrapped,
    rather than at the end of the build."""
    root, leaf = _declared_ahead_of_its_own_subclass()

    class _Unlinearizable(_HostProfile):
        HANDLER_CONTRIBUTIONS = (_ServedLanes, root, leaf)

    with pytest.raises(RouteBindingError, match="cannot be composed"):
        standalone(_Unlinearizable())
    assert standalone.source.bootstrapped is False


def test_build_server_refuses_a_name_the_core_sets_on_instances_before_its_work(
        standalone):
    """Through the real core, `path` is what `BaseHTTPRequestHandler` sets on
    every request. The measurement reads it from the real MRO's source, and
    the build is refused before the snapshot source is bootstrapped."""

    class _NamedLikeState:
        def path(self, head_only):
            return None

    class _Stateful(_HostProfile):
        HANDLER_CONTRIBUTIONS = (_ServedLanes, _NamedLikeState)

    with pytest.raises(RouteBindingError, match="INSTANCE") as caught:
        standalone(_Stateful())
    assert "http.server.BaseHTTPRequestHandler" in str(caught.value)
    assert standalone.source.bootstrapped is False
