"""THE PROJECTION MECHANISM'S SEAMS: the snapshot registry and source, the
corpus-root predicate, the snapshot writer and the validator lookup. Each is a
host's contribution or openDox's own default, held for late resolution (plan
034's T055; #1144's 5.5, and 4.3 in part).

WHY THIS FILE EXISTS. openDox's generate verbs and its server reached four
mechanisms of the consumer's projection column through `consumer_reach`: the
snapshot registry and the source built over it (`openxdox.snapshot_registry`),
the corpus-root predicate (`openxdox.corpus_root`), the snapshot writer and its
validator (`openxdox.snapshot`). With openXdox absent, which is the normal state
of a neutral openDox, each of those reaches refused, so a server could not be
BUILT standalone (plan 034, research R7) and a generate verb could not write.
`consumer_reach` names the gap itself: the injection that would retire a reach,
*"openDox naming a protocol and being handed an implementation"*, *"does not
exist yet and is BUILD-arc work"*. This module is that injection for the four.

R1Q10 (a) (`openxFactory#656` comment `5850003126`, in R-G3's pattern). openDox
grows a small neutral default for each mechanism, and the consumer contributes
its governed one through the same seam. The defaults are new code
(`opendox.default_registry`, `opendox.default_projection`), not openXdox's
modules relocated: option (b), the relocation, was not the ruling.

THE ENTRY POINTS REGISTER THE DEFAULTS WHERE NO HOST HAS (R1Q3 (a), comment
`5817152735`). `cli.build_parser()`, `cli.main()`, `serve.build_server()` and
`serve.main()` call `register_defaults()`, beside their registrations of the
default profile, the default home corpus and the default generator. So:

* a process that runs none of them still meets `SeamNotRegistered`, naming the
  seam and the call, which is the library caller's case (4.2's discipline:
  REFUSAL, NOT A DEFAULT, so nothing here ever answers an empty mechanism that
  would read exactly like a working one);
* a host registration made BEFORE the default has been read replaces it;
* AFTER a consumer has read the default, a host's registration is refused as
  `SeamAlreadyRegistered`. One process would otherwise hold two registries, two
  predicates or two writers, and a registry entry built by one would be
  registered in the other. It is the same rule the profile and the generator
  keep (R1Q3 (ii); RN-1 (a), comment `5850003126`);
* the same registration again is a no-op, so an idempotent host start is not
  punished, and `unregister()` makes a deliberate swap explicit.

THE FOUR SEAMS.

* `registry`: the snapshot registry and the source that serves and regenerates
  through it. A registration is a MODULE, or any object, carrying
  `REGISTRY_CALLABLES` and `REGISTRY_VALUES`: the entry, registry and source
  types, the key and containment rules, and the refresh bindings.
  openXdox's `snapshot_registry` module carries them as it stands.
* `corpus_root`: whether a path can be scanned as a corpus checkout at all,
  the refusal a verb prints when it cannot, the roots a corpus is scanned from,
  and the corpus's change rows (`branch_session`'s proposal custody reads
  them). A registration carries `CORPUS_ROOT_CALLABLES` and
  `CORPUS_ROOT_VALUES`.
* `writer`: the canonical snapshot writer, `write_snapshot(snapshot, path,
  boundary)`, which writes through the interactivity boundary.
* `validators`: the validator lookup, ONE REGISTRATION PER KIND. A snapshot is
  validated by the validator registered for its own `kind`, which is its
  generator's declared contract (`generator_seam.SnapshotGenerator.contract`),
  and a workbench manifest by the one registered for `ideation-workbench`. A
  host registers a validator for each of its own kinds, and openDox's entry
  points register openDox's own for openDox's kinds. So a host that contributes
  its governed snapshot validator does not take openDox's own kinds with it.

RESOLVE PER CALL. A consumer asks `current()` (or reads through `proxy`) at
each use and holds nothing across calls, so every consumer in a process answers
from the one registration that exists at the time.

ONE LOCK PER SEAM. `serve.py` answers each request on a thread of its own, so
a registration and a read can meet. Each seam's bookkeeping is held under its
own lock, and a registration's own code (probing its names, naming it in a
refusal) never runs under it.

IMPORT WEIGHT. The standard library only. So this module imports with no extra
installed and no sibling present, and it names no sibling in an import.
`register_defaults()` imports openDox's two default modules when it is CALLED.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "CORPUS_ROOT_CALLABLES",
    "CORPUS_ROOT_VALUES",
    "NOT_CONFORMANT",
    "ProjectionSeamError",
    "REGISTRY_CALLABLES",
    "REGISTRY_VALUES",
    "SeamAlreadyRegistered",
    "SeamNotRegistered",
    "VALIDATED",
    "VALIDATOR_CALLABLES",
    "VALIDATOR_UNAVAILABLE",
    "ValidationResult",
    "ValidatorNotRegistered",
    "WRITER_CALLABLES",
    "corpus_root",
    "name_of",
    "register_defaults",
    "registry",
    "validators",
    "writer",
]

#: The ruling every refusal cites for where the defaults come from.
_DEFAULTS_RULING = (
    "R1Q10 (a), openxFactory#656 comment 5850003126, in R1Q3 (a)'s pattern")

#: The entry points that register the defaults, as every refusal names them.
_ENTRY_POINTS = ("`cli.build_parser()`, `cli.main()`, `serve.build_server()` "
                 "and `serve.main()`")

#: How much of a `repr` a refusal quotes before it stops being read.
_NAME_LIMIT = 120


class ProjectionSeamError(RuntimeError):
    """A refusal of one of the projection seams.

    One base for every refusal below, so a verb can report them in one clause,
    as `cli.main()` and `serve.main()` do."""


class SeamNotRegistered(ProjectionSeamError):
    """Nothing is registered at a seam: no host's contribution, and no entry
    point's default. Raised instead of falling back to openDox's own default,
    which is a registration an ENTRY POINT makes."""


class SeamAlreadyRegistered(ProjectionSeamError):
    """A second, different registration was made over a first: over a host's,
    or over the entry point's default after a consumer has read it."""


class ValidatorNotRegistered(SeamNotRegistered):
    """No validator is registered for a kind. The validator lookup refuses
    rather than choosing another kind's validator, because a validator reads a
    document by its kind."""


def name_of(value: Any) -> str:
    """A registration's most nameable name, for a refusal. Never raises: a
    refusal that fails while formatting itself replaces the reader's problem
    with a worse one."""
    try:
        name = getattr(value, "__name__", None)
        if isinstance(name, str) and name:
            return name
    except Exception:  # noqa: BLE001 - naming must never out-raise
        pass
    try:
        kind = type(value)
        return f"{kind.__module__}.{kind.__qualname__} instance"
    except Exception:  # noqa: BLE001
        pass
    try:
        text = repr(value)
    except Exception:  # noqa: BLE001
        text = ""
    if not text:
        return "an unnameable registration"
    return text if len(text) <= _NAME_LIMIT else text[:_NAME_LIMIT - 1] + "…"


def _probe(registration: Any, callables: tuple[str, ...],
           values: tuple[str, ...], call: str, what: str) -> None:
    """Refuse a registration that does not carry the seam's names.

    A registration that CANNOT HAND OVER a name, because looking it up raises
    (a lazy module whose first use fails, say), lacks that name. Its failure is
    chained to the refusal, so the reason stays readable, and it never escapes
    the registration as a failure of some other kind (T027's rule for the
    status-exemption seam, `doxbench_packet.register_status_exemption`)."""
    missing: list[str] = []
    failure: Exception | None = None
    for name in (*callables, *values):
        try:
            member = getattr(registration, name)
        except Exception as exc:  # noqa: BLE001 - a name it cannot hand over is a name it lacks
            failure = failure or exc
            missing.append(name)
            continue
        if name in callables and not callable(member):
            missing.append(name)
    if registration is None or missing:
        wanted = ", ".join(callables)
        if values:
            wanted += f" (callables) and {', '.join(values)}"
        refusal = TypeError(
            f"{call} takes {what}: a module, or any object, carrying {wanted}. "
            f"{name_of(registration)} lacks {', '.join(missing) or 'them'}. A "
            "host with no contribution of its own does not register one: the "
            "entry points then register openDox's own default, and a process "
            "that runs none of them is refused, naming this call.")
        if failure is None:
            raise refusal
        raise refusal from failure


class _SeamProxy:
    """A module-shaped stand-in over one seam's registration, resolved on each
    attribute read.

    `registry_mod = projection_seams.registry.proxy` lets a module keep its
    `registry_mod.X` reads while every one of them resolves the registration
    current at the moment it runs. Dunder lookups never resolve: `copy`,
    `pickle`, `inspect` and pytest's own assertion rewriting probe for dunders
    on arbitrary objects, and a probe must not be what reads a seam.
    `consumer_reach._LateConsumerModule` settled the same rule."""

    __slots__ = ("_seam",)

    def __init__(self, seam: "_Seam") -> None:
        self._seam = seam

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("__") and attr.endswith("__"):
            raise AttributeError(attr)
        return getattr(self._seam.current(), attr)

    def __repr__(self) -> str:
        return f"<projection seam proxy {self._seam.name!r}>"


class _Seam:
    """ONE registration: a host's contribution, or the entry point's default.

    `callables` and `values` are the names a registration must carry.
    `default` names openDox's own default, for the refusal. The records a
    registration keeps are whether it is the entry point's default, and whether
    a consumer has read that default since it was registered.

    `module` names the module that declares the seam, in every refusal and in
    the call a host makes. It is this module's own by default, and
    `opendox.column_seams` declares its four seams through the same class
    (plan 034 T084), so every seam of openDox's keeps one discipline."""

    def __init__(self, name: str, *, what: str, callables: tuple[str, ...],
                 values: tuple[str, ...] = (), default: str,
                 consequence: str,
                 module: str = "opendox.projection_seams") -> None:
        self.name = name
        self.module = module
        #: The module's own name without the package, as a refusal names a call.
        self._short = module.rsplit(".", 1)[-1]
        self.what = what
        self.callables = callables
        self.values = values
        self.default = default
        self.consequence = consequence
        #: The ONE call a host makes, quoted verbatim in every refusal.
        self.registration_call = (
            f"{module}.{name}.register(<the host's {what}>)")
        self._registered: Any = None
        self._is_default = False
        self._default_read = False
        self._lock = threading.Lock()
        #: A module-shaped proxy over whatever is registered (see `_SeamProxy`).
        self.proxy = _SeamProxy(self)

    def _begin(self, registration: Any, *, is_default: bool) -> None:
        """The one place the registration changes. The caller holds the lock."""
        self._registered = registration
        self._is_default = is_default
        self._default_read = False

    def register(self, registration: Any) -> Any:
        """THE host's registration, made once, at process start. Returns it.

        The SAME registration again is a no-op, and it is not probed a second
        time. A different one over a host's is refused. Over the entry point's
        default it REPLACES the default until a consumer has read the default,
        and it is refused once one has."""
        with self._lock:
            if registration is not None and registration is self._registered:
                return registration
        _probe(registration, self.callables, self.values,
               f"{self._short}.{self.name}.register()", f"the host's {self.what}")
        with self._lock:
            held = self._registered
            if held is registration:
                return registration
            if held is None or (self._is_default and not self._default_read):
                self._begin(registration, is_default=False)
                return registration
            over_a_host = not self._is_default
        # Named outside the lock: naming a registration can run its own code.
        if over_a_host:
            raise SeamAlreadyRegistered(
                f"a host's {self.what} is already registered at openDox's "
                f"{self.name} seam ({name_of(held)}), and "
                f"{name_of(registration)} would replace it. Registration "
                "happens ONCE, at process start: one process holding two "
                f"would split its consumers between them. Call "
                f"{self.module}.{self.name}.unregister() first if "
                "the swap is deliberate.")
        raise SeamAlreadyRegistered(
            f"openDox's own default {self.what} ({name_of(held)}) is "
            f"registered, because an entry point registered it where no host "
            f"had, and a consumer has already read it, so "
            f"{name_of(registration)} cannot replace it now. A swap would "
            "leave one process holding two, as a host's profile after a build "
            "would (R1Q3 (ii), openxFactory#656 comment 5817152735; RN-1 (a), "
            "comment 5850003126). Register the host's own at process start, "
            f"ahead of {_ENTRY_POINTS}. Call "
            f"{self.module}.{self.name}.unregister() first if the "
            "swap is deliberate.")

    def register_default(self, registration: Any) -> Any:
        """AN ENTRY POINT's registration of openDox's own default (R1Q10 (a)).

        Registers `registration` ONLY where nothing is registered, and leaves
        a host's registration, or a default already registered, exactly as it
        is. Returns whatever is registered afterwards. It is NOT for hosts. A
        default that does not carry the seam's names is refused whether or not
        anything is registered, because it is openDox's own defect."""
        with self._lock:
            if registration is not None and registration is self._registered:
                return registration
        _probe(registration, self.callables, self.values,
               f"{self._short}.{self.name}.register_default()",
               f"openDox's own default {self.what}")
        with self._lock:
            if self._registered is None:
                self._begin(registration, is_default=True)
            return self._registered

    def unregister(self) -> None:
        """Drop the registration, a host's or the default, and its records.
        For test isolation and for a host tearing down."""
        with self._lock:
            self._begin(None, is_default=False)

    def is_registered(self) -> bool:
        """Is anything registered? Answers without reading or refusing."""
        return self._registered is not None

    def holds_a_hosts(self) -> bool:
        """Is a HOST's registration held here, not the entry point's default
        and not nothing? Answers without reading, so it closes no default's
        window, and without refusing."""
        with self._lock:
            return self._registered is not None and not self._is_default

    def current(self) -> Any:
        """The registration, or a refusal naming this seam and its call.

        Reading the entry point's default is what closes its window: from here
        a host's registration over it is refused (see `register()`)."""
        with self._lock:
            registered = self._registered
            if registered is not None and self._is_default:
                self._default_read = True
        if registered is None:
            raise SeamNotRegistered(
                f"no {self.what} is registered at openDox's {self.name} seam "
                f"({self.module}.{self.name}), so {self.consequence}. "
                f"openDox ships its own, {self.default}, but it is a "
                "registration an ENTRY POINT makes and never a fallback here "
                f"({_DEFAULTS_RULING}). {_ENTRY_POINTS} register it where no "
                "host has. Nothing is registered now, so either nothing in "
                "this process has run one of them, or "
                f"{self.module}.{self.name}.unregister() has "
                "dropped the registration since. A host that contributes its "
                "own registers it at process start with\n\n    "
                + self.registration_call + "\n\nbefore anything reads it.")
        return registered


class _KindSeam:
    """The validator lookup: ONE registration PER KIND, each a host's or the
    entry point's default, with the records `_Seam` keeps, kept per kind."""

    name = "validators"
    what = "validator"
    callables = ("validate",)
    #: The ONE call a host makes for each of its kinds.
    registration_call = (
        "opendox.projection_seams.validators.register(<the kind>, "
        "<the host's validator for it>)")

    def __init__(self) -> None:
        #: `kind -> (validator, is_default)`.
        self._registered: dict[str, tuple[Any, bool]] = {}
        #: The kinds whose entry-point default a consumer has read.
        self._default_read: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _require_a_kind(kind: Any, call: str) -> str:
        if not isinstance(kind, str) or not kind or kind != kind.strip():
            raise ValueError(
                f"{call} takes the kind a validator validates, a non-empty name "
                f"with no surrounding space, as a document's `kind` carries "
                f"it, not {kind!r}")
        return kind

    def register(self, kind: str, validator: Any) -> Any:
        """A host's validator for ONE of its kinds, registered once, at
        process start. Returns it. The rules are `_Seam.register()`'s, kept
        per kind."""
        kind = self._require_a_kind(kind, "projection_seams.validators.register()")
        with self._lock:
            held = self._registered.get(kind)
            if held is not None and held[0] is validator:
                return validator
        _probe(validator, self.callables, (),
               "projection_seams.validators.register()",
               f"the host's validator for {kind!r}")
        with self._lock:
            held = self._registered.get(kind)
            if held is not None and held[0] is validator:
                return validator
            if held is None or (held[1] and kind not in self._default_read):
                self._registered[kind] = (validator, False)
                self._default_read.discard(kind)
                return validator
            over_a_host = not held[1]
        if over_a_host:
            raise SeamAlreadyRegistered(
                f"a host's validator for {kind!r} is already registered at "
                f"openDox's validator lookup ({name_of(held[0])}), and "
                f"{name_of(validator)} would replace it. Registration happens "
                "ONCE per kind, at process start. Call "
                f"opendox.projection_seams.validators.unregister({kind!r}) "
                "first if the swap is deliberate.")
        raise SeamAlreadyRegistered(
            f"openDox's own validator for {kind!r} ({name_of(held[0])}) is "
            "registered, because an entry point registered it where no host "
            f"had, and a consumer has already read it, so {name_of(validator)} "
            "cannot replace it now: a document validated by one validator and "
            "then by another under one name is two contracts. Register the "
            f"host's own at process start, ahead of {_ENTRY_POINTS}. Call "
            f"opendox.projection_seams.validators.unregister({kind!r}) first "
            "if the swap is deliberate.")

    def register_default(self, kind: str, validator: Any) -> Any:
        """AN ENTRY POINT's registration of openDox's own validator for one of
        openDox's kinds, ONLY where nothing is registered for that kind.
        Returns whatever is registered for it afterwards."""
        kind = self._require_a_kind(
            kind, "projection_seams.validators.register_default()")
        with self._lock:
            held = self._registered.get(kind)
            if held is not None and held[0] is validator:
                return validator
        _probe(validator, self.callables, (),
               "projection_seams.validators.register_default()",
               f"openDox's own validator for {kind!r}")
        with self._lock:
            if kind not in self._registered:
                self._registered[kind] = (validator, True)
                self._default_read.discard(kind)
            return self._registered[kind][0]

    def unregister(self, kind: str | None = None) -> None:
        """Drop the registration for `kind`, or every registration."""
        with self._lock:
            if kind is None:
                self._registered.clear()
                self._default_read.clear()
            else:
                self._registered.pop(kind, None)
                self._default_read.discard(kind)

    def is_registered(self, kind: str) -> bool:
        """Is a validator registered for `kind`? Answers without reading."""
        return kind in self._registered

    def kinds(self) -> tuple[str, ...]:
        """The kinds a validator is registered for, sorted."""
        with self._lock:
            return tuple(sorted(self._registered))

    def for_kind(self, kind: str) -> Any:
        """The validator registered for `kind`, or `ValidatorNotRegistered`
        naming the kind and the call. It never answers another kind's
        validator. Reading a kind's default closes that kind's window."""
        with self._lock:
            held = self._registered.get(kind) if isinstance(kind, str) else None
            if held is not None and held[1]:
                self._default_read.add(kind)
            known = tuple(sorted(self._registered))
        if held is None:
            raise ValidatorNotRegistered(
                f"no validator is registered for kind {kind!r} at openDox's "
                "validator lookup (opendox.projection_seams.validators), so "
                "nothing of that kind can be validated. A document is "
                "validated by the validator registered for its OWN kind, and "
                "never by another's. Registered now: "
                f"{', '.join(known) or 'none'}. openDox's entry points "
                f"register openDox's own validator for openDox's kinds "
                f"({_DEFAULTS_RULING}); a host registers its own for each of "
                "its kinds at process start with\n\n    "
                + self.registration_call + "\n")
        return held[0]


# --------------------------------------------------------------------------
# the validation result a registered validator answers
# --------------------------------------------------------------------------

#: The three outcomes of a validation. "The snapshot is wrong" and "the check
#: could not be performed" are different facts, and the generate verbs give
#: them different consequences (`cli._validate`).
VALIDATED = "validated"
NOT_CONFORMANT = "not-conformant"
VALIDATOR_UNAVAILABLE = "validator-unavailable"


@dataclass
class ValidationResult:
    """What a registered validator's `validate(path, *, strict, search_from)`
    answers. A host's own result type conforms if it carries these attributes;
    this one is openDox's.

    `validator` names what ran (a path or a name), or is `None` where no
    validator was found at all. `outcome` refines `ok` without displacing it:
    left unset it is derived from `ok`. `unavailable_reason` says why nothing
    could be concluded, when nothing could."""

    ok: bool
    returncode: int
    stdout: str
    stderr: str
    validator: Path | str | None
    outcome: str | None = None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if self.outcome is None:
            self.outcome = VALIDATED if self.ok else NOT_CONFORMANT

    @property
    def available(self) -> bool:
        """Did the validator reach a verdict? False means nothing is known
        about the document's conformance, not that it is bad."""
        return self.outcome != VALIDATOR_UNAVAILABLE

    def summary(self) -> str:
        if self.validator is None:
            return f"validator not found ({self.unavailable_reason or 'none registered'})"
        tail = (self.stdout or self.stderr).strip().splitlines()
        return tail[-1] if tail else f"returncode={self.returncode}"


# --------------------------------------------------------------------------
# the four seams
# --------------------------------------------------------------------------

#: What a snapshot registry registration must carry as callables: its entry,
#: registry and source types, the entry-from-a-file reader, the per-entry
#: containment rule, the key parser, the publishable-ref rule the hosted plane
#: confines by (FR-048), and the data-source configuration readers.
REGISTRY_CALLABLES: tuple[str, ...] = (
    "SnapshotEntry", "SnapshotRegistry", "SnapshotSource",
    "entry_from_snapshot_file", "resolve_within", "parse_key_id",
    "is_publishable_ref", "data_source_from_options", "github_raw_base_url")

#: ...and as values: the refresh bindings, the default ref, and the data
#: source's defaults `serve.main()` offers as its options' defaults.
REGISTRY_VALUES: tuple[str, ...] = (
    "BINDING_REFETCH", "BINDING_REGENERATE", "DEFAULT_REF",
    "DEFAULT_INDEX_NAME", "DEFAULT_PUBLISH_PATH", "PEEK_TTL_SECONDS")

#: What a corpus-root registration must carry: the predicate, the refusal a
#: verb prints, and the corpus's change rows (callables), and the roots a
#: snapshot is projected from (a value, possibly empty).
CORPUS_ROOT_CALLABLES: tuple[str, ...] = (
    "corpus_scan_defect", "corpus_root_refusal", "change_rows")
CORPUS_ROOT_VALUES: tuple[str, ...] = ("SCANNED_ROOTS",)

#: What a writer registration must carry.
WRITER_CALLABLES: tuple[str, ...] = ("write_snapshot",)

#: What a validator registration must carry.
VALIDATOR_CALLABLES: tuple[str, ...] = ("validate",)

registry = _Seam(
    "registry", what="snapshot registry and source",
    callables=REGISTRY_CALLABLES, values=REGISTRY_VALUES,
    default="opendox.default_registry",
    consequence="no snapshot can be registered, served or regenerated")

corpus_root = _Seam(
    "corpus_root", what="corpus-root predicate",
    callables=CORPUS_ROOT_CALLABLES, values=CORPUS_ROOT_VALUES,
    default="opendox.default_projection.CORPUS_ROOT",
    consequence="no path can be accepted as a corpus checkout")

writer = _Seam(
    "writer", what="snapshot writer", callables=WRITER_CALLABLES,
    default="opendox.default_projection.WRITER",
    consequence="no snapshot can be written")

validators = _KindSeam()


def register_defaults() -> None:
    """Register openDox's OWN default at each of the four seams, where no host
    has registered one (R1Q10 (a), in R1Q3 (a)'s pattern).

    The entry points call this beside their registrations of the default
    profile, home corpus and generator. It registers nothing over a host, and
    reads nothing, so a host registration made afterwards, and before any
    consumer reads a default, still replaces it. Importing this module
    registers nothing."""
    from opendox import default_projection, default_registry

    registry.register_default(default_registry)
    corpus_root.register_default(default_projection.CORPUS_ROOT)
    writer.register_default(default_projection.WRITER)
    for kind in default_projection.OWN_KINDS:
        validators.register_default(kind, default_projection.VALIDATORS[kind])
