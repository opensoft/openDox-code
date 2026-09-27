"""The generator seam, held to 5.4 of openxFactory's
`add-neutral-product-standalone-operability` (plan 034, T052).

Box 5.4 reads *"DECLARE THE GENERATOR SEAM — it does not exist and
`CorpusAdapter` is not it"*. It asks for the operation handed over, the
registration point beside `domain_profile.register()`, and the conformance a
contributed generator must satisfy. Plan 034's T052 adds that the conformance
clause names T053's neutral snapshot kind for openDox's own generator, and that
the entry points register openDox's own generator where no host has (R1Q10 (a),
`openxFactory#656` comment `5850003126`, in R1Q3 (a)'s pattern). These are
T052's seam tests.

WHAT IT ASSERTS, AND WHY EACH IS HERE

1. NOTHING IS REGISTERED BY AN IMPORT, AND THE SEAM MAKES NO REACH. A fresh
   process that imports both modules and both entry points registers nothing,
   and it meets the refusal. The two modules import with every sibling
   blocked, pull in no third-party module, and name no sibling in any import,
   late or not.
2. NOTHING REGISTERED REFUSES, NAMING THE SEAM AND THE CALL (4.2's
   discipline). It never falls back to openDox's own generator.
3. THE DECLARATION IS CHECKED WHEN IT IS MADE. A contract that is not a name,
   an operation that is not callable or cannot take the seam's call (with its
   declared inputs given, or with none of them given), and an input that is not
   a name beyond the operation's own four are refused before anything is
   registered.
4. THE OPERATION IS HANDED OVER AND ITS ANSWER CHECKED. The registered
   generator receives the four arguments and its declared inputs. An
   undeclared input is refused before the call. A `None` input is not passed.
   Only a snapshot of the declared contract comes back.
5. ONE REGISTRATION. The same declaration twice is a no-op, and a second host
   is refused.
6. THE ENTRY POINTS' DEFAULT, in R1Q3 (a)'s pattern. openDox's own generator
   writes the neutral kind and takes no input. `register_default()` registers
   it only where nothing is, and holds it to the neutral contract. A host
   replaces it before a generation, and after one that wrote nothing. A host is
   refused while a generation runs, and after one that wrote a snapshot. A
   generator may register or generate from inside its own call without
   deadlocking the seam. What the default generates is T054's neutral
   projection, and `tests/test_neutral_projection.py` holds it.
7. EACH ENTRY POINT REGISTERS IT. `cli.build_parser()` and `cli.main()` run for
   real. `serve.build_server()` and `serve.main()` still cannot run in a lone
   checkout (research R7), so their registration is executed from their own
   source lines, as `tests/test_authoring_seam.py` does for the home corpus.
8. `CorpusAdapter` STAYS CLOSED AT SIX MEMBERS.

`--noconftest` SAFE. The autouse fixture below saves and restores the three
registries the entry points write, so no case depends on the root conftest or
leaves a registration behind.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import ast
import inspect
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from opendox import corpus_adapter, default_generator, domain_profile
from opendox import generator_seam as gs

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
CLI = SRC / "opendox" / "cli.py"
SERVE = SRC / "opendox" / "serve.py"

#: The seam's two modules.
SEAM_MODULES = {"opendox.generator_seam": SRC / "opendox" / "generator_seam.py",
                "opendox.default_generator": SRC / "opendox" / "default_generator.py"}

#: The four packages a neutral openDox must import without (#1144's F2.1).
SIBLINGS = ("openxdox", "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")

#: F5.3's declared vocabulary, verbatim from #1144's `tasks.md`. F5.3 reads
#: every string value of the neutral snapshot, and the snapshot's `kind` is one.
F5_3_WORDS = ("brainstorm", "staged", "draft", "ratified", "standard",
              "superseded", "retired", "record", "openspec", "proposal.md",
              "tasks.md", "design.md", "added requirements",
              "modified requirements")


@pytest.fixture(autouse=True)
def _isolated_registries():
    """Every case starts with NO generator registered, and PUTS BACK what it found.

    The three registries an entry point writes are process-global by design:
    the generator seam, the profile and the home corpus. Each is saved whole,
    because each keeps more than its registration (whether it is the entry
    point's default, and whether anything was generated or built from it, or
    is being generated), and a restore through `register()` would hand an entry
    point's default back as a host's.
    """
    seam = (gs._registered, gs._is_default, gs._generated_from_default,
            gs._default_generations_under_way)
    profile = (domain_profile._registered, domain_profile._is_default,
               domain_profile._built_from_default)
    home = corpus_adapter._home_factory
    gs.unregister()
    yield
    (gs._registered, gs._is_default, gs._generated_from_default,
     gs._default_generations_under_way) = seam
    (domain_profile._registered, domain_profile._is_default,
     domain_profile._built_from_default) = profile
    corpus_adapter._home_factory = home


def _declared(contract: str = "stand-in-snapshot", *, inputs: tuple = (),
              answer=None):
    """A stand-in generator's declaration, and the list its operation records.

    The operation takes exactly the seam's call. It answers `answer` when one
    is given, and otherwise a minimal snapshot of `contract`."""
    calls: list[dict] = []

    def operation(repo_root, repository, *, source_revision=None,
                  generated_at=None, **extra):
        calls.append({"repo_root": repo_root, "repository": repository,
                      "source_revision": source_revision,
                      "generated_at": generated_at, **extra})
        if answer is not None:
            return answer
        return {"schema_version": 1, "kind": contract, "repository": repository}

    return gs.SnapshotGenerator(contract=contract, generate=operation,
                                inputs=inputs), calls


def _fresh_process(program: str) -> subprocess.CompletedProcess:
    """`program` in a fresh interpreter, with this checkout's `src` first. The
    registry is process-global, so a case about what a PROCESS meets runs in
    one of its own. So does a case that could deadlock the seam's lock: the
    time limit then fails it, where in this process it would hang the suite."""
    return subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(SRC)!r})\n"
         + textwrap.dedent(program)],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120)


# --------------------------------------------------------------------------
# 1 — nothing is registered by an import, and the seam makes no reach
# --------------------------------------------------------------------------

def test_importing_the_seam_and_the_entry_points_registers_nothing() -> None:
    """The library caller's case. A process that builds nothing still refuses,
    because openDox's own generator is a registration an entry point MAKES."""
    done = _fresh_process("""
        import opendox.cli, opendox.serve, opendox.default_generator
        from opendox import generator_seam as gs
        assert gs.is_registered() is False, "an import registered a generator"
        for call in (gs.current, lambda: gs.generate(".", "fixture")):
            try:
                call()
            except gs.GeneratorNotRegistered:
                continue
            raise AssertionError(f"{call} answered with nothing registered")
        print("refused")
    """)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "refused"


def test_the_seam_imports_with_no_sibling_and_no_third_party_module() -> None:
    """Both modules import with the four siblings blocked at the finder, and
    what they add to `sys.modules` is openDox's own or the standard library's."""
    block = "".join(f"sys.modules[{name!r}] = None\n" for name in SIBLINGS)
    done = _fresh_process(block + textwrap.dedent("""
        before = set(sys.modules)
        import opendox.generator_seam, opendox.default_generator
        added = {name.split(".")[0] for name in set(sys.modules) - before}
        print(sorted(added - set(sys.stdlib_module_names) - {"opendox"}))
    """))
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]", (
        f"the seam pulls in a module that is neither openDox's nor the "
        f"standard library's: {done.stdout.strip()}")


def _named_imports(node: ast.AST) -> list[str]:
    """The module names an import node, or an `import_module`/`__import__`
    call with a literal name, reaches. This is #1144's F4.1 scan's own reading."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.level == 0 and node.module else []
    if (isinstance(node, ast.Call) and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and getattr(node.func, "attr", getattr(node.func, "id", ""))
            in ("import_module", "__import__")):
        return [node.args[0].value]
    return []


@pytest.mark.parametrize("module", sorted(SEAM_MODULES))
def test_the_seam_names_no_sibling_in_any_import_late_or_not(module: str) -> None:
    """No import anywhere in either module, at module scope or inside a
    function body, names a sibling. A late one is still a reach, and it is the
    class F4.1's scan exists for."""
    tree = ast.parse(SEAM_MODULES[module].read_text(encoding="utf-8"))
    reaches = sorted({name for node in ast.walk(tree)
                      for name in _named_imports(node)
                      if any(name == s or name.startswith(s + ".")
                             for s in SIBLINGS)})
    assert reaches == [], f"{module} reaches {reaches}"


# --------------------------------------------------------------------------
# 2 — nothing registered: the seam refuses, naming itself and the call (4.2)
# --------------------------------------------------------------------------

def test_nothing_registered_refuses_naming_the_seam_and_the_call() -> None:
    with pytest.raises(gs.GeneratorNotRegistered) as caught:
        gs.current()
    message = str(caught.value)
    for expected in (gs.REGISTRATION_CALL, "opendox.generator_seam",
                     "opendox.default_generator", "ENTRY POINT",
                     "cli.build_parser()", "cli.main()",
                     "serve.build_server()", "serve.main()",
                     "R1Q10 (a)", "5850003126", "unregister()"):
        assert expected in message, f"the refusal no longer says {expected!r}"


def test_generate_with_nothing_registered_refuses_as_the_seam(tmp_path) -> None:
    """Never a fallback to openDox's own generator, and never an empty snapshot."""
    with pytest.raises(gs.GeneratorNotRegistered) as caught:
        gs.generate(tmp_path, "fixture")
    assert isinstance(caught.value, gs.GeneratorSeamError)
    assert gs.is_registered() is False


# --------------------------------------------------------------------------
# 3 — the declaration is checked when it is made
# --------------------------------------------------------------------------

@pytest.mark.parametrize("contract,error", (
    (None, TypeError), (3, TypeError), ("", ValueError), (" padded ", ValueError)))
def test_a_declaration_names_the_contract_it_writes(contract, error) -> None:
    with pytest.raises(error):
        gs.SnapshotGenerator(contract=contract, generate=default_generator.generate)


@pytest.mark.parametrize("operation", (None, "not callable", 3))
def test_a_declaration_carries_a_callable_operation(operation) -> None:
    with pytest.raises(TypeError):
        gs.SnapshotGenerator(contract="stand-in-snapshot", generate=operation)


@pytest.mark.parametrize("inputs,error", (
    (["project_register_source"], TypeError),
    ((1,), TypeError),
    (("not an identifier",), ValueError),
    (("class",), ValueError),
    (("repository",), ValueError),
    (("generated_at",), ValueError),
    (("register", "register"), ValueError)))
def test_declared_inputs_are_names_beyond_the_operations_own_four(inputs,
                                                                  error) -> None:
    def operation(repo_root, repository, **kw):
        return {}

    with pytest.raises(error):
        gs.SnapshotGenerator(contract="stand-in-snapshot", generate=operation,
                             inputs=inputs)


def test_an_operation_that_cannot_take_the_seams_call_is_refused() -> None:
    """Conformance clause 2, checked where the signature can be read."""
    with pytest.raises(TypeError) as caught:
        gs.SnapshotGenerator(contract="stand-in-snapshot",
                             generate=lambda repo_root, repository: {})
    assert "cannot take the generator seam's call" in str(caught.value)

    def takes_the_four(repo_root, repository, *, source_revision=None,
                       generated_at=None):
        return {}

    with pytest.raises(TypeError):
        gs.SnapshotGenerator(contract="stand-in-snapshot",
                             generate=takes_the_four,
                             inputs=("project_register_source",))


def test_a_declared_input_the_operation_cannot_do_without_is_refused() -> None:
    """Conformance clause 2: each declared input is optional. The seam passes a
    declared input only when its caller has a value for it. So an operation
    that REQUIRES one would take the call while the option is set, and fail
    with a raw `TypeError` the first time it is not. Such an operation is
    refused when it is declared, whether it requires the input by keyword or by
    position."""
    def requires_it_by_keyword(repo_root, repository, *, project_register_source,
                               source_revision=None, generated_at=None):
        return {}

    def requires_it_by_position(repo_root, repository, project_register_source,
                                *, source_revision=None, generated_at=None):
        return {}

    for operation in (requires_it_by_keyword, requires_it_by_position):
        with pytest.raises(TypeError) as caught:
            gs.SnapshotGenerator(contract="stand-in-snapshot", generate=operation,
                                 inputs=("project_register_source",))
        message = str(caught.value)
        for expected in ("with none of its declared inputs given",
                         "project_register_source", "optional"):
            assert expected in message, (
                f"{operation.__name__}: the refusal no longer says {expected!r}")

    def takes_it_optionally(repo_root, repository, project_register_source=None,
                            *, source_revision=None, generated_at=None):
        return {}

    gs.SnapshotGenerator(contract="stand-in-snapshot", generate=takes_it_optionally,
                         inputs=("project_register_source",))


def test_a_governed_generators_shape_is_declarable(tmp_path) -> None:
    """A consumer's generator keeps its own signature and declares its extras.

    This is the call shape of openXdox's `generator.generate_snapshot`, as T059
    will declare it, restated here because openDox may not import it. Its
    keyword-only test hooks stay undeclared, and so the seam never passes them.
    It generates with its declared inputs unset and with one of them set.
    """
    def generate_snapshot(repo_root, repository, *, source_revision=None,
                          generated_at=None, git=None, generator_version="v",
                          project_register_source=None, possibles_source=None,
                          excluded_documents=None):
        return {"schema_version": 1, "kind": "governed-stand-in",
                "register": project_register_source,
                "possibles": possibles_source, "git": git}

    declared = gs.SnapshotGenerator(
        contract="governed-stand-in", generate=generate_snapshot,
        inputs=("project_register_source", "possibles_source"))
    assert declared.inputs == ("project_register_source", "possibles_source")
    gs.register(declared)
    unset = gs.generate(tmp_path, "fixture", project_register_source=None,
                        possibles_source=None)
    assert (unset["register"], unset["possibles"], unset["git"]) == (None, None, None)
    one_set = gs.generate(tmp_path, "fixture",
                          project_register_source=Path("register.yaml"))
    assert (one_set["register"], one_set["possibles"]) == (Path("register.yaml"), None)


@pytest.mark.parametrize("candidate", (None, "a generator", default_generator.generate))
def test_only_a_declaration_is_registered(candidate) -> None:
    for call in (gs.register, gs.register_default):
        with pytest.raises(TypeError):
            call(candidate)
    assert gs.is_registered() is False


# --------------------------------------------------------------------------
# 4 — the operation handed over, and its answer checked
# --------------------------------------------------------------------------

def test_the_registered_generator_is_handed_the_operation(tmp_path) -> None:
    declared, calls = _declared()
    assert gs.register(declared) is declared
    assert gs.current() is declared
    snapshot = gs.generate(str(tmp_path), "fixture", source_revision="abc123",
                           generated_at="2026-09-27T00:00:00Z")
    assert calls == [{"repo_root": tmp_path, "repository": "fixture",
                      "source_revision": "abc123",
                      "generated_at": "2026-09-27T00:00:00Z"}]
    assert isinstance(calls[0]["repo_root"], Path), "repo_root is handed over as a Path"
    assert snapshot == {"schema_version": 1, "kind": "stand-in-snapshot",
                        "repository": "fixture"}


def test_a_declared_input_is_passed_and_an_undeclared_one_refused(tmp_path) -> None:
    declared, calls = _declared(inputs=("project_register_source",))
    gs.register(declared)
    gs.generate(tmp_path, "fixture",
                project_register_source=Path("register.yaml"))
    assert calls[-1]["project_register_source"] == Path("register.yaml")

    with pytest.raises(gs.GeneratorInputRefused) as caught:
        gs.generate(tmp_path, "fixture", possibles_source=Path("possibles.yaml"))
    assert len(calls) == 1, "the generator was called with an undeclared input"
    message = str(caught.value)
    assert "possibles_source" in message and "project_register_source" in message


def test_an_input_given_as_none_is_not_passed(tmp_path) -> None:
    """So a verb can hand over its options whether or not they were set."""
    declared, calls = _declared()
    gs.register(declared)
    gs.generate(tmp_path, "fixture", project_register_source=None,
                possibles_source=None)
    assert set(calls[-1]) == {"repo_root", "repository", "source_revision",
                              "generated_at"}


@pytest.mark.parametrize("answer", (
    ["not", "a", "snapshot"],
    "a snapshot",
    {"schema_version": 1, "kind": "another-snapshot"},
    {"schema_version": 1},
    {"kind": "stand-in-snapshot"},
    {"schema_version": "1", "kind": "stand-in-snapshot"},
    {"schema_version": True, "kind": "stand-in-snapshot"},
    {"schema_version": 1.0, "kind": "stand-in-snapshot"}))
def test_only_a_snapshot_of_the_declared_contract_comes_back(answer,
                                                              tmp_path) -> None:
    """Conformance clause 4. Two generators writing two contracts can then
    never both answer for one of them."""
    declared, calls = _declared(answer=answer)
    gs.register(declared)
    with pytest.raises(gs.GeneratorNotConformant) as caught:
        gs.generate(tmp_path, "fixture")
    assert calls, "the generator was never called"
    assert "stand-in-snapshot" in str(caught.value)


# --------------------------------------------------------------------------
# 5 — one registration
# --------------------------------------------------------------------------

def test_registering_the_same_declaration_twice_is_a_no_op() -> None:
    declared, _ = _declared()
    assert gs.register(declared) is declared
    assert gs.register(declared) is declared
    assert gs.current() is declared


def test_a_second_different_host_generator_is_refused() -> None:
    first, _ = _declared("first-snapshot")
    second, _ = _declared("second-snapshot")
    gs.register(first)
    with pytest.raises(gs.GeneratorAlreadyRegistered) as caught:
        gs.register(second)
    message = str(caught.value)
    for expected in ("first-snapshot", "second-snapshot", "ONCE",
                     "unregister()"):
        assert expected in message, f"the refusal no longer says {expected!r}"
    assert gs.current() is first


def test_unregister_makes_a_deliberate_swap_explicit() -> None:
    first, _ = _declared("first-snapshot")
    second, _ = _declared("second-snapshot")
    gs.register(first)
    gs.unregister()
    assert gs.is_registered() is False
    assert gs.register(second) is second


# --------------------------------------------------------------------------
# 6 — the entry points' default (R1Q10 (a), in R1Q3 (a)'s pattern)
# --------------------------------------------------------------------------

def test_openDoxs_own_generator_writes_the_neutral_contract() -> None:
    """The conformance clause names T053's neutral kind for openDox's own."""
    declared = default_generator.GENERATOR
    assert isinstance(declared, gs.SnapshotGenerator)
    assert declared.contract == gs.NEUTRAL_SNAPSHOT_KIND
    assert declared.inputs == ()
    assert declared.generate is default_generator.generate
    assert list(inspect.signature(default_generator.generate).parameters) == \
        list(gs.OPERATION_ARGUMENTS)


def test_the_neutral_kind_carries_no_word_f5_3_forbids() -> None:
    """The kind is a string value of every neutral snapshot, and F5.3 sweeps
    every string value, lowercased, for its declared words."""
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in F5_3_WORDS) + r")\b")
    assert not pattern.search(gs.NEUTRAL_SNAPSHOT_KIND.lower()), \
        gs.NEUTRAL_SNAPSHOT_KIND


def test_register_default_registers_only_where_nothing_is_registered() -> None:
    host, _ = _declared("host-snapshot")
    gs.register(host)
    assert gs.register_default(default_generator.GENERATOR) is host
    gs.unregister()
    assert gs.register_default(default_generator.GENERATOR) is \
        default_generator.GENERATOR
    other_default, _ = _declared(gs.NEUTRAL_SNAPSHOT_KIND)
    assert gs.register_default(other_default) is default_generator.GENERATOR


def test_register_default_holds_the_default_to_the_neutral_contract() -> None:
    """An entry point's default is openDox's own, so it writes the neutral kind.
    Another contract is refused, whether or not anything is registered."""
    governed, _ = _declared("governed-stand-in")
    with pytest.raises(gs.GeneratorNotConformant) as caught:
        gs.register_default(governed)
    assert gs.NEUTRAL_SNAPSHOT_KIND in str(caught.value)
    assert gs.is_registered() is False
    host, _ = _declared("host-snapshot")
    gs.register(host)
    with pytest.raises(gs.GeneratorNotConformant):
        gs.register_default(governed)
    assert gs.current() is host


def test_a_host_replaces_a_default_nothing_was_generated_from() -> None:
    assert gs.register_default(default_generator.GENERATOR) is \
        default_generator.GENERATOR
    host, _ = _declared("host-snapshot")
    assert gs.register(host) is host
    assert gs.current() is host


def test_a_host_after_a_generation_from_the_default_is_refused(tmp_path) -> None:
    """R1Q3 (ii)'s reason, for the generator: one process would then write two
    contracts. A stand-in writes the neutral kind here, because openDox's own
    projection is T054's."""
    stand_in_default, _ = _declared(gs.NEUTRAL_SNAPSHOT_KIND)
    gs.register_default(stand_in_default)
    gs.generate(tmp_path, "fixture")
    host, _ = _declared("host-snapshot")
    with pytest.raises(gs.GeneratorAlreadyRegistered) as caught:
        gs.register(host)
    message = str(caught.value)
    for expected in ("default generator", "generated", "BEFORE", "R1Q3 (ii)",
                     "RN-1 (a)", "5850003126", "unregister()"):
        assert expected in message, f"the refusal no longer says {expected!r}"
    assert gs.current() is stand_in_default


def test_asking_or_being_refused_is_not_a_generation(tmp_path) -> None:
    """Only a generation closes the default's window. Asking which generator is
    registered does not, and nor does an input refused before the call."""
    stand_in_default, calls = _declared(gs.NEUTRAL_SNAPSHOT_KIND)
    gs.register_default(stand_in_default)
    assert gs.is_registered() is True
    assert gs.current() is stand_in_default
    gs.name_of(gs.current())
    with pytest.raises(gs.GeneratorInputRefused):
        gs.generate(tmp_path, "fixture", project_register_source=Path("r.yaml"))
    assert calls == []
    host, _ = _declared("host-snapshot")
    assert gs.register(host) is host


def test_unregister_clears_the_default_and_its_generation(tmp_path) -> None:
    stand_in_default, _ = _declared(gs.NEUTRAL_SNAPSHOT_KIND)
    gs.register_default(stand_in_default)
    gs.generate(tmp_path, "fixture")
    gs.unregister()
    host, _ = _declared("host-snapshot")
    assert gs.register(host) is host


@pytest.mark.parametrize("failure", ("raises", "answers another kind"))
def test_a_generation_from_the_default_that_wrote_nothing_is_not_a_generation(
        failure: str, tmp_path) -> None:
    """A generation that fails, or whose answer the seam refuses, wrote no
    snapshot, so it leaves the default's window open. A host still replaces the
    default after it, and nothing is left counted as under way."""
    if failure == "raises":
        def operation(repo_root, repository, *, source_revision=None,
                      generated_at=None):
            raise OSError("the checkout is not there")

        stand_in_default = gs.SnapshotGenerator(
            contract=gs.NEUTRAL_SNAPSHOT_KIND, generate=operation)
        expected = OSError
    else:
        stand_in_default, _ = _declared(
            gs.NEUTRAL_SNAPSHOT_KIND,
            answer={"schema_version": 1, "kind": "another-snapshot"})
        expected = gs.GeneratorNotConformant
    gs.register_default(stand_in_default)
    with pytest.raises(expected):
        gs.generate(tmp_path, "fixture")
    assert gs._default_generations_under_way == 0
    host, _ = _declared("host-snapshot")
    assert gs.register(host) is host


#: A program for a fresh process. A generation from the default runs on a
#: thread of its own, as a request does in `serve.py`'s `ThreadingHTTPServer`.
#: A host's registration is tried while it runs and again once it has ended.
#: `OUTCOME` is how the generation ends.
_UNDER_WAY = """
    import threading
    from opendox import generator_seam as gs
    OUTCOME = OUTCOME_VALUE
    started, release = threading.Event(), threading.Event()

    def operation(repo_root, repository, *, source_revision=None, generated_at=None):
        started.set()
        release.wait(30)
        if OUTCOME == "raises":
            raise RuntimeError("the checkout went away mid-generation")
        kind = gs.NEUTRAL_SNAPSHOT_KIND if OUTCOME == "answers" else "another-snapshot"
        return {"schema_version": 1, "kind": kind}

    def host_operation(repo_root, repository, *, source_revision=None, generated_at=None):
        return {"schema_version": 1, "kind": "host-snapshot"}

    host = gs.SnapshotGenerator(contract="host-snapshot", generate=host_operation)
    gs.register_default(gs.SnapshotGenerator(contract=gs.NEUTRAL_SNAPSHOT_KIND,
                                             generate=operation))
    ended = []

    def request():
        try:
            gs.generate(".", "fixture")
            ended.append("answered")
        except Exception as exc:
            ended.append(type(exc).__name__)

    def try_the_host():
        try:
            gs.register(host)
            return "registered"
        except gs.GeneratorAlreadyRegistered as exc:
            if "a snapshot is being generated from it now" in str(exc):
                return "refused-under-way"
            if "a snapshot has already been generated from it" in str(exc):
                return "refused-generated"
            return "refused-otherwise"

    worker = threading.Thread(target=request)
    worker.start()
    assert started.wait(30), "the generation never started"
    during = try_the_host()
    release.set()
    worker.join(30)
    assert not worker.is_alive(), "the generation never ended"
    assert gs._default_generations_under_way == 0, gs._default_generations_under_way
    print(during, ended[0], try_the_host())
"""


@pytest.mark.parametrize("outcome,ends,host_after", (
    ("answers", "answered", "refused-generated"),
    ("raises", "RuntimeError", "registered"),
    ("answers another kind", "GeneratorNotConformant", "registered")))
def test_a_host_is_refused_while_a_generation_from_the_default_is_under_way(
        outcome: str, ends: str, host_after: str) -> None:
    """While a snapshot is being generated from the default, a host's
    registration is refused, because that snapshot would come back after the
    swap. Whether the window stays shut afterwards depends on whether the
    generation WROTE a snapshot. A conformant answer shuts it for good. A
    failure, or an answer the seam refuses, reopens it. The case runs in a
    process of its own (see `_fresh_process`)."""
    done = _fresh_process(_UNDER_WAY.replace("OUTCOME_VALUE", repr(outcome)))
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["refused-under-way", ends, host_after]


def test_a_generator_may_register_or_generate_from_inside_its_own_call() -> None:
    """The seam's lock is held only for its bookkeeping, and never across a
    generator's call. So a generator that registers, unregisters or generates
    from inside its own call cannot deadlock the seam, and the seam's records
    stay true. A default swapped out from inside its own call records nothing
    against the default that replaced it. The case runs in a process of its own
    (see `_fresh_process`)."""
    done = _fresh_process("""
        from opendox import generator_seam as gs
        KIND = gs.NEUTRAL_SNAPSHOT_KIND
        seen = []

        def snapshot(repository):
            return {"schema_version": 1, "kind": KIND, "repository": repository}

        def host_operation(repo_root, repository, *, source_revision=None,
                           generated_at=None):
            return {"schema_version": 1, "kind": "host-snapshot"}

        host = gs.SnapshotGenerator(contract="host-snapshot", generate=host_operation)

        def nesting(repo_root, repository, *, source_revision=None, generated_at=None):
            if repository == "outer":
                try:
                    gs.register(host)
                    seen.append("host-registered-inside")
                except gs.GeneratorAlreadyRegistered as exc:
                    seen.append("refused-inside"
                                if "is being generated from it now" in str(exc)
                                else "refused-otherwise")
                seen.append(gs.generate(repo_root, "inner")["repository"])
            return snapshot(repository)

        gs.register_default(gs.SnapshotGenerator(contract=KIND, generate=nesting))
        seen.append(gs.generate(".", "outer")["repository"])
        try:
            gs.register(host)
            seen.append("host-registered-after")
        except gs.GeneratorAlreadyRegistered:
            seen.append("refused-after")

        def replacing(repo_root, repository, *, source_revision=None,
                      generated_at=None):
            return snapshot(repository)

        replacement = gs.SnapshotGenerator(contract=KIND, generate=replacing)

        def swapping(repo_root, repository, *, source_revision=None,
                     generated_at=None):
            gs.unregister()
            gs.register_default(replacement)
            return snapshot(repository)

        gs.unregister()
        gs.register_default(gs.SnapshotGenerator(contract=KIND, generate=swapping))
        gs.generate(".", "swapped")
        assert gs.current() is replacement
        seen.append("host-registered-over-the-replacement"
                    if gs.register(host) is host else "not-registered")
        assert gs._default_generations_under_way == 0
        print(" ".join(seen))
    """)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["refused-inside", "inner", "outer",
                                   "refused-after",
                                   "host-registered-over-the-replacement"]


def test_a_host_that_registers_the_default_itself_holds_a_hosts_registration() -> None:
    """Which kind a registration is, is set by the call that MADE it."""
    gs.register(default_generator.GENERATOR)
    assert gs.register_default(default_generator.GENERATOR) is \
        default_generator.GENERATOR
    host, _ = _declared("host-snapshot")
    with pytest.raises(gs.GeneratorAlreadyRegistered) as caught:
        gs.register(host)
    assert "a host's generator is already registered" in str(caught.value)


# --------------------------------------------------------------------------
# 7 — each entry point registers openDox's own generator
# --------------------------------------------------------------------------

def _is_the_registration(stmt: ast.stmt) -> bool:
    """`generator_seam.register_default(default_generator.GENERATOR)`, alone."""
    call = stmt.value if isinstance(stmt, ast.Expr) else None
    return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr == "register_default"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "generator_seam"
            and [ast.unparse(arg) for arg in call.args]
            == ["default_generator.GENERATOR"]
            and not call.keywords)


def _binds_the_seam(stmt: ast.stmt) -> bool:
    """`from opendox import default_generator, generator_seam`."""
    return (isinstance(stmt, ast.ImportFrom) and stmt.level == 0
            and stmt.module == "opendox"
            and {"default_generator", "generator_seam"}
            <= {alias.asname or alias.name for alias in stmt.names})


def _module_and_function(path: Path, function: str) -> tuple[list, list]:
    """`path`'s module-level statements, and the body of its top-level `function`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function:
            return tree.body, node.body
    raise AssertionError(f"{path.name} no longer defines {function}()")


@pytest.mark.parametrize("path,function", (
    (CLI, "build_parser"), (CLI, "main"), (SERVE, "build_server"), (SERVE, "main")))
def test_each_entry_point_registers_openDoxs_own_generator_once(path: Path,
                                                                function: str) -> None:
    module_body, body = _module_and_function(path, function)
    registrations = [stmt for stmt in body if _is_the_registration(stmt)]
    assert len(registrations) == 1, (
        f"{path.name}:{function}() makes {len(registrations)} registrations of "
        "openDox's own generator, where R1Q10 (a) asks for exactly one "
        "`generator_seam.register_default(default_generator.GENERATOR)`")
    assert [stmt for stmt in module_body if _binds_the_seam(stmt)], (
        f"{path.name} registers openDox's own generator without importing it")


def test_build_parser_registers_openDoxs_own_generator_where_no_host_has() -> None:
    from opendox import cli

    cli.build_parser()
    assert gs.current() is default_generator.GENERATOR


def test_cli_main_registers_openDoxs_own_generator() -> None:
    from opendox import cli

    with pytest.raises(SystemExit) as exited:
        cli.main(["--help"])
    assert exited.value.code == 0
    assert gs.current() is default_generator.GENERATOR


def test_a_host_registered_first_is_kept_by_the_cli_entry_points() -> None:
    from opendox import cli

    host, _ = _declared("host-snapshot")
    gs.register(host)
    cli.build_parser()
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert gs.current() is host


@pytest.mark.parametrize("function", ("build_server", "main"))
def test_the_server_entry_points_register_openDoxs_own_generator(function: str) -> None:
    """`serve.build_server()` and `serve.main()` cannot run in a lone checkout
    until phase 2 routes their snapshot source (research R7). So the import
    and the registration are lifted out of `serve.py` and executed: the tree's
    own statements, not a paraphrase of them."""
    module_body, body = _module_and_function(SERVE, function)
    lifted = [stmt for stmt in module_body if _binds_the_seam(stmt)] + \
             [stmt for stmt in body if _is_the_registration(stmt)]
    module = ast.Module(body=lifted, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SERVE), "exec"), {})  # noqa: S102
    assert gs.current() is default_generator.GENERATOR
    host, _ = _declared("host-snapshot")
    assert gs.register(host) is host, (
        "registering the default generated nothing, so a host still replaces it")


# --------------------------------------------------------------------------
# 8 — `CorpusAdapter` stays closed at six members
# --------------------------------------------------------------------------

def test_corpus_adapter_stays_closed_at_six_members() -> None:
    """The generator is handed over at its own seam, not as a seventh member."""
    assert corpus_adapter.OPERATIONS == (
        "resolve", "list_documents", "read", "classify", "check", "write_back")
    assert set(corpus_adapter.CorpusAdapter.__protocol_attrs__) == \
        set(corpus_adapter.OPERATIONS)
    assert not hasattr(corpus_adapter.CorpusAdapter, "generate")
