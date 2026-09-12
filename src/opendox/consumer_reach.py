"""Late-bound reaches from openDox INTO its consumer, openXdox.

WHY THIS FILE EXISTS. openDox is the NEUTRAL product and openXdox is the layer
that pins it: `contracts/opendox-pin.yaml` in the openXdox assembly root names
openDox's commit and tree digest (`split-opendox-two-layer-product` § 4.2,
RULED OQ-2), and nothing in the chain points back. A module of THIS package may
therefore never require `openxdox` to be importable. `design.md`:243 states the
standard the carve is held to in one sentence: *"What must not survive is the
direction, not the calls."*

Thirty-two calls survived the carve pointing the wrong way — **13 at import
time** and 19 deferred, over six modules, measured at `8e9ffa62` and recorded
as a per-module ratchet in openXdox-code's `tests/test_dependency_direction.py`
(`OPENDOX_BACK_IMPORTS`). They are not a defect of the carve: the manifest's
`import rewrites` class rewrote `ideation_dashboard.<name>` to the package that
now owns `<name>`, and for the gate column that package IS `openxdox`. The
rewrite was correct and the direction it produced is the thing the BUILD arc
removes.

WHAT THIS MODULE DOES. It makes a surviving reach LATE, NAMED and REFUSABLE
instead of an import-time dependency on the consumer. `import opendox.workbench`
no longer requires openXdox to be installed; the verb that actually needs the
consumer's module resolves it on first use and, when it is absent, refuses with
the layering spelled out rather than raising `ModuleNotFoundError` from an
import line a thousand lines away from the call.

WHAT IT DELIBERATELY IS NOT. It is not the § 2.4 extension points and it does
not replace them. A route or a subcommand openXdox CONTRIBUTES travels through
`route_extension.RouteBinding` / `subcommand_extension.SubcommandExtension` —
seams this repository already declares (`serve.build_server(route_extensions=)`,
`cli.build_parser(subcommand_extensions=)`) and openXdox-code already supplies
its half of (`serve_gate.routes()`, `serve_projection.routes()`,
`cli_gate.GateSubcommands.register()`). This module is for the OTHER class: a
neutral verb of openDox's own that calls a function living in the consumer's
column. Those calls are what `design.md`:243 permits to survive; their
DIRECTION at import time is what it does not.

It is kept narrow on purpose so it cannot grow into a facade. A name is added
here only for a reach that is already in the tree and already counted in the
ratchet, and each carries the reason it is still pointing that way.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C). It sits under
a declared root, so the arrival verifier is told about it explicitly with
`--allow-created src/opendox/consumer_reach.py`.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

#: The consumer package. One spelling, unlike openXdox-code's two: openXdox is
#: an installed distribution (`pyproject.toml` at openXdox-code declares
#: `opendox` as a dependency and is itself installed as `openxdox`), never a
#: directory a runner happens to put on `sys.path`. A bare-name fallback here
#: would make an unrelated top-level `gate_console` on the path answer for the
#: consumer's, which is a worse failure than the absence it would paper over.
CONSUMER_PACKAGE = "openxdox"


def _names_the_candidate(missing: str, dotted: str) -> bool:
    """Is `missing` the candidate itself, or a package on its dotted path?

    `import_module("openxdox.gate_console")` raises
    `ModuleNotFoundError(name="openxdox")` when the PACKAGE is absent and
    `name="openxdox.gate_console"` when only the submodule is — both mean "the
    consumer is not here". `name="jsonschema"`, raised from inside a consumer
    module that DID load, does not, and must not be swallowed: catching
    `ImportError` wholesale would report a broken openXdox as a layering
    problem and send the reader to the wrong repository.
    """
    return dotted == missing or dotted.startswith(f"{missing}.")


class ConsumerReachUnavailable(RuntimeError):
    """A verb of openDox reached its consumer's column and it is absent.

    Raised instead of `ModuleNotFoundError` so the failure names the LAYERING
    rather than a module path: openDox does not ship, pin or depend on
    openXdox — the pin runs the other way — so "openXdox is not installed" is
    the NORMAL state of a neutral openDox, and a caller that needs this verb is
    responsible for assembling a server that has it.
    """


class _LateConsumerModule:
    """A stand-in for a consumer module, resolved on first use.

    Attribute access — and nothing earlier — performs the import. The resolved
    module is cached, so the cost is paid once and `is` identity holds across
    accesses, which is what lets a caller `monkeypatch.setattr` the real module
    and be seen by openDox's verbs.
    """

    __slots__ = ("_name", "_reason", "_module")

    def __init__(self, name: str, *, reason: str) -> None:
        self._name = name
        self._reason = reason
        self._module: ModuleType | None = None

    @property
    def name(self) -> str:
        """The dotted name this stand-in resolves, e.g. `openxdox.snapshot`."""
        return f"{CONSUMER_PACKAGE}.{self._name}"

    def resolve(self) -> ModuleType:
        """Import the consumer module, or refuse naming the layering.

        An ABSENT consumer refuses; a consumer that is PRESENT and raises while
        executing re-raises untouched (`_names_the_candidate`).
        """
        if self._module is not None:
            return self._module
        dotted = self.name
        try:
            self._module = importlib.import_module(dotted)
        except ModuleNotFoundError as exc:
            if exc.name is None or not _names_the_candidate(exc.name, dotted):
                raise
            raise ConsumerReachUnavailable(
                f"{dotted!r} belongs to openXdox, the layer that PINS this "
                f"one, and openDox does not supply it: {self._reason}. "
                "openXdox pins openDox by commit and tree digest "
                "(split-opendox § 4.2, RULED OQ-2) and openDox pins nothing "
                "back, so a neutral openDox with no openXdox installed is the "
                "normal case and this reach is the exception. THE REMEDY IS "
                "TO INSTALL openXdox — and only that, today. The § 2.4 "
                "extension points are NOT an alternative here and this "
                "message will not offer one: `build_server(route_extensions=)` "
                "contributes route bindings and "
                "`build_parser(subcommand_extensions=)` contributes "
                "subcommands, and neither injects a MODULE, so a caller who "
                "followed them would arrive back at this same refusal. The "
                "injection that would make this reach disappear — openDox "
                "naming a protocol and being handed an implementation — does "
                "not exist yet and is BUILD-arc work "
                "(split-opendox § 3.5/3.6, § 4.3)") from exc
        return self._module

    def __getattr__(self, attr: str) -> Any:
        # Dunder lookups must not resolve the consumer: `copy`, `pickle`,
        # `inspect` and pytest's own assertion rewriting all probe for dunders
        # on arbitrary objects, and resolving openXdox because something asked
        # for `__wrapped__` would make the reach fire at a moment no verb chose.
        if attr.startswith("__") and attr.endswith("__"):
            raise AttributeError(attr)
        return getattr(self.resolve(), attr)

    def __repr__(self) -> str:
        state = "resolved" if self._module is not None else "unresolved"
        return f"<late consumer module {self.name!r} ({state})>"


class _LateConsumerCallable:
    """One FUNCTION of a consumer module, resolved on first call.

    The module stand-in above cannot serve a `from <module> import <function>`
    site: that form binds the function object itself, and the call sites keep
    spelling it as a bare name. This binds a callable that resolves the module,
    fetches the attribute and forwards — so the call site is unchanged and the
    import is gone.

    Deliberately NOT a `functools.wraps` of the target: wrapping would have to
    resolve the consumer at construction time, which is the import-time reach
    this class exists to remove.
    """

    __slots__ = ("_module", "_attr")

    def __init__(self, module: _LateConsumerModule, attr: str) -> None:
        self._module = module
        self._attr = attr

    @property
    def name(self) -> str:
        return f"{self._module.name}.{self._attr}"

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return getattr(self._module.resolve(), self._attr)(*args, **kwargs)

    def __repr__(self) -> str:
        return f"<late consumer callable {self.name!r}>"


class _LateConsumerValue:
    """One CONSTANT of a consumer module, resolved on first use.

    THE NARROWEST MEMBER OF THIS FAMILY, and the one that needs an argument for
    existing at all. A constant cannot be deferred the way a module or a
    function can: a module stand-in defers until an attribute is read and a
    callable stand-in defers until it is called, but a name bound to a VALUE is
    read by whatever the value is handed to. So this proxy defers to the first
    OPERATION on the value — iteration, length, membership, subscript,
    comparison, truthiness, `str()` — and forwards it to the resolved object.

    IT IS HERE FOR ONE SITE AND IT SAYS WHICH. `cli.py` re-exports
    `openxdox.corpus_root.SCANNED_ROOTS` and reads it at :228 inside a function
    body (`for root in SCANNED_ROOTS`), which defers correctly — but :228 is
    not a line openxFactory's carve manifest declares for `cli.py`'s row, so
    the READ cannot be respelled `corpus_root.SCANNED_ROOTS` and the NAME has
    to keep behaving like the tuple it used to be. `SCANNED_ROOTS` is itself
    DERIVED at the consumer (`tuple(sorted({*corpus.GOVERNED_ROOTS,
    "openspec"}))`, over openxFactory's doc-health corpus), so unlike the
    values in `opendox/defaults.py` it cannot simply be owned here: openDox has
    no corpus to derive it from.

    NOT A GENERAL VALUE FACADE. `__getattr__` is deliberately NOT forwarded: an
    attribute read on a constant is almost always a caller who wanted the
    MODULE, and answering it here would turn this into the facade the module
    docstring refuses. The operations below are the ones a re-exported
    sequence constant is actually subjected to, and a site needing more is a
    site that should be respelled instead.
    """

    __slots__ = ("_module", "_attr")

    def __init__(self, module: _LateConsumerModule, attr: str) -> None:
        self._module = module
        self._attr = attr

    @property
    def name(self) -> str:
        return f"{self._module.name}.{self._attr}"

    def resolve(self) -> Any:
        """The consumer's value, or `ConsumerReachUnavailable` naming the layering."""
        return getattr(self._module.resolve(), self._attr)

    def __iter__(self):
        return iter(self.resolve())

    def __len__(self) -> int:
        return len(self.resolve())

    def __contains__(self, item: Any) -> bool:
        return item in self.resolve()

    def __getitem__(self, key: Any) -> Any:
        return self.resolve()[key]

    def __eq__(self, other: Any) -> bool:
        return self.resolve() == other

    def __ne__(self, other: Any) -> bool:
        return self.resolve() != other

    def __hash__(self) -> int:
        return hash(self.resolve())

    def __bool__(self) -> bool:
        return bool(self.resolve())

    def __str__(self) -> str:
        return str(self.resolve())

    def __repr__(self) -> str:
        # Deliberately does NOT resolve: `repr` is what a debugger, a pytest
        # assertion rewrite and a logging call reach for, and resolving the
        # consumer because something formatted a value would make the reach
        # fire at a moment no verb chose — the same rule `_LateConsumerModule`
        # applies to dunder lookups.
        return f"<late consumer value {self.name!r}>"


class _LateConsumerColumn:
    """The BASE-CLASS member of this family: one handler-method column of the
    consumer, reached on first CALL instead of at class-definition time.

    THE SITE, AND WHY NOTHING NARROWER WOULD DO. `serve.DashboardHandler` named
    `serve_gate.GateRoutes` and `serve_projection.ProjectionRoutes` as MIXIN
    BASES. A base expression is evaluated when the class statement runs, which
    is when the module loads, so those two lines alone made
    `import opendox.serve` require openXdox — and a base, unlike a call, cannot
    be deferred by any of the stand-ins above: a class needs its bases to exist
    before its first instance does.

    So the column is replaced by a base openDox OWNS, carrying one method per
    name the consumer's column defines. Each forwards
    `getattr(<consumer class>, name)(self, *args, **kwargs)` — the SAME function
    object, with the SAME `self`, which is the live request handler — so the
    handler behaves exactly as it did when it inherited: `serve.py`'s core
    `/snapshot.json` arm still finds `self._serve_snapshot`, and a contributed
    binding naming `_handle_gate_action` or `_serve_index` still resolves
    against the bound class at wiring time
    (`route_extension.resolve_handlers`), which is the check that refuses a
    route that cannot be served BEFORE a socket.

    `design.md`:243 is the standard again: *"What must not survive is the
    direction, not the calls."* The call into openXdox's column survives, and it
    is the same call; what goes is the import that used to make it at load time.

    WHY THE METHOD NAMES ARE RESTATED HERE. The same reason `defaults.py`
    restates three literals: the alternative is reading them off the consumer,
    which is the import this removes. `LATE_COLUMN` publishes the triple
    (consumer module, class, method names) so openXdox-code's
    `tests/test_dependency_direction.py` can hold the two surfaces together and
    refuse if either side moves without the other — the drift guard is the
    invariant, the restatement is the spelling.

    NOT A GENERAL SUBCLASS PROXY. There is no `__getattr__` here, deliberately:
    a handler instance is probed for absent attributes constantly (`hasattr(self,
    "do_PUT")` in `http.server`'s own dispatch, `copy`, `pickle`, pytest), and a
    base that answered those by importing openXdox would fire the reach at a
    moment no verb chose — and, worse, would raise this module's
    `ConsumerReachUnavailable` where the caller was testing for `AttributeError`.
    A NAMED method list answers exactly the names the column has and nothing
    else, and an absent consumer refuses at the call with the layering spelled
    out.
    """

    #: `(consumer module, class, method names)`. Set on each generated subclass.
    LATE_COLUMN: tuple[str, str, tuple[str, ...]] = ("", "", ())


def _column_forwarder(holder: _LateConsumerModule, class_name: str, attr: str):
    """One forwarding method: resolve the column's class, then call through it."""

    def forward(self, *args: Any, **kwargs: Any) -> Any:
        column = getattr(holder.resolve(), class_name)
        return getattr(column, attr)(self, *args, **kwargs)

    forward.__name__ = attr
    forward.__qualname__ = f"Late{class_name}.{attr}"
    forward.__doc__ = (
        f"`{holder.name}.{class_name}.{attr}`, resolved on first call "
        f"(consumer_reach._LateConsumerColumn).")
    return forward


def route_column(holder: _LateConsumerModule, class_name: str,
                 methods: tuple[str, ...]) -> type:
    """A mixin base standing in for `<consumer module>.<class_name>`."""
    if not methods:
        raise ValueError(
            "a late column with no methods stands in for nothing; name the "
            f"methods {holder.name}.{class_name} defines")
    namespace: dict[str, Any] = {
        name: _column_forwarder(holder, class_name, name) for name in methods}
    namespace["LATE_COLUMN"] = (holder.name, class_name, tuple(methods))
    namespace["__doc__"] = (
        f"Late stand-in for `{holder.name}.{class_name}` as a mixin base. "
        "See `consumer_reach._LateConsumerColumn`.")
    return type(f"Late{class_name}", (_LateConsumerColumn,), namespace)


def module(name: str, *, reason: str) -> _LateConsumerModule:
    """A late stand-in for `openxdox.<name>`. `name` carries no package prefix."""
    if name.startswith(f"{CONSUMER_PACKAGE}."):
        raise ValueError(
            f"consumer_reach.module() takes the module name WITHOUT the "
            f"{CONSUMER_PACKAGE!r} prefix; got {name!r}")
    return _LateConsumerModule(name, reason=reason)


def function(holder: _LateConsumerModule, attr: str) -> _LateConsumerCallable:
    """A late stand-in for one function of a consumer module."""
    return _LateConsumerCallable(holder, attr)


def constant(holder: _LateConsumerModule, attr: str) -> _LateConsumerValue:
    """A late stand-in for one CONSTANT of a consumer module."""
    return _LateConsumerValue(holder, attr)


# --------------------------------------------------------------------------
# The reaches this package still makes, each with the reason it still makes it
# --------------------------------------------------------------------------

#: The gate console — openXdox's gate-and-commission loop (`design.md` § D3,
#: the gate column). `cli`'s human-gate plumbing and `branch_session`'s session
#: refusals read `GateConsole`, `GateRefused`, `Provenance`, `PRESENCE_*`,
#: `SURFACE_CLI` and `require_human_gate` off it. The injection that removes
#: the reach altogether is § 4.3/§ 4.5 work at openXdox-code, not a direction
#: fix, so the call stays and only its direction at import time goes.
gate_console = module(
    "gate_console",
    reason="the gate-and-commission loop is openXdox's column (design.md § D3) "
           "and openDox contributes no gate of its own")

#: The snapshot writer and validator — openXdox's projection mechanism.
snapshot = module(
    "snapshot",
    reason="the snapshot projection mechanism is openXdox's column "
           "(design.md § D3)")

#: The snapshot registry — the projection's per-binding bookkeeping.
snapshot_registry = module(
    "snapshot_registry",
    reason="the snapshot registry belongs to the projection mechanism, which "
           "is openXdox's column (design.md § D3)")

#: The corpus-root predicate — whether a checkout can be scanned as
#: openxFactory's governed corpus at all. The SHAPE of a corpus is the
#: consumer's business (`SCANNED_ROOTS` is derived from `doc_health.corpus`'s
#: governed roots), and openDox's `cli` asks the question on the way into a
#: generate verb.
corpus_root = module(
    "corpus_root",
    reason="what counts as a scannable corpus checkout is derived from "
           "openxFactory's governed document roots, which openDox does not "
           "carry (design.md § D3)")

#: The snapshot GENERATOR — the projection mechanism's writer half, beside
#: `snapshot` (its validator half) above.
generator = module(
    "generator",
    reason="the snapshot generator is the projection mechanism, which is "
           "openXdox's column (design.md § D3)")

#: The projection's HTTP column. openDox's `serve` core keeps one reach into it
#: — `hosted_ref_refused`, below — after slice 2b stopped naming the column as
#: a mixin base and stopped re-exporting its names.
serve_projection = module(
    "serve_projection",
    reason="the snapshot and index routes are openXdox's column "
           "(design.md § D3); this core dispatches them through the § 2.4 "
           "route extension point instead of inheriting them")

#: `snapshot.find_validator`, bound as a callable because `workbench.py` and
#: `cli.py` import the FUNCTION rather than the module.
find_validator = function(snapshot, "find_validator")

#: `corpus_root.corpus_root_refusal` — `cli.py:130` refuses a generate whose
#: `--repo-root` is not a corpus checkout, and the refusal text is the whole
#: message.
corpus_root_refusal = function(corpus_root, "corpus_root_refusal")

#: `generator.generate_snapshot` and `generator.is_rfc3339_datetime` —
#: `cli.py`'s two generate verbs (:184, :501) and its `--generated-at` shape
#: check (:156).
generate_snapshot = function(generator, "generate_snapshot")
is_rfc3339_datetime = function(generator, "is_rfc3339_datetime")

#: `serve_projection.hosted_ref_refused` — `serve.py:760` must never NAME a
#: session ref on a hosted response (FR-048), and the predicate that decides it
#: travelled to the projection column with its neighbours.
hosted_ref_refused = function(serve_projection, "hosted_ref_refused")

#: `resolve_source_path` STOOD HERE and is `serve.py`'s own definition since
#: § 3.4 slice S6 (RULED Q4, openxFactory#656 comment 5642758731). It is the
#: single-root entry point to the `/source` pass-through's containment, and that
#: pass-through is now a FIXED CORE ARM of the neutral product — so a stand-in
#: forwarding into the layer that PINS openDox was the wrong shape for it. The
#: RULE has not moved: `snapshot_registry.resolve_within` is still the consumer's
#: and is still what the entry point calls, through `serve.py`'s `registry_mod`
#: binding below — the same seam `serve_workbench.py` reaches it by at five
#: sites. `notebook_action.py`:52 still imports the name `from .serve`, and now
#: gets a real function rather than a forwarder.

#: `corpus_root.SCANNED_ROOTS` — the one CONSTANT reach, and the family's
#: narrowest member. `cli.py:228` iterates it to name the roots a rejected
#: checkout is missing; that line is not one the carve manifest declares, so
#: the NAME must keep behaving like the tuple it was. See `_LateConsumerValue`.
scanned_roots = constant(corpus_root, "SCANNED_ROOTS")

#: The gate console's HTTP column — the door the gate verbs are posted through.
#: Named here only to carry `LateGateRoutes` below; `serve.py` holds no other
#: reference to it.
serve_gate = module(
    "serve_gate",
    reason="the gate console's route column is openXdox's (design.md § D3); "
           "this core dispatches its one contributed route through the § 2.4 "
           "route extension point")

#: `serve_gate.GateRoutes` as a mixin base — `DashboardHandler`'s third base
#: until slice 2b. Two methods: the contributed `POST /actions/gate/` handler
#: the § 2.4 binding names, and the failure logger it calls.
LateGateRoutes = route_column(serve_gate, "GateRoutes",
                              ("_handle_gate_action", "_log_gate_failure"))

#: `serve_projection.ProjectionRoutes` as a mixin base — `DashboardHandler`'s
#: fourth base until slice 2b. FIVE methods since § 3.4 slice S6: the one the
#: § 2.4 binding names (`_serve_index`), `_serve_snapshot` — which `serve.py`'s
#: own CORE arm calls, because `/snapshot.json`'s handler travelled with its
#: neighbours while its arm stayed core — and the three those two call between
#: them.
#:
#: IT WAS EIGHT UNTIL S6 (RULED Q4, openxFactory#656 comment 5642758731).
#: `_keyed_source`, `_serve_source` and `_refuse_bare_source` are `serve.py`'s
#: own methods now, because the route they answer is the neutral product's own
#: fixed core arm. `_hosted_entry_refused` stays HERE and is still forwarded:
#: `_serve_snapshot` calls it too, and it is FR-048's hosted-plane confinement,
#: which is the projection column's rule — the route moved, the rule did not.
LateProjectionRoutes = route_column(
    serve_projection, "ProjectionRoutes",
    ("_query_key", "_read_snapshot", "_serve_snapshot", "_hosted_entry_refused",
     "_serve_index"))

__all__ = [
    "CONSUMER_PACKAGE",
    "ConsumerReachUnavailable",
    "constant",
    "corpus_root",
    "corpus_root_refusal",
    "find_validator",
    "function",
    "gate_console",
    "generate_snapshot",
    "generator",
    "hosted_ref_refused",
    "is_rfc3339_datetime",
    "LateGateRoutes",
    "LateProjectionRoutes",
    "module",
    "route_column",
    "scanned_roots",
    "serve_gate",
    "serve_projection",
    "snapshot",
    "snapshot_registry",
]
