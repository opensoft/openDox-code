"""The home-corpus seam: ONE registration, read wherever a deferred reach
used to import a publisher's adapter by name (`split-opendox-two-layer-product`
§ 4.1, § 4.2; design.md D6, D7).

`authoring.py:318` used to read the publisher's factory by name INSIDE a
function body, so the module imported cleanly and the failure waited for the
call -- design.md D6's more dangerous class, because it survives any
import-based health check and fails in front of a user. This suite holds
`opendox.corpus_adapter`'s half of the repair to its two words: with NOTHING
registered, the seam REFUSES, naming itself and the exact call that is
missing; with a factory registered, the seam hands it back, unevaluated, for
the caller to invoke with its own root.

THIS FILE GROWS, in the order `tasks.md`'s single-writer table gives:
T020 (this task) adds the two cases below. T021 adds
`test_required_header_fields_come_from_the_registered_adapter`, once
`authoring.py:318` is routed through this seam. T022 adds
`test_an_entry_point_registers_the_local_git_corpus_when_no_host_has`, once
an entry point registers openDox's own default where no host has. Each lands
in its own PR.

T020's and T021's own cases needed neither `opendox.serve` nor `opendox.cli`
WHEN THEY WERE WRITTEN: both raised `ModuleNotFoundError: No module named
'ideation_dashboard'` before T011 landed (measured at `1e4a57fb`), and any
run with the root conftest in play failed on the autouse
`declared_human_console` fixture, which imports `opendox.cli`
(`tests/session_fixtures.py:397`). Those cases were `--noconftest` safe for
exactly that reason. **THIS IS HISTORY, NOT CURRENT COVERAGE** (Copilot
review of openDox-code#45, "Update outdated T011 coverage note"): T011 has
since landed (`#46` -> `0e88454a`), `opendox.cli`/`opendox.serve` import
cleanly, and every case in this file -- this one included -- now runs under
the plain root conftest; `--noconftest` is no longer required for any of
them, only still harmless where a case never depended on it either way.

**T022's named test was DIFFERENT WHILE T011 WAS STILL OPEN, and this
correction said so plainly rather than silently contradicting the
paragraph above.** Proving *"an entry point registers…"* means calling the
entry point -- `cli.build_parser()` -- which did not import before T011
landed. So that one case `pytest.importorskip`s `opendox.cli`, which SKIPPED
here and under `--noconftest` alike before T011 landed. T022's own PR
verified it, ahead of T011, under the Group 2 simulation shim (research.md's
Appendix; never committed), which stood in for `ideation_dashboard` exactly
as T005's and T006's measurements did. T011 has SINCE landed (`#46` ->
`0e88454a`): `cli.build_parser()` no longer refuses on import, this case now
runs for real like every other one in this file, and the `importorskip`
above is retained only as a harmless guard against some future, narrower
invocation of this file alone -- not because it is expected to trigger.

A CREATED file: no carve-manifest row (RULED OQ-C -- the manifest declares
what LEAVES openxFactory, never what a destination assembles).
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from opendox import authoring
from opendox import corpus_adapter as ca

#: `serve.py`'s own path, for the AST-lifted `build_server()` case below --
#: same constant shape as `test_profile_registration.py`'s `SERVE`.
_SERVE_PY = Path(__file__).resolve().parent.parent / "src" / "opendox" / "serve.py"


@pytest.fixture(autouse=True)
def _empty_home_registry():
    """Every test starts with NOTHING registered, and PUTS BACK what it found.

    Mirrors `test_profile_registration.py`'s `_empty_registry`, for the same
    reason: the registry is process-global by design (ONE registration, for
    the whole process), so a test that registers a stand-in must restore
    whatever the process itself relies on afterwards rather than merely clear
    it. Nothing registers a home corpus at this leg's process start today --
    that is T022, still open when this fixture was written -- so there is
    nothing yet to restore; the restore is here so the day T022 lands, or a
    conftest gains an autouse registration, this file does not silently start
    depending on collection order.
    """
    previous = ca._home_factory
    ca._home_factory = ca._UNSET
    yield
    ca._home_factory = previous


def _import_opendox_cli_or_skip():
    """`opendox.cli` imports cleanly once T011 has landed; before that, it
    fails at `serve.py`'s `from ideation_dashboard import
    serve_openxfactory_lanes` (`cli.py` imports `serve.py`).

    Skipping on EXACTLY that one `ModuleNotFoundError` -- never any
    `ModuleNotFoundError` raised while importing the module -- is the whole
    point (Copilot review of openDox-code#45, "importorskip masks unrelated
    CLI import failures"): `pytest.importorskip` catches ANY import-time
    `ModuleNotFoundError`, so an unrelated broken or missing import inside
    `opendox.cli`, discovered after T011 has already landed, would report
    SKIP here instead of FAILING -- masking the very entry-point regression
    this falsifier exists to catch."""
    try:
        import opendox.cli as cli
    except ModuleNotFoundError as exc:
        if exc.name != "ideation_dashboard":
            raise
        pytest.skip("opendox.cli does not import until T011 lands "
                   "(ModuleNotFoundError: No module named 'ideation_dashboard')")
    return cli


# --------------------------------------------------------------------------
# 4.2 -- nothing registered: `home()` refuses, naming the seam and the remedy
# --------------------------------------------------------------------------

def test_home_refuses_naming_the_seam_and_the_remedy_when_nothing_is_registered() -> None:
    """`CorpusRefused`, the interface's ONE exception, and nothing else.

    Never a `ModuleNotFoundError` raised from inside a function -- the defect
    this seam retires -- and never a silent local default: an entry point
    that wants one registers it explicitly (4.1a, T022), so an unregistered
    `home()` always refuses rather than falling back on its own.
    """
    with pytest.raises(ca.CorpusRefused) as caught:
        ca.home()
    refusal = caught.value.refusal
    assert refusal.kind == ca.ADAPTER_NOT_REGISTERED, (
        f"refused for another reason: {refusal.kind!r}")
    assert refusal.subject == "opendox.corpus_adapter", (
        f"the refusal does not name the seam: {refusal.subject!r}")
    assert "register_home" in refusal.detail, (
        f"the refusal does not name the remedy: {refusal.detail!r}")
    # `ADAPTER_NOT_REGISTERED` is a real member of the closed vocabulary, not
    # a one-off string a future edit could drift from `REFUSAL_KINDS`.
    assert ca.ADAPTER_NOT_REGISTERED in ca.REFUSAL_KINDS


def test_home_is_still_refused_after_a_registration_is_cleared() -> None:
    """The refusal is read off THIS process's registry, not cached once seen."""
    ca.register_home(lambda root: (root, root))
    ca.home()  # does not raise: something is registered

    ca._home_factory = ca._UNSET  # the shape `unregister()` would leave, were one asked for
    with pytest.raises(ca.CorpusRefused) as caught:
        ca.home()
    assert caught.value.refusal.kind == ca.ADAPTER_NOT_REGISTERED


# --------------------------------------------------------------------------
# 4.1 -- a registered factory is what `home()` returns
# --------------------------------------------------------------------------

def test_a_registered_factory_is_what_home_returns() -> None:
    """`home()` hands back the factory itself, unevaluated, not its result.

    `factory` has the shape `adapter, ref = factory(root)`. The seam stores
    it as given: no caller has a root to offer at registration time, so the
    caller that later has one (`authoring.py:324`, T021) is the one that
    invokes it -- `home()` only resolves WHICH factory that is.
    """
    calls: list[str] = []

    def stand_in(root: str) -> tuple[str, str]:
        calls.append(root)
        return (f"adapter-over-{root}", f"ref-for-{root}")

    returned = ca.register_home(stand_in)
    assert returned is stand_in, (
        "register_home() should return the factory, so a registrant can "
        "register and hold it in one expression, as domain_profile.register() "
        "does for a profile")

    factory = ca.home()
    assert factory is stand_in, "home() must return exactly what was registered"
    assert calls == [], "home() must not itself call the registered factory"

    adapter, ref = factory("/some/root")
    assert (adapter, ref) == ("adapter-over-/some/root", "ref-for-/some/root")
    assert calls == ["/some/root"], "the caller's own invocation is the only one"


def test_home_returns_the_latest_registration_and_does_not_cache() -> None:
    """One registration stays one: a second `register_home` replaces the first."""
    first = lambda root: ("first", root)   # noqa: E731 - a stand-in, not a policy
    second = lambda root: ("second", root)  # noqa: E731

    ca.register_home(first)
    assert ca.home() is first

    ca.register_home(second)
    assert ca.home() is second, (
        "home() answered from a stale registration after a new one replaced it")


def test_register_home_refuses_a_non_callable_factory() -> None:
    """Storing anything but a callable defers today's clean refusal to a raw
    `TypeError` on the caller's NEXT line -- `adapter, ref = home()(root)`
    cannot unpack what a non-callable would hand back. Consistent with
    `domain_profile.register()` rejecting `None` for the same reason
    (Copilot review, PR opensoft/openDox-code#37).
    """
    with pytest.raises(TypeError):
        ca.register_home(None)  # type: ignore[arg-type]
    with pytest.raises(ca.CorpusRefused):
        ca.home()  # nothing valid was ever stored

    stand_in = lambda root: (root, root)  # noqa: E731
    ca.register_home(stand_in)
    with pytest.raises(TypeError):
        ca.register_home("not-a-factory")  # type: ignore[arg-type]
    assert ca.home() is stand_in, (
        "a rejected registration must not clobber a good one already in place")


# --------------------------------------------------------------------------
# 4.1 (authoring.py:318, T021) -- the registered adapter answers, not a name
# --------------------------------------------------------------------------

class _StandInAdapter:
    """The two `CorpusAdapter` operations `authoring._classify_proposal` calls
    -- `resolve`, then `classify` -- and nothing else: a minimal duck-typed
    stand-in, like `test_health_check_seam.py`'s `_RecordingCheck`, not a full
    six-method `CorpusAdapter` implementation. `required_fields` is the ONE
    thing a test varies, so a change in `authoring.required_header_fields()`'s
    answer can only have come from here -- never from a name this module
    imports, because none is imported any more (T021)."""

    def __init__(self, required_fields: tuple[str, ...]) -> None:
        self.required_fields = required_fields
        self.resolved: list[ca.CorpusRef] = []

    def resolve(self, ref: ca.CorpusRef) -> ca.ResolvedCorpus:
        self.resolved.append(ref)
        return ca.ResolvedCorpus(ref=ref, location=ref.location, revision=None,
                                 scopes=(ca.SCOPE_ALL,), write_path=None,
                                 write_path_available=False)

    def classify(self, corpus: ca.ResolvedCorpus,
                document: ca.DocumentId) -> ca.Classification:
        return ca.Classification(id=document, kind="stand-in",
                                 required_fields=self.required_fields,
                                 missing_fields=())


def test_required_header_fields_come_from_the_registered_adapter() -> None:
    """`authoring.py:318` (T021): `authoring.required_header_fields()` used to
    read `corpus_adapter_openxfactory.home_corpus` by NAME -- one of #1144's
    F4.1 scan's 27 deferred reaches, and the class design.md § D6 calls more
    dangerous because it survives any import-based health check. It now
    resolves through `corpus_adapter.home()`, so this test registers a
    stand-in adapter TWICE, with two DIFFERENT `required_fields` tuples in
    turn, and requires the answer to follow each one -- proving the fields
    come from the registered adapter and not from a name, a cache, or a
    coincidence of the first tuple chosen.

    `home()` is called through `_classify_proposal`, which stages an empty
    proposal body under a throwaway temp directory and resolves it as the
    home corpus's ROOT -- so the stand-in's `resolve()` genuinely runs, over
    a `CorpusRef` this test never has to build by hand.
    """
    first = _StandInAdapter(("Distinctive-Field-One", "Distinctive-Field-Two"))
    ca.register_home(lambda root: (first, ca.CorpusRef(name="home", location=root)))
    assert authoring.required_header_fields() == first.required_fields
    assert first.resolved, "the registered adapter's resolve() was never called"

    second = _StandInAdapter(("A-Third-Field",))
    ca.register_home(lambda root: (second, ca.CorpusRef(name="home", location=root)))
    assert authoring.required_header_fields() == second.required_fields
    assert second.required_fields != first.required_fields, (
        "the two tuples must be genuinely different, or neither assertion "
        "above would have been able to fail")
    assert second.resolved, "the second registration's resolve() was never called"
    assert first.resolved[0] != second.resolved[0], (
        "each call staged its own throwaway root; the two resolutions must "
        "not have collided on one directory")


# --------------------------------------------------------------------------
# 4.1a (T022) -- openDox's own default adapter, registered by an entry point
# --------------------------------------------------------------------------

def test_register_default_home_leaves_an_existing_registration_alone() -> None:
    """`corpus_adapter.register_default_home()` (T022) is the entry points'
    seam call, generic over whatever factory it is given -- this case never
    touches `cli.py`/`serve.py` at all, so it needs neither module and runs
    unconditionally.

    A host's (or an earlier caller's) registration, made before an entry
    point runs, must survive: `register_home()` always OVERWRITES, so the
    entry point's call is only lawful because it checks first."""
    host_factory = lambda root: ("the host's adapter", root)  # noqa: E731
    ca.register_home(host_factory)

    default_factory = lambda root: ("openDox's default adapter", root)  # noqa: E731
    ca.register_default_home(default_factory)

    assert ca.home() is host_factory, (
        "register_default_home() replaced a registration that was already "
        "there -- it must check corpus_adapter.home() first, exactly as "
        "domain_profile.register_default() does for the profile (T016)")


def test_register_default_home_registers_where_nothing_has() -> None:
    """The other half of the same seam call: nothing registered, so it does."""
    default_factory = lambda root: ("openDox's default adapter", root)  # noqa: E731
    ca.register_default_home(default_factory)
    assert ca.home() is default_factory


def test_an_entry_point_registers_the_local_git_corpus_when_no_host_has() -> None:
    """T022's named falsifier. `cli.build_parser()` -- AN ENTRY POINT -- calls
    `corpus_adapter.register_default_home(...)` over openDox's own
    `LocalGitCorpus`, where no host has called `register_home(...)` already
    (4.1a). A bare process that builds nothing still meets 4.2's
    `ADAPTER_NOT_REGISTERED` refusal (`test_home_refuses_naming_the_seam_...`
    above); this is the registration that entry point makes instead.

    An explicit skip-on-import-failure, not a plain `import` -- because
    proving *"an entry point registers…"* means calling `cli.build_parser()`,
    and that is exactly what does not import in a lone checkout until T011
    lands (see the module docstring's correction, and
    `_import_opendox_cli_or_skip`'s own). This case SKIPS today, under
    `--noconftest` and without it alike, and runs for real once T011 has
    landed -- T022's own PR verifies it now under the Group 2 simulation
    shim instead, and says so plainly."""
    cli = _import_opendox_cli_or_skip()
    from opendox import domain_profile
    from opendox.runtime.local_git_adapter import WorkingTreeCorpus

    with pytest.raises(ca.CorpusRefused):
        ca.home()  # nothing registered yet -- the autouse fixture's own promise

    # `build_parser()` also reads the (still unregistered, pre-T016) host
    # profile as its OWN last statement, which refuses `ProfileNotRegistered`
    # today. This case is about the corpus-adapter registration alone, which
    # runs first in the function body regardless of that later refusal --
    # and once T016 lands, `build_parser()` will not raise at all, so this
    # `except` clause becomes dead code and the assertions below still hold.
    try:
        cli.build_parser()
    except domain_profile.ProfileNotRegistered:
        pass

    factory = ca.home()
    adapter, ref = factory("/some/repository/root")
    assert isinstance(adapter, WorkingTreeCorpus), (
        f"the entry point's default adapter is {adapter!r}, not a "
        "WorkingTreeCorpus (RULING, Brett Heap, 2026-09-27, via the holder: "
        "\"Working tree (Recommended)\")")
    assert ref.location == "/some/repository/root"


def test_build_server_registers_the_default_where_no_host_has() -> None:
    """`serve.build_server()`'s half of 4.1a, run from its own source lines.

    `serve.build_server()` cannot be called directly today, unlike
    `cli.build_parser()`: T011 only made `opendox.serve` IMPORTABLE, and
    `build_server()`'s own body still reaches `openxdox.snapshot_registry`/
    `openxdox.corpus_root` (unrelated, later tasks; plan 034 research R7), so
    calling it whole fails for a reason that has nothing to do with this
    registration (Copilot review of openDox-code#45, "Missing test coverage
    for server default registration": the entry-point falsifier above
    exercises only `cli.build_parser()`, so a regression removing `serve
    .build_server()`'s own registration line would leave this suite green).

    Lifted by AST instead, mirroring `test_profile_registration.py`'s own
    technique for the identical problem with `ROUTE_EXTENSIONS`: the module-
    level `_default_home_factory` definition, and the ONE statement in
    `build_server()`'s body that calls `corpus_adapter
    .register_default_home(_default_home_factory)`, executed together
    against the REAL `corpus_adapter`/`local_git_adapter` (both import
    cleanly and touch no registry on import) -- running the actual source
    line, not a paraphrase of it."""
    tree = ast.parse(_SERVE_PY.read_text(encoding="utf-8"))
    factory_def = None
    build_server_body = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef)
                and node.name == "_default_home_factory"):
            factory_def = node
        if isinstance(node, ast.FunctionDef) and node.name == "build_server":
            build_server_body = node.body
    assert factory_def is not None, (
        "serve.py no longer defines _default_home_factory()")
    assert build_server_body is not None, (
        "serve.py no longer defines build_server()")

    def _is_the_registration(stmt: ast.stmt) -> bool:
        call = stmt.value if isinstance(stmt, ast.Expr) else None
        return (isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "register_default_home"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "corpus_adapter"
                and [ast.unparse(a) for a in call.args] == ["_default_home_factory"]
                and not call.keywords)

    registrations = [n for n in build_server_body if _is_the_registration(n)]
    assert len(registrations) == 1, (
        f"serve.py:build_server() makes {len(registrations)} statements "
        "shaped like `corpus_adapter.register_default_home"
        "(_default_home_factory)`, where 4.1a asks for exactly one")

    from opendox import corpus_adapter
    from opendox.runtime import local_git_adapter
    from opendox.runtime.local_git_adapter import WorkingTreeCorpus

    namespace = {"corpus_adapter": corpus_adapter,
                "local_git_adapter": local_git_adapter}
    module = ast.Module(body=[factory_def, registrations[0]], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(_SERVE_PY), "exec"),  # noqa: S102
        namespace)

    factory = ca.home()
    adapter, ref = factory("/some/repository/root")
    assert isinstance(adapter, WorkingTreeCorpus), (
        f"serve.build_server()'s default adapter is {adapter!r}, not a "
        "WorkingTreeCorpus")
    assert ref.location == "/some/repository/root"


def _init_ordinary_checkout(repo, *files: tuple[str, str]) -> None:
    """A REAL, ORDINARY (non-bare) git repository, made with plain `git`
    commands -- the shape a standalone user's own repository has, and never
    the BARE one `local_git_adapter.initialize_repository` makes (RULING C3):
    a bare repository has no working tree for this ruling to be about.
    Mirrors `tests_runtime/test_local_git_adapter.py`'s own
    `_GIT_ENV`/linked-worktree fixture construction, hermetic against a
    developer's global git config the same way.

    THE BASE ENVIRONMENT IS `sanitized_git_environment()`, NOT A RAW
    `os.environ` COPY (Copilot review of openDox-code#45, "Sanitize Git
    environment in checkout test"): a plain `{**os.environ, ...}` keeps
    whatever `GIT_DIR`/`GIT_WORK_TREE`/`GIT_COMMON_DIR` the process this
    suite runs under already has set -- a wrapping git hook, a CI runner's
    own checkout step -- so `git init -C <repo> .` below could target or
    mutate THAT repository instead of the throwaway `repo` this helper was
    asked to create, silently. The identity/config overrides this helper
    itself needs are layered on top of the sanitized base, exactly as
    `authoring._stage_as_a_repository_if_git_is_available` layers its own
    `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` overrides on top of it."""
    import subprocess

    from opendox.runtime.local_git_adapter import sanitized_git_environment

    env = {**sanitized_git_environment(), "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_SYSTEM": os.devnull,
           "GIT_AUTHOR_NAME": "openDox tests",
           "GIT_AUTHOR_EMAIL": "tests@opendox.invalid",
           "GIT_COMMITTER_NAME": "openDox tests",
           "GIT_COMMITTER_EMAIL": "tests@opendox.invalid"}

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, env=env)

    repo.mkdir()
    git("init", "--initial-branch=main", ".")
    for relpath, content in files:
        (repo / relpath).write_text(content, encoding="utf-8")
        git("add", relpath)
    git("commit", "-m", "first")


def test_an_uncommitted_edit_is_visible_through_the_default(tmp_path) -> None:
    """RULING (Brett Heap, 2026-09-27, via the holder: "Working tree
    (Recommended)"): the standalone default reads the WORKING TREE, uncommitted
    edits included, not the session branch's HEAD. Reason: standalone users
    edit files in their own editor, and the hosted openxFactory adapter
    already shows worktree bytes.

    A real, ORDINARY checkout with one committed file, read once through the
    default, THEN edited on disk with no second commit, and read again through
    the SAME resolved corpus -- not a fresh `resolve()` -- so this also proves
    there is no listing or content cache keyed on the revision `resolve()`
    captured. A new, never-committed file is picked up by `list_documents`
    too, which only a working-tree listing (never `git ls-tree HEAD`) can do.

    `_import_opendox_cli_or_skip`, for the same reason as the case above:
    proving this THROUGH THE DEFAULT means calling `cli.build_parser()`."""
    cli = _import_opendox_cli_or_skip()
    from opendox import domain_profile
    from opendox.runtime import local_git_adapter as lga

    if not lga.git_available():
        pytest.skip("`git` is not on PATH")

    repo = tmp_path / "notes"
    _init_ordinary_checkout(repo, ("note.md", "committed\n"))

    try:
        cli.build_parser()
    except domain_profile.ProfileNotRegistered:
        pass
    factory = ca.home()
    adapter, ref = factory(str(repo))
    resolved = adapter.resolve(ref)
    key = ca.DocumentId(corpus=ref.name, key="note.md")

    committed = adapter.read(resolved, key)
    assert committed.content == b"committed\n"

    (repo / "note.md").write_text("edited, never committed\n", encoding="utf-8")
    edited = adapter.read(resolved, key)
    assert edited.content == b"edited, never committed\n", (
        "the default served the committed bytes after an uncommitted edit -- "
        "it is reading git HEAD, not the working tree")

    (repo / "draft.md").write_text("never committed at all\n", encoding="utf-8")
    keys = {doc.key for doc in adapter.list_documents(resolved)}
    assert keys == {"note.md", "draft.md"}, (
        "the default's listing did not pick up the new, uncommitted file")


def test_the_default_can_actually_classify_a_proposal() -> None:
    """The end-to-end falsifier asked for directly (Copilot review of
    openDox-code#45, "Make default factory classify proposals in temporary
    directories"): `required_header_fields()`/`missing_required_headers()`
    go through `authoring._classify_proposal()`, which stages the body in a
    plain `tempfile.TemporaryDirectory()` and hands it to whatever `home()`
    returns. Once an entry point registers the REAL default (not a stand-in
    -- every OTHER case in this file uses one, on purpose, to isolate the
    seam from the adapter), that staged tree was never a git repository, so
    `WorkingTreeCorpus.resolve()` always refused `CORPUS_UNCLASSIFIABLE`
    before `authoring.py`'s own fix
    (`_stage_as_a_repository_if_git_is_available`). This proves the fix
    through the REGISTERED default, not a mock of it.

    Deliberately NOT asserting the exact `required_fields` tuple: T054
    (phase 2) sets the neutral fields; today's bare default is `()`, and
    hard-coding that would make this test wrong the day T054 lands rather
    than testing what it actually claims to -- that the call SUCCEEDS.

    SKIPS WHERE `git` IS NOT ON PATH, like the falsifier above (Copilot
    review of openDox-code#45, "Skip Git-dependent integration test when
    Git is unavailable"): `_stage_as_a_repository_if_git_is_available`
    deliberately SWALLOWS a missing `git` executable (its own docstring:
    "never this function's failure"), so without this guard, a runner with
    no `git` on PATH would still reach `WorkingTreeCorpus.resolve()` on a
    plain, never-initialized temporary directory and fail on
    `CorpusRefused(CORPUS_UNCLASSIFIABLE)` -- a fresh, misleading failure
    unrelated to what this case actually tests, in exactly the environment
    the rest of this suite already knows to skip in instead."""
    cli = _import_opendox_cli_or_skip()
    from opendox import domain_profile
    from opendox.runtime import local_git_adapter as lga

    if not lga.git_available():
        pytest.skip("`git` is not on PATH")

    try:
        cli.build_parser()
    except domain_profile.ProfileNotRegistered:
        pass

    fields = authoring.required_header_fields()
    assert isinstance(fields, tuple), (
        f"required_header_fields() returned {fields!r}, not a tuple -- "
        "did it raise and get swallowed somewhere upstream?")

    missing = authoring.missing_required_headers("Status: draft\n")
    assert isinstance(missing, list), (
        f"missing_required_headers() returned {missing!r}, not a list")
