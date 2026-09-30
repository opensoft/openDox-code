"""THE GENERATOR SEAM: the one snapshot generator a process generates with, a
host's contribution or openDox's own default, held for late resolution.

WHY THIS FILE EXISTS. Box 5.4 of openxFactory's
`add-neutral-product-standalone-operability` (RATIFIED, `openxFactory#656`
comment `5815412869`) reads *"DECLARE THE GENERATOR SEAM — it does not exist
and `CorpusAdapter` is not it"*. Its requirement 4 has openDox grow a neutral
generator of its own, while the consumer KEEPS its governed generator and
contributes it *"through a DECLARED GENERATOR SEAM"*. That seam *"SHALL BE
DECLARED BY THIS ARC, naming the operation it hands over, the registration
point, and what a conformant implementation must satisfy"*. `consumer_reach.py`
names the same gap from the other side. The injection that would retire its
`generator` reach, *"openDox naming a protocol and being handed an
implementation"*, *"does not exist yet and is BUILD-arc work"*. This module is
that declaration (plan 034's T052).

WHAT GENERATES THROUGH IT. Since plan 034's T055 the generate verbs
(`cli._generate_and_write`, `cli._gate_snapshot`) and the local regenerate of
openDox's own snapshot source (`default_registry.SnapshotSource.refresh`) call
`generate()` below, looking the generator up on each call. T055 came after
T054, which built openDox's own projection, so the day a verb first generated
through this seam, openDox's own generator could generate.

`CorpusAdapter` IS NOT IT, AND STAYS CLOSED AT SIX MEMBERS. The corpus-read
interface (`corpus_adapter.py`) declares `resolve`, `list_documents`, `read`,
`classify`, `check` and `write_back`, and its own docstring says *"Nothing
else, ever"*. None of the six hands a generator over, and a seventh member
would be a seam that leaks. So a generator is handed over HERE, through a
registration of its own. A generator READS its corpus through that interface,
as openDox's own projection does (plan 034's T054).

THE OPERATION HANDED OVER is one call. It answers the snapshot, a JSON-ready
`dict`:

    generate(repo_root, repository, *,
             source_revision=None, generated_at=None, **inputs)

* `repo_root` is the corpus checkout the generator scans, as a `Path`.
* `repository` is the repository id the snapshot is for.
* `source_revision` is the source anchor to pin, or `None`, which leaves the
  generator to read the checkout itself.
* `generated_at` is the generation anchor, recorded verbatim when it is given.
* `**inputs` are the further inputs a generator DECLARES that it takes. Each is
  passed only when the caller has a value for it.

The four arguments are the ones openDox's generate verbs already hand a
generator. A governed generator's own extras, such as a project register,
travel as declared inputs. So the seam never drops one, and never names one
either.

THE REGISTRATION POINT sits beside `domain_profile.register()`, in the shape
the product already uses (5.4's own words). A host calls
`opendox.generator_seam.register(<its SnapshotGenerator>)` ONCE, at process
start. openDox's own entry points call `register_default(...)`, which registers
openDox's own generator only where nothing is registered.

THE CONFORMANCE A CONTRIBUTED GENERATOR MUST MEET. `SnapshotGenerator` declares
it, and `generate()` enforces it.

1. It DECLARES THE CONTRACT IT WRITES: the `kind` of every snapshot it answers.
   openDox's own generator writes `NEUTRAL_SNAPSHOT_KIND`, the neutral
   snapshot contract whose schema openDox's own spec leg owns (plan 034's
   T053; R1Q11 (a), `openxFactory#656` comment `5850003126`). A consumer's
   governed generator declares its own. So two generators that write two
   contracts can never both claim to be the one conformant implementation,
   which is the failure 5.4 was raised against.
2. Its operation TAKES THE SEAM'S CALL: the four arguments, and every input it
   declares, EACH ONE OPTIONAL, because the seam passes a declared input only
   when its caller has a value for it. This is checked when the declaration is
   made, wherever the callable's signature can be read. The call is bound once
   with every declared input given and once with none given, and between them
   the two binds cover every call the seam can make.
3. It DECLARES EVERY FURTHER INPUT it reads. An input that it does not declare
   is refused before the generator is called, and never dropped.
4. It ANSWERS A SNAPSHOT OF ITS DECLARED CONTRACT: a `dict` whose `kind` is
   that contract and whose `schema_version` is an integer, which is what a
   validator picks a schema by. Anything else is refused, not handed on.
5. It is DETERMINISTIC over its inputs, as the generate verbs promise (*"the
   deterministic snapshot"*): the same corpus at the same anchors answers the
   same snapshot. Each generator's own suite proves that. The seam does not
   check it again.

REFUSAL, NOT A DEFAULT (4.2's discipline, and `domain_profile`'s). With nothing
registered, `current()` and `generate()` refuse, naming this seam and the
registration call. They never fall back to openDox's own generator, and they
never answer an empty snapshot, which would read exactly like an honest one.

THE ENTRY POINTS REGISTER openDox's OWN GENERATOR WHERE NO HOST HAS (R1Q10
(a), comment `5850003126`, in R1Q3 (a)'s pattern, comment `5817152735`).
`cli.build_parser()`, `cli.main()`, `serve.build_server()` and `serve.main()`
call `register_default(default_generator.GENERATOR)`, beside their
registrations of the default profile and the default home corpus. So, as for
the profile:

* a process that builds nothing still meets `GeneratorNotRegistered`, which is
  the library caller's case;
* a host registration made BEFORE anything is generated from the default
  replaces it;
* AFTER a snapshot has been generated from the default, a host's registration
  is refused as `GeneratorAlreadyRegistered`. One process would otherwise
  write two contracts, and a reader could not tell which snapshot was which.
  This is the same reason `domain_profile` refuses a swap after a build
  (R1Q3 (ii); RN-1 (a), comment `5850003126`);
* WHILE a snapshot is being generated from the default, a host's registration
  is refused too, because that snapshot would come back after the swap;
* a generation that fails, or whose answer the seam refuses, wrote nothing,
  so it records nothing, and a host still replaces the default after it.

ONE REGISTRATION. Registering the same declaration again is a no-op, so an
idempotent host start is not punished. A different declaration over a host's
is refused as `GeneratorAlreadyRegistered`. `unregister()` makes a deliberate
swap explicit.

EACH REGISTRATION KEEPS ITS OWN RECORDS. A generation belongs to the
registration it began under. So a generation still under way when
`unregister()` drops that registration neither holds shut, nor closes, the
window of the registration that follows. That holds even for a later
registration of the same declaration.

ONE LOCK. The registration and its records are kept under one lock. `serve.py`
answers each request on a thread of its own (a `ThreadingHTTPServer`), so a
generation can run beside a registration. `generate()` holds the lock only for
its bookkeeping, and never across the generator's own call. So a slow
generator holds up nobody else, and a generator that itself registers or
generates cannot deadlock the seam.

RESOLVE PER CALL. A caller generates through `generate()`, and does not hold
`current()`'s answer across calls. So every caller in a process answers from
the one registration that exists at the time.

IMPORT WEIGHT. The standard library only. So this module imports with no extra
installed and no sibling present, and it names no sibling.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import inspect
import keyword
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "GeneratorAlreadyRegistered",
    "GeneratorInputRefused",
    "GeneratorNotConformant",
    "GeneratorNotRegistered",
    "GeneratorSeamError",
    "NEUTRAL_SNAPSHOT_KIND",
    "OPERATION_ARGUMENTS",
    "REGISTRATION_CALL",
    "SnapshotGenerator",
    "current",
    "generate",
    "is_registered",
    "name_of",
    "register",
    "register_default",
    "unregister",
]

#: The contract openDox's OWN generator writes: the `kind` of the neutral
#: snapshot, whose schema openDox's spec leg owns (plan 034's T053; R1Q11 (a),
#: `openxFactory#656` comment `5850003126`). It is the `kind` const of that
#: schema, `contracts/schemas/opendox-snapshot.schema.yaml` (openDox-spec#16),
#: and it must stay equal to it. The value is a string in every neutral
#: snapshot, so F5.3's sweep of the snapshot's string values reads it too, and
#: it carries none of the words that sweep forbids.
NEUTRAL_SNAPSHOT_KIND = "opendox-snapshot"

#: The operation's own arguments, in its call order. The first two are
#: positional, and the last two are keywords. A generator's declared inputs may
#: not reuse these names.
OPERATION_ARGUMENTS: tuple[str, ...] = (
    "repo_root", "repository", "source_revision", "generated_at")

#: The ONE call a host makes, quoted verbatim in every refusal, so that a
#: refusal names its remedy rather than its symptom.
REGISTRATION_CALL = (
    "opendox.generator_seam.register(<the host's SnapshotGenerator>)")

#: How much of a `repr` a refusal quotes before it stops being read.
_NAME_LIMIT = 120


class GeneratorSeamError(RuntimeError):
    """A refusal of the generator seam.

    One base for every refusal below, so a verb that generates can report the
    seam's refusals in one clause, as `cli.main()` reports its own."""


class GeneratorNotRegistered(GeneratorSeamError):
    """Nothing is registered: no host's generator, and no entry point's default.

    Raised instead of falling back to openDox's own generator. The default is a
    registration an ENTRY POINT makes (R1Q10 (a), in R1Q3 (a)'s pattern), so
    this is what a process meets when it generates without having built
    anything through an entry point, which is the library caller's case. It is
    also what a process meets after `unregister()`, because the refusal reports
    what is registered NOW and keeps no history."""


class GeneratorAlreadyRegistered(GeneratorSeamError):
    """A second, different generator was registered over a first.

    ONE registration is the contract, as it is for the profile. A process whose
    snapshots came from two generators would write two contracts under one
    name. The entry point's default is replaceable only until a snapshot has
    been generated from it, and not while one is being generated.
    `unregister()` makes a deliberate swap explicit."""


class GeneratorInputRefused(GeneratorSeamError):
    """The registered generator was handed an input it does not declare.

    Refused before the generator is called. A generator that silently ignored
    the input would write a snapshot that looks as though the input had been
    read."""


class GeneratorNotConformant(GeneratorSeamError):
    """A generator broke the conformance this seam declares.

    It answered something other than a snapshot of its declared contract, or
    it was offered as openDox's own default while declaring another contract.
    What it answered is refused, not handed on: the validator and the views
    read a snapshot by its `kind`."""


def _qualified(value: Any) -> str:
    """`module.qualname` for a callable, else a truncated `repr`. Never raises."""
    try:
        module = getattr(value, "__module__", None)
        qualname = getattr(value, "__qualname__", None)
        if isinstance(module, str) and isinstance(qualname, str) and module and qualname:
            return f"{module}.{qualname}"
    except Exception:  # noqa: BLE001 - naming must never out-raise
        pass
    try:
        text = repr(value)
    except Exception:  # noqa: BLE001
        text = ""
    if not text:
        return "an unnameable callable"
    return text if len(text) <= _NAME_LIMIT else text[:_NAME_LIMIT - 1] + "…"


@dataclass(frozen=True, eq=False)
class SnapshotGenerator:
    """ONE generator's declaration: the contract it writes, its operation, and
    the further inputs it takes. It is what `register()` and
    `register_default()` hold.

    `contract` is the `kind` of every snapshot the generator answers.
    `generate` is the operation this module's docstring declares. `inputs`
    names the keyword inputs it reads beyond the operation's own four, and
    defaults to none.

    Construction refuses a declaration the seam could not honour, rather than
    registering one that fails at its first generation. That covers a contract
    that is not a non-empty string, an operation that is not callable, an input
    name that is not an identifier (or is a keyword, a duplicate, or one of the
    operation's own four), and an operation whose signature cannot take the
    seam's call, whether its declared inputs are given or not. Frozen, and
    compared by identity, as `register()` compares registrations."""

    contract: str
    generate: Callable[..., dict]
    inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.contract, str):
            raise TypeError(
                "a SnapshotGenerator declares the contract it writes as a "
                f"string, the kind of every snapshot it answers, not "
                f"{type(self.contract).__name__}")
        if not self.contract or self.contract != self.contract.strip():
            raise ValueError(
                "a SnapshotGenerator's contract is the kind its snapshots carry, "
                f"a non-empty name with no surrounding space, not {self.contract!r}")
        if not callable(self.generate):
            raise TypeError(
                "a SnapshotGenerator's generate is the operation the seam hands "
                f"over, a callable, not {type(self.generate).__name__}")
        if not isinstance(self.inputs, tuple) or not all(
                isinstance(name, str) for name in self.inputs):
            raise TypeError(
                "a SnapshotGenerator declares its further inputs as a tuple of "
                f"names, not {self.inputs!r}")
        bad = sorted({name for name in self.inputs
                      if not name.isidentifier() or keyword.iskeyword(name)})
        reused = sorted(set(self.inputs) & set(OPERATION_ARGUMENTS))
        repeated = sorted({name for name in self.inputs
                           if self.inputs.count(name) > 1})
        if bad or reused or repeated:
            raise ValueError(
                "a SnapshotGenerator's inputs name keyword arguments its "
                "operation takes beyond the operation's own four "
                f"({', '.join(OPERATION_ARGUMENTS)}). Refused: "
                f"not an identifier {bad}, one of the four {reused}, "
                f"repeated {repeated}")
        self._refuse_an_operation_that_cannot_take_the_call()

    def _refuse_an_operation_that_cannot_take_the_call(self) -> None:
        try:
            signature = inspect.signature(self.generate)
        except (TypeError, ValueError):
            # The signature cannot be read (some builtins). The seam's call is
            # then checked when it is first made, and not here.
            return
        # `generate()` passes a declared input only when its caller has a value
        # for it. So the call is bound with every declared input given, which
        # proves that each is taken, and with none given, which proves that
        # each is optional. Every call the seam can make lies between the two.
        calls = [("", dict.fromkeys(self.inputs))]
        if self.inputs:
            calls.append((" with none of its declared inputs given", {}))
        for when, given in calls:
            try:
                signature.bind(Path("."), "repository", source_revision=None,
                               generated_at=None, **given)
            except TypeError as exc:
                raise TypeError(
                    f"{_qualified(self.generate)} cannot take the generator "
                    f"seam's call{when}, generate(repo_root, repository, *, "
                    "source_revision=, generated_at="
                    + "".join(f", {name}=" for name in given)
                    + f"): {exc}. A contributed generator takes the operation's "
                    "own four arguments and every input it declares, and each "
                    "declared input is optional, because the seam passes one "
                    "only when its caller has a value for it") from None


#: THE one registration, a host's or the entry point's default, or `None`.
_registered: SnapshotGenerator | None = None

#: Whether `_registered` is the default an ENTRY POINT registered
#: (`register_default()`), rather than a host's own `register()`.
_is_default: bool = False

#: Whether a snapshot has been generated from THIS registration of that
#: default, meaning that its operation has answered a snapshot the seam handed
#: back. `generate()` sets it once that snapshot has come back. A generation
#: that failed, or whose answer the seam refused, wrote nothing, and so records
#: nothing.
_generated_from_default: bool = False

#: How many generations from THIS registration of that default are under way:
#: begun, and not yet answered or failed. While one is, a host's registration
#: is refused, as it is after one, because the snapshot being generated would
#: come back after the swap.
_default_generations_under_way: int = 0

#: Which registration is current. Every change of registration moves it on:
#: `register()`, `register_default()` where it registers, and `unregister()`.
#: A generation carries the serial it began under, and when it ends it touches
#: the two records above only if that registration is still the current one.
#: So a change of registration starts both records afresh, and a generation
#: that outlived its registration records nothing against the next.
_registration_serial: int = 0

#: Guards the five above. It is held only for bookkeeping, and never across a
#: generator's own call.
_lock = threading.Lock()


def _begin_a_registration(generator: SnapshotGenerator | None,
                          is_default: bool) -> None:
    """Make `generator` the registration (or none), with records of its own.
    The one place the registration changes. The caller holds `_lock`."""
    global _registered, _is_default, _generated_from_default
    global _default_generations_under_way, _registration_serial
    _registration_serial += 1
    _registered = generator
    _is_default = is_default
    _generated_from_default = False
    _default_generations_under_way = 0


def name_of(generator: Any) -> str:
    """A generator's most nameable name, with its contract, for a refusal.

    Public, as `domain_profile.name_of()` is, so a host's own refusal can name a
    generator the same way. It never raises: a refusal that fails while
    formatting itself replaces the reader's problem with a worse one."""
    if isinstance(generator, SnapshotGenerator):
        return f"{_qualified(generator.generate)} (writing {generator.contract!r})"
    return _qualified(generator)


def _require_a_declaration(generator: Any, call: str) -> None:
    if not isinstance(generator, SnapshotGenerator):
        raise TypeError(
            f"{call} takes a SnapshotGenerator, the declaration of a generator's "
            "contract, operation and inputs, not "
            f"{type(generator).__name__}. A host with no generator of its own "
            "does not register one: the seam then answers with openDox's own "
            "generator where an entry point registered it, and refuses where "
            "none did.")


def register(generator: SnapshotGenerator) -> SnapshotGenerator:
    """THE one registration. A host calls this at process start.

    Returns the generator, so a host can register it and hold it in one
    expression.

    Registering the SAME declaration again is a no-op. A DIFFERENT one over a
    host's registration raises `GeneratorAlreadyRegistered`. Over the entry
    point's default it REPLACES the default while no snapshot has been
    generated from it and none is being generated. It is refused once one has
    been, or while one is. Either way the host ends up holding the one
    registration, or knows why it does not."""
    _require_a_declaration(generator, "register()")
    with _lock:
        held = _registered
        if held is generator:
            # The same object again: a no-op, before any bookkeeping is touched.
            return generator
        over_a_host = held is not None and not _is_default
        why = ""
        if held is not None and _is_default:
            if _default_generations_under_way:
                why = "a snapshot is being generated from it now"
            elif _generated_from_default:
                why = "a snapshot has already been generated from it"
        if not over_a_host and not why:
            _begin_a_registration(generator, is_default=False)
            return generator
    # Named outside the lock: naming a generator can run its own code.
    if over_a_host:
        raise GeneratorAlreadyRegistered(
            f"a host's generator is already registered at openDox's "
            f"generator seam ({name_of(held)}), and "
            f"{name_of(generator)} would replace it. Registration happens "
            "ONCE, at process start: one process generating through two "
            "generators would write two contracts, and a reader could not "
            "tell which snapshot was which. Call "
            "opendox.generator_seam.unregister() first if the swap is "
            "deliberate.")
    raise GeneratorAlreadyRegistered(
        f"openDox's own default generator ({name_of(held)}) is "
        "registered, because an entry point registered it where no host "
        f"had, and {why}, so "
        f"{name_of(generator)} cannot replace it now. A swap would leave "
        "one process writing two contracts. A host's generator replaces "
        "the default only BEFORE anything is generated from it, as a "
        "host's profile replaces the default profile only before a build "
        "(R1Q3 (ii), openxFactory#656 comment 5817152735; RN-1 (a), "
        "comment 5850003126). So register the host's generator at "
        "process start, ahead of the first generation. Call "
        "opendox.generator_seam.unregister() first if the swap is "
        "deliberate.")


def register_default(generator: SnapshotGenerator) -> SnapshotGenerator:
    """AN ENTRY POINT'S registration of openDox's OWN generator (R1Q10 (a)).

    `cli.build_parser()`, `cli.main()`, `serve.build_server()` and
    `serve.main()` call this with `default_generator.GENERATOR`. It registers
    `generator` ONLY where nothing is registered, and leaves a host's
    registration, or a default already registered, exactly as it is. Returns
    whatever is registered afterwards.

    It is NOT for hosts. A host calls `register()`. The conformance clause holds
    openDox's own generator to the neutral contract, so a declaration that
    writes another contract is refused as `GeneratorNotConformant`, whether or
    not anything is registered."""
    _require_a_declaration(generator, "register_default()")
    if generator.contract != NEUTRAL_SNAPSHOT_KIND:
        raise GeneratorNotConformant(
            "register_default() registers openDox's OWN generator, which writes "
            f"the neutral snapshot contract {NEUTRAL_SNAPSHOT_KIND!r}, and "
            f"{name_of(generator)} declares another. A host's generator is "
            f"registered with {REGISTRATION_CALL}.")
    with _lock:
        if _registered is None:
            _begin_a_registration(generator, is_default=True)
        return _registered


def unregister() -> None:
    """Drop the registration, a host's or the entry point's default.

    For test isolation and for a host tearing down. The registration's records
    go with it: whether a snapshot was generated from the default, and how many
    generations from it are under way. A generation still under way is not
    stopped, and its caller still gets its snapshot. But it belongs to the
    registration that was dropped, so when it ends it records nothing against
    whatever is registered next, even a later registration of the same
    declaration."""
    with _lock:
        _begin_a_registration(None, is_default=False)


def is_registered() -> bool:
    """Is a generator registered? Answers without resolving or refusing."""
    return _registered is not None


def current() -> SnapshotGenerator:
    """The registered generator, or a refusal naming this seam and its call.

    It answers what is registered: a host's generator, or the default an entry
    point registered. It never falls back to the default itself, and asking
    records nothing. Only a generation closes the default's window, while it
    runs and once it has answered.

    It reads the registration ONCE. So a registration another thread drops
    while it answers never makes it answer `None`: it answers the registration
    it checked. It takes no lock of its own, because `generate()` calls it
    while holding the seam's lock."""
    registered = _registered
    if registered is None:
        raise GeneratorNotRegistered(
            "no snapshot generator is registered at openDox's generator seam "
            "(opendox.generator_seam), so there is nothing to generate a "
            "snapshot with, and nothing is generated. openDox ships a generator "
            "of its own, opendox.default_generator, but it is a registration an "
            "ENTRY POINT makes and never a fallback here (R1Q10 (a), "
            "openxFactory#656 comment 5850003126, in R1Q3 (a)'s pattern). "
            "`cli.build_parser()`, `cli.main()`, `serve.build_server()` and "
            "`serve.main()` register it where no host has. Nothing is "
            "registered now, so either nothing in this process has been built "
            "through one of them, or opendox.generator_seam.unregister() has "
            "dropped the registration since. A host that contributes its own "
            "generator registers it at process start with\n\n    "
            + REGISTRATION_CALL + "\n\nbefore the first generation.")
    return registered


def generate(repo_root: Path | str, repository: str, *,
             source_revision: str | None = None,
             generated_at: str | None = None,
             **inputs: Any) -> dict:
    """Generate a snapshot through the registered generator. This is THE
    operation the seam hands over, called and checked.

    An input given as `None` means "not given", and it is not passed, so a verb
    can hand over its options whether or not they were set. Any other input the
    registered generator does not declare is refused before the generator is
    called (`GeneratorInputRefused`). What the generator answers is handed back
    only if it is a snapshot of the contract the generator declared
    (`GeneratorNotConformant`). With nothing registered this refuses as
    `current()` does.

    A generation from the entry point's default holds the default's window shut
    while it runs. Once its snapshot has come back, it closes the window for
    good (see `register()`). A generation that fails, or whose answer is
    refused, reopens it."""
    global _default_generations_under_way
    given = {name: value for name, value in inputs.items() if value is not None}
    with _lock:
        # One hold for the resolve and the mark, so that no registration can
        # land between the generator this call resolves and its call.
        generator = current()
        undeclared = sorted(set(given) - set(generator.inputs))
        from_default = _is_default and not undeclared
        serial = _registration_serial
        if from_default:
            _default_generations_under_way += 1
    if undeclared:
        declared = ", ".join(generator.inputs) or "none"
        raise GeneratorInputRefused(
            f"{name_of(generator)} declares the inputs ({declared}) beyond the "
            f"operation's own four, and was handed {', '.join(undeclared)}. An "
            "input a generator does not declare is refused rather than dropped: "
            "a generator that silently ignored it would write a snapshot that "
            "looks as though the input had been read.")
    answered = False
    try:
        snapshot = generator.generate(
            Path(repo_root), repository, source_revision=source_revision,
            generated_at=generated_at, **given)
        _refuse_a_snapshot_that_does_not_conform(generator, snapshot)
        answered = True
    finally:
        if from_default:
            _end_a_generation_from_the_default(serial, answered)
    return snapshot


def _end_a_generation_from_the_default(serial: int, answered: bool) -> None:
    """Take a generation from the default off the count of those under way. If
    it answered a snapshot the seam handed back, record that one was generated.
    Both happen only while the registration it began under (`serial`) is still
    the current one. A registration dropped since took its records with it. So
    a generation that outlived its registration touches nothing, and records
    nothing against what was registered after it."""
    global _default_generations_under_way, _generated_from_default
    with _lock:
        if serial != _registration_serial:
            return
        _default_generations_under_way -= 1
        if answered:
            _generated_from_default = True


def _refuse_a_snapshot_that_does_not_conform(generator: SnapshotGenerator,
                                             snapshot: Any) -> None:
    if not isinstance(snapshot, dict):
        raise GeneratorNotConformant(
            f"{name_of(generator)} answered {type(snapshot).__name__}, not a "
            "snapshot. The seam hands on only a snapshot, a dict, and an answer "
            "it cannot read is refused rather than taken for one.")
    kind = snapshot.get("kind")
    if kind != generator.contract:
        raise GeneratorNotConformant(
            f"{name_of(generator)} declares that it writes "
            f"{generator.contract!r}, and it answered a snapshot whose kind is "
            f"{kind!r}. The seam hands back only a snapshot of the contract its "
            "generator declared. The validator and the views read a snapshot "
            "by its kind, so a generator whose output drifted from its "
            "declaration would be two contracts under one name.")
    version = snapshot.get("schema_version")
    if type(version) is not int:
        raise GeneratorNotConformant(
            f"{name_of(generator)} answered a {generator.contract!r} snapshot "
            f"whose schema_version is {version!r}, not an integer. A validator "
            "picks a schema by kind and version, so a snapshot that does not "
            "say which version of its contract it is cannot be checked.")
