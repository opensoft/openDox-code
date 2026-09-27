"""The suite's hermeticity is STRUCTURAL, and this file is what proves it
(FR-043; PR #49 adversarial review finding 17).

FR-043 — "Tests MUST NOT create real NotebookLM notebooks; the adapter MUST be
stubbed" — used to rest entirely on per-test discipline at the injection seams.
`cli._notebook_port()` DEFAULTS to the real `nlm`-backed
`workbench.NotebookAdapter()` (and `serve._make_adapter()` did too, until PR #49
hardening item 1 made the library default ABSENCE — see
`test_session_notebook.py`), and three tests reached it: two CLI
scoped creates ran `nlm notebook list` + `nlm notebook create
xf-session-openxfactory-demo-topic` and uploaded the fixture staging fragment as
a source, and the CLI abandon then ran `nlm notebook delete --confirm` by TITLE
MATCH against the shared account. It was silent in BOTH directions, because every
call site wraps the runner in `except Exception` and degrades (FR-042): the tests
passed identically whether `nlm` was absent, present-and-failing, or
present-and-succeeding.

`tests/hermeticity.py` removes the class rather than the three instances, and
every test below is a REGRESSION on the guard itself — delete or weaken any part
of the guard and these fail:

  * the shim `PATH` layer (the real binary is not reachable by ANY route,
    including a child process), and its refusal names the offending test;
  * the in-process runner layer (`workbench._default_runner`,
    `session_pr.SubprocessCommandRunner.run`), which is what makes an escape LOUD
    instead of a silent degradation;
  * `HermeticityViolation` being a `BaseException`, asserted through the real
    adapter's own `except Exception` degradation path and through
    `branch_session.open_session_notebook`, whose whole job is to swallow
    notebook failures;
  * the guard NOT weakening anything: an explicitly injected double still works,
    and `available()` is untouched;
  * the hookup set, so the guard cannot be silently dropped from a directory.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

import hermeticity
from conftest import REPO_ROOT

from session_fixtures import build_scratch_repo

from opendox import branch_session as bs
from opendox import cli as cli_mod
from opendox import corpus_adapter as ca
from opendox import session_pr as session_pr_mod
from opendox import workbench as wb

SESSION_ALIAS = bs.notebook_alias("openxFactory", "draft/demo-topic")


# --------------------------------------------------------------------------
# layer 1 — the real binaries are not on PATH, and the refusal is loud
# --------------------------------------------------------------------------

# ONE PROBE PER GUARDED BINARY, in that binary's own dialect. The single
# `notebook list --json` argv this file used to send to every guarded binary was
# an `nlm` command being handed to a `gh` and (since task 2.3) an `omp`: the
# refusal is argv-blind, so it still proved the point, but a probe that names a
# subcommand the binary does not have is a test the next reader has to decode.
# A guarded binary with no probe here fails the completeness assertion below
# rather than silently falling back to somebody else's dialect.
PROBE_ARGV = {
    "nlm": ("notebook", "list", "--json"),
    "gh": ("pr", "list", "--json", "number"),
    "omp": ("--mode", "rpc", "--profile", "doxbench-bridge"),
}


def test_every_guarded_binary_has_a_probe_in_its_own_dialect():
    """The completeness pin for the table above: adding a binary to
    `GUARDED_BINARIES` without a probe here would leave it tested through
    another tool's command line."""
    missing = [b for b in hermeticity.GUARDED_BINARIES if b not in PROBE_ARGV]
    assert missing == [], missing


@pytest.mark.parametrize("binary", hermeticity.GUARDED_BINARIES)
def test_the_real_binary_is_not_what_the_suite_resolves(binary, hermetic_binary_path):
    """`shutil.which` is what `NotebookAdapter.available()` and every ambient
    lookup consults. It must resolve INSIDE the shim dir — not to
    `/usr/local/bin/<binary>`, which is installed on the hosts this suite runs
    on and is exactly how finding 17 reached the live account."""
    resolved = shutil.which(binary)
    assert resolved is not None, f"the {binary} shim must be on PATH"
    assert Path(resolved).parent == hermetic_binary_path, resolved
    assert Path(resolved).resolve() != Path(f"/usr/local/bin/{binary}")


@pytest.mark.parametrize("binary", hermeticity.GUARDED_BINARIES)
def test_an_invocation_of_the_binary_is_refused_and_names_this_test(binary):
    """Any route to the binary — including a child process, which no in-process
    patch can intercept — exits non-zero and says why, naming the guard's marker,
    the REQUIREMENT that binary would break, and the offending test, so the
    escape is attributable rather than mysterious."""
    probe = PROBE_ARGV[binary]
    done = subprocess.run([binary, *probe],
                          capture_output=True, text=True)
    assert done.returncode == hermeticity.REFUSAL_EXIT_CODE, done
    assert hermeticity.MARKER in done.stderr, done.stderr
    assert "test_an_invocation_of_the_binary_is_refused_and_names_this_test" in done.stderr
    assert done.stdout == "", "a refusal must produce no parseable output"
    # and the refusal is RECORDED, so a whole run leaves an attributable inventory
    # of what tried to escape rather than only a message in one test's captured
    # stderr. Asserted as CONTAINMENT, never as the whole file: the ledger is
    # append-only across the session and an exact-contents assertion here would
    # itself be order-dependent.
    ledger = hermeticity.refusal_log()
    assert ledger is not None and ledger.is_file(), ledger
    lines = ledger.read_text(encoding="utf-8").splitlines()
    # keyed on the invocation and this test's own NAME, never on the full nodeid:
    # the nodeid's prefix depends on the run's rootdir (`test_hermeticity.py::…`
    # from inside the directory, `tests/ideation-dashboard/test_hermeticity.py::…`
    # from the repo root), and a run-shape-dependent assertion is the same class of
    # fragility as finding 19a.
    assert any(line.startswith(f"{binary} {' '.join(probe)} :: ")
               and "test_an_invocation_of_the_binary_is_refused" in line
               for line in lines), lines


# --------------------------------------------------------------------------
# task 2.3 (add-doxbench-distilled-abstract) — the MODEL HARNESS binary
# --------------------------------------------------------------------------

def test_the_model_harness_binary_is_guarded_too(hermetic_binary_path):
    """`omp` is the third real binary this repository can reach, and until this
    task it was unguarded.

    The escape it closes is not hypothetical: the entrypoint now declares an
    `OmpHarnessBridge` (task 2.2), whose child is a real `omp --mode rpc`
    process, and `doxbench_bridge._spawn_child` reaches it with no injection at
    all. Every bridge test today passes its own `spawn=` double — but that is
    per-test discipline, which is precisely the class of guarantee finding 17
    proved worthless for `nlm`. The harness's own docstring says no gate may
    require an `omp`; layer 1 makes that structural."""
    assert "omp" in hermeticity.GUARDED_BINARIES, (
        "`omp` is reachable from this repository (doxbench_bridge._spawn_child) "
        "and no test may run it: a forgotten `spawn=` would start a real harness "
        "child, exactly as a forgotten adapter double reached the real NotebookLM "
        "account")
    resolved = shutil.which("omp")
    assert resolved is not None, "the omp shim must be on PATH"
    assert Path(resolved).parent == hermetic_binary_path, resolved
    done = subprocess.run(["omp", *PROBE_ARGV["omp"]],
                          capture_output=True, text=True)
    assert done.returncode == hermeticity.REFUSAL_EXIT_CODE, done
    assert hermeticity.MARKER in done.stderr, done.stderr
    assert done.stdout == "", "a refusal must produce no parseable output"


def test_a_refusal_cites_the_requirement_that_binary_would_actually_break():
    """THE MARKER DECISION (task 2.3), as a test rather than a comment.

    The refusal used to be stamped `MARKER = "FR-043"` — the NotebookLM
    requirement — for EVERY guarded binary. That was already loose for `gh` and
    would be a plain mislabel for `omp`: a developer reading "FR-043 refusing to
    run the real 'omp' binary" would go and read a requirement about NotebookLM
    notebooks. The marker is now the guard's own binary-neutral stamp and each
    refusal additionally names ITS OWN requirement, so no refusal cites a
    requirement it has nothing to do with."""
    omp = subprocess.run(["omp", *PROBE_ARGV["omp"]], capture_output=True,
                         text=True)
    nlm = subprocess.run(["nlm", *PROBE_ARGV["nlm"]], capture_output=True,
                         text=True)
    assert hermeticity.requirement_for("omp") in omp.stderr, omp.stderr
    assert "FR-043" not in omp.stderr, (
        "the omp refusal cites the NotebookLM requirement: a refusal that names "
        f"the wrong requirement is worse than an unexplained one\n{omp.stderr}")
    assert hermeticity.requirement_for("nlm") in nlm.stderr, nlm.stderr
    assert "FR-043" in nlm.stderr, "nlm's own refusal must still cite FR-043"


# --------------------------------------------------------------------------
# layer 2 — the in-process default runners RAISE, and the raise is not swallowed
# --------------------------------------------------------------------------

def test_the_default_notebook_runner_refuses_instead_of_running_nlm():
    with pytest.raises(hermeticity.HermeticityViolation) as raised:
        wb._default_runner("notebook", "create", SESSION_ALIAS)
    message = str(raised.value)
    assert hermeticity.MARKER in message
    assert "test_the_default_notebook_runner_refuses_instead_of_running_nlm" in message


def test_the_default_pull_request_runner_refuses_instead_of_running_gh():
    with pytest.raises(hermeticity.HermeticityViolation) as raised:
        session_pr_mod.SubprocessCommandRunner().run("gh", "pr", "create",
                                                    cwd=REPO_ROOT)
    assert hermeticity.MARKER in str(raised.value)


def test_the_violation_survives_the_adapters_own_degradation_clause():
    """The discriminating assertion for the `BaseException` choice.

    `NotebookAdapter._create_titled` wraps the runner in `except Exception` and
    returns `skipped=True` — that is FR-042's "a notebook never blocks a session"
    and it is correct production behaviour. It is also why a guard raising an
    ordinary exception would be ABSORBED: the escape would return a plausible
    `NotebookResult` and the test would stay green while real `nlm` ran. Only a
    `BaseException` reaches the runner."""
    adapter = wb.NotebookAdapter()                 # the production default
    assert adapter.available() is True, (
        "the shim keeps `available()` TRUE, so the guard is proved on the path "
        "that actually calls the runner rather than on the unavailable shortcut")
    with pytest.raises(hermeticity.HermeticityViolation):
        adapter.create_session(SESSION_ALIAS)


def test_the_violation_survives_open_session_notebooks_degradation_clause(
        monkeypatch, tmp_path):
    """`branch_session.open_session_notebook` catches `Exception` and turns EVERY
    failure into an FR-042 notice — the outermost swallow on the create path.

    A HOME CORPUS IS REGISTERED FIRST (plan 034 T035; the P1-E hand-off). The
    open lists the worktree's documents through `corpus_adapter.home()` BEFORE
    it reaches the adapter's runner, and with nothing registered that listing
    refuses `ADAPTER_NOT_REGISTERED`, an ordinary `Exception` the same clause
    turns into a notice. The case would then stop short of the runner and prove
    nothing about the guard. Whether a registration was already present
    depended on test order, because `cli.build_parser()` registers openDox's
    default process-wide and there is no unregister. So this case registers
    that same default itself, over a one-document scratch worktree rather than
    this checkout, and `monkeypatch` puts the previous registration back.

    The listing is asserted on its own first, so the raise below can only be
    the runner's."""
    monkeypatch.setattr(ca, "_home_factory", ca._home_factory)   # restored after
    ca.register_home(cli_mod._default_home_factory)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "note.md").write_text("# a note\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(worktree)], check=True,
                   capture_output=True, text=True)
    assert wb.session_documents(worktree, repository="openxFactory"), (
        "the scratch worktree listed no document, so the open would stop "
        "before the runner")

    with pytest.raises(hermeticity.HermeticityViolation):
        bs.open_session_notebook(wb.NotebookAdapter(), alias=SESSION_ALIAS,
                                 branch="draft/demo-topic", worktree=worktree,
                                 repository="openxFactory")


# `test_an_unguarded_cli_scoped_create_is_refused` and
# `test_the_cli_seam_with_a_fake_port_reaches_no_binary` LEFT THIS FILE for
# openXdox-code (plan 034 T035). Both drive `gate create-document`, and `gate`
# is not an openDox verb since the carve: the host profile contributes it
# (openXdox's `cli_gate.GateSubcommands`, plan 034 research R8), so this suite's
# own empty profile has no `gate` to parse. openXdox's gate verbs import
# `doc_health` at module level (`cli_gate` imports `gate_console`, which does
# `from doc_health import corpus`), so the two cases join T041's declared
# `doc_health` exclusion there. The guard itself is still proved here, through
# the default adapter above and through `open_session_notebook`.


# --------------------------------------------------------------------------
# the guard weakens nothing — an injected double still works
# --------------------------------------------------------------------------

def test_an_explicitly_injected_runner_is_untouched_by_the_guard():
    """Requirement (c): the guard poisons only the DEFAULTS. A test that
    legitimately exercises the real adapter code still injects its own runner,
    and the adapter behaves exactly as before."""
    calls: list[tuple] = []

    def fake(*args, parse: bool = True, **kwargs):
        calls.append(args)
        return {"id": "nb-1", "title": SESSION_ALIAS}

    result = wb.NotebookAdapter(fake, available=True).create_session(SESSION_ALIAS)
    assert result.ok is True and result.skipped is False
    assert calls == [("notebook", "create", SESSION_ALIAS)]


# --------------------------------------------------------------------------
# the hookup set — the guard cannot be silently dropped from a directory
# --------------------------------------------------------------------------

def test_every_conftest_under_tests_registers_the_guard():
    """Every `conftest.py` under `tests/` registers the guard, and this pin fails
    when a new directory's conftest forgets. The reason is `confcutdir`: a conftest
    is only loaded if it sits between the rootdir and the argument, so a hookup can
    go out of scope without anything changing in the file itself. (At this leg
    `tests/` is one flat directory with one conftest, and `pyproject.toml`
    anchors the rootdir at the repository — see
    `test_the_rootdir_anchor_is_what_puts_the_hookup_in_scope`. openxFactory's
    copy of this pin covers five conftests and anchors on `pytest.ini`.)

    It also pins the SET, because adding a conftest.py is not free: `conftest` is
    an ambient module name, so an UNCLAIMING one hijacks it for siblings whose
    test modules import through it (`tests/notebooklm/conftest.py` broke all 18
    doc-health modules in codexFactory's `scripts/validate-docs.sh`, which ran
    these tests when they lived in codexFactory before the doc-health relocation
    moved them here — adopt-neutral-tooling-home, ratified 2026-08-03; archived
    2026-08-05). A new entry here must be accompanied by a green gate run.

    `CONFTEST_EXEMPT_HOOKUPS` (adopt-neutral-tooling-home tranche B) names the
    conftests that exist but cannot carry the registration — their bytes are
    digest-indexed conformance inputs — so the exemption is itself pinned: a
    new unregistered conftest still fails here unless it is DECLARED.

    THAT HIJACK NOW HAS A REPAIR (issue #305): every DIRECTORY conftest listed
    here calls `claim_conftest_slot(globals())` and owns the ambient name for
    its OWN subtree, which is why `pytest tests/doc-health tests/ideation-dashboard` no
    longer depends on argument order. The claim is pinned separately by
    `test_every_flat_conftest_claims_the_slot_and_the_suite_wide_one_does_not`,
    so a new entry in this set has to carry it."""
    tests_root = REPO_ROOT / "tests"
    found = sorted(str(p.relative_to(tests_root))
                   for p in tests_root.rglob("conftest.py"))
    assert found == sorted(hermeticity.CONFTEST_HOOKUPS
                           + hermeticity.CONFTEST_EXEMPT_HOOKUPS), found
    for relative in hermeticity.CONFTEST_HOOKUPS:
        text = (tests_root / relative).read_text(encoding="utf-8")
        assert "from hermeticity import" in text, relative
        assert "hermetic_binary_path" in text and "hermetic_external_runners" in text, relative


# --------------------------------------------------------------------------
# the ambient `conftest` slot — each directory conftest owns it for its OWN
# subtree, so a multi-directory invocation is order-independent (issue #305)
# --------------------------------------------------------------------------

_SLOT_CONFTEST = '''\
import sys
from pathlib import Path

sys.path.insert(0, {tests_root!r})
{claim_import}
{upper}_ONLY = "{name}"
{claim_call}'''

_SLOT_TEST = '''\
from conftest import {upper}_ONLY


def test_module_level_import_sees_its_own_conftest():
    assert {upper}_ONLY == "{name}"


def test_a_runtime_import_sees_its_own_conftest():
    from conftest import {upper}_ONLY as at_run_time
    assert at_run_time == "{name}"
'''


def _build_slot_tree(root: Path, *, claim: bool) -> Path:
    """Two ROOTLESS sibling directories, each with a conftest.py exporting a
    name only IT defines, and a test module importing that name both at module
    level (collection time) and inside a test body (run time).

    This is `tests/doc-health/` and `tests/ideation-dashboard/` in miniature:
    the same flat `conftest` module name, no `__init__.py`, an inifile at the
    root so the child's rootdir is the scratch tree and never this repository.
    `claim` is the ONLY difference between the pin and its negative control."""
    tests_root = str(REPO_ROOT / "tests")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    for name in ("a", "b"):
        directory = root / name
        directory.mkdir()
        (directory / "conftest.py").write_text(_SLOT_CONFTEST.format(
            tests_root=tests_root,
            upper=name.upper(),
            name=name,
            claim_import=("from hermeticity import claim_conftest_slot\n\n"
                          if claim else "\n"),
            claim_call="claim_conftest_slot(globals())\n" if claim else "",
        ), encoding="utf-8")
        # Unique basenames: two rootless `test_slot.py` files would collide in
        # `sys.modules` the same way the conftests do, which is a DIFFERENT
        # defect and would mask this one.
        (directory / f"test_{name}.py").write_text(_SLOT_TEST.format(
            upper=name.upper(), name=name), encoding="utf-8")
    return root


def _slot_run(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=str(root), capture_output=True, text=True, timeout=120)


def _repo_collect(*args) -> subprocess.CompletedProcess:
    """`--co` over the REAL tree, from the repository root."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--co", "-q", "-p", "no:cacheprovider",
         *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)


def test_a_directory_conftest_owns_the_ambient_slot_for_its_own_subtree(tmp_path):
    """Issue #305. `conftest` is an ambient top-level module name with exactly
    ONE `sys.modules` entry, and pytest's `_importconftest` deletes that entry
    before importing each rootless conftest.py
    (`_pytest/config/__init__.py:753`), so the last one loaded owns it. With
    several path ARGUMENTS, `_set_initial_conftests` loads every argument's
    conftest BEFORE collection starts, so the LAST argument's conftest is what
    the FIRST argument's test modules import from.

    `claim_conftest_slot` re-installs each conftest as the slot's occupant from
    two hooks dispatched through the node's `ihook` — a path-scoped
    `FSHookProxy` that subtracts the conftests not in scope for that path
    (`_pytest/main.py:731`) — so `tests/doc-health/conftest.py`'s copy never
    fires for an ideation-dashboard node. `pytest_collectstart` fires
    immediately before the module is imported (`_pytest/runner.py:588`) and
    `pytest_runtest_setup` before each test body runs
    (`_pytest/runner.py:241`), which is the leg a run-time `from conftest
    import ...` needs.

    Both argument orders, and the single-argument shape, are green."""
    root = _build_slot_tree(tmp_path, claim=True)

    for args in (("a", "b"), ("b", "a")):
        proc = _slot_run(root, *args)
        assert proc.returncode == 0, f"{args}: {proc.stdout}{proc.stderr}"
        assert "4 passed" in proc.stdout, f"{args}: {proc.stdout}"

    proc = _slot_run(root, ".")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "4 passed" in proc.stdout, proc.stdout


def test_without_the_claim_the_same_tree_reproduces_the_slot_collision(tmp_path):
    """The negative control, so the pin above proves the MECHANISM and not just
    an outcome: the identical tree with the claim removed fails exactly the way
    `pytest tests/doc-health tests/avatar_runtime` failed — an ImportError that
    names the OTHER directory's conftest.py as the module it read.

    The single-argument run is the second, quieter half of the defect: directory
    conftests load lazily during traversal so every module-level import
    succeeds, and only the RUN-TIME import inside a test body reads whichever
    conftest was loaded last. That is why the repair needs both hooks."""
    root = _build_slot_tree(tmp_path, claim=False)

    for args, hijacker, wanted in ((("a", "b"), "b", "A_ONLY"),
                                   (("b", "a"), "a", "B_ONLY")):
        proc = _slot_run(root, *args)
        assert proc.returncode != 0, f"{args}: {proc.stdout}"
        assert f"cannot import name '{wanted}' from 'conftest'" in proc.stdout, proc.stdout
        assert f"{hijacker}/conftest.py" in proc.stdout, proc.stdout

    proc = _slot_run(root, ".")
    assert proc.returncode != 0, proc.stdout
    assert "3 passed" in proc.stdout and "1 failed" in proc.stdout, proc.stdout
    assert "cannot import name 'A_ONLY' from 'conftest'" in proc.stdout, proc.stdout


def test_every_flat_conftest_claims_the_slot_and_the_suite_wide_one_does_not():
    """The shipped hookups, pinned. Every directory conftest in
    `CONFTEST_HOOKUPS` is rootless and therefore contends for the slot, so every
    one of them claims it.

    AT THIS LEG THE ROLES SIT ONE LEVEL UP (plan 034 T035). `tests/conftest.py`
    is the one DIRECTORY conftest, the replica of openxFactory's
    `tests/ideation-dashboard/conftest.py`, so it claims. The SUITE-WIDE conftest
    is the repository-root `conftest.py`, and it MUST NOT claim, which is the
    load-bearing exception. pluggy calls hook implementations in LIFO
    registration order and the suite-wide conftest registers FIRST, so its claim
    would run LAST and clobber the directory's. Measured at this leg: with the
    call added to the root conftest, this very module stops collecting, with
    `cannot import name 'REPO_ROOT' from 'conftest'` naming the root conftest.
    (openxFactory measured the same on a scratch tree: two collection errors.)

    `CONFTEST_EXEMPT_HOOKUPS` is empty here. openxFactory's two exempt conftests
    need nothing, because their directories carry `__init__.py`, and the check
    below keeps that reason attached to any entry this leg ever adds."""
    tests_root = REPO_ROOT / "tests"
    suite_wide = (REPO_ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "claim_conftest_slot" not in suite_wide, (
        "the suite-wide (repository-root) conftest must not claim the slot; its "
        "hook would run last and clobber the directory conftest's")
    for relative in hermeticity.CONFTEST_HOOKUPS:
        text = (tests_root / relative).read_text(encoding="utf-8")
        assert "claim_conftest_slot(globals())" in text, relative
        # The define-it-AFTER-the-call direction, which the helper cannot catch:
        # a plain `def pytest_collectstart` later in the file replaces the claim
        # and pytest reports nothing.
        for hook in hermeticity.HOOKS_INSTALLED_BY_THE_CLAIM:
            assert f"def {hook}" not in text, (
                f"{relative} defines {hook} itself, which silently replaces the "
                "slot claim; call the function claim_conftest_slot returns from "
                "inside that implementation instead")
    for relative in hermeticity.CONFTEST_EXEMPT_HOOKUPS:
        assert (tests_root / relative).parent.joinpath("__init__.py").is_file(), (
            f"{relative} is exempt from the claim only because its directory is a "
            "real package, so its conftest never occupies the flat `conftest` slot")


def test_the_claim_refuses_a_conftest_whose_directory_is_a_package(tmp_path):
    """A conftest inside a package is imported as `<package>.conftest` and never
    contends for the flat slot, so claiming from one would install the WRONG
    module under `conftest` for everybody. The precondition is checked, not
    assumed, because the failure it prevents is silent.

    It keys on the directory's `__init__.py`, NOT on the module's `__name__` —
    see `test_the_claim_does_not_abort_a_run_under_a_non_prepend_import_mode`
    for the shape that distinction saves."""
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="ROOTLESS"):
        hermeticity.claim_conftest_slot(
            {"__name__": "pkg.conftest", "__file__": str(tmp_path / "conftest.py")})


def test_the_claim_refuses_a_conftest_that_already_defines_either_hook(tmp_path):
    """The claim installs its two hooks by plain assignment into the conftest's
    `globals()`, so a conftest with a `pytest_collectstart` of its own would have
    it silently overwritten — and one that defines it AFTER the call silently
    overwrites the claim instead. Neither is reported by pytest: the run just goes
    back to being order-dependent.

    So the collision is refused at claim time, and the hooks are RETURNED for the
    conftest that legitimately needs its own to call from inside it. (The
    define-it-afterwards direction cannot be caught here, and is pinned by source
    in `test_every_flat_conftest_claims_the_slot_and_the_suite_wide_one_does_not`.)"""
    namespace = {"__name__": __name__,
                 "__file__": str(tmp_path / "conftest.py"),
                 "pytest_collectstart": lambda collector: None}
    with pytest.raises(RuntimeError, match="already defines pytest_collectstart"):
        hermeticity.claim_conftest_slot(namespace)

    clean = {"__name__": __name__, "__file__": str(tmp_path / "conftest.py")}
    hooks = hermeticity.claim_conftest_slot(clean)
    assert sorted(hooks) == sorted(hermeticity.HOOKS_INSTALLED_BY_THE_CLAIM)
    assert all(clean[name] is hooks[name] for name in hooks)


def test_the_claim_does_not_abort_a_run_under_a_non_prepend_import_mode(tmp_path):
    """`--import-mode=importlib` and `consider_namespace_packages=true` are both
    reachable through `PYTEST_ADDOPTS`, and under either one pytest gives a
    ROOTLESS conftest a DOTTED name — measured: `a.conftest`, not `conftest`. A
    precondition keyed on that name would raise inside conftest collection, which
    aborts the entire run (rc=4) with the FR-043 guard never registered, and would
    misreport the cause: those modes merely change the naming, they do not make
    the directory a package.

    Keyed on the missing `__init__.py` instead, the claim installs and the run
    proceeds. (It also still WORKS under importlib here, but that is not what is
    pinned — only that the guard does not turn a working configuration into an
    aborted one.)"""
    root = _build_slot_tree(tmp_path, claim=True)

    for extra in (["--import-mode=importlib"],
                  ["-o", "consider_namespace_packages=true"]):
        proc = _slot_run(root, "a", "b", *extra)
        output = proc.stdout + proc.stderr
        assert "claim_conftest_slot is for a ROOTLESS" not in output, output
        assert "error" not in output.lower() or proc.returncode == 0, output
        assert proc.returncode == 0, f"{extra}: {output}"


def test_the_real_two_directory_invocation_collects_the_same_in_either_order():
    """The scratch-tree pins prove the MECHANISM; this one proves the SHIPPED
    conftests still use it. Everything else about the claim on the real tree is
    checked by reading source, and a text grep passes over a conftest whose claim
    has been clobbered by a later hook definition, an import-mode change, or an
    edit that reorders the file.

    So: run the collision shape for real, both ways round, and require the two
    orders to AGREE. Counts are compared to each other rather than to a literal,
    because the absolute number moves with every test added; at f9457d6f the two
    orders read 184-with-27-errors and 993-clean.

    AT THIS LEG THE PAIR IS `tests` AND `tests_runtime`, the two suite
    directories it carries (plan 034 T035). A directory's claim is only
    observable when that directory is not the one already holding the slot, and
    in the order `tests tests_runtime` it is not: `tests_runtime/conftest.py`
    loads last, so without `tests/conftest.py`'s claim every
    `from conftest import ...` in `tests/` reads the runtime suite's conftest.
    `tests_runtime/` imports nothing through `conftest`, so the other order
    holds either way. (openxFactory's copy runs two pairs of its own
    directories.)"""
    for left, right in (("tests", "tests_runtime"),):
        counts = []
        for args in ((left, right), (right, left)):
            proc = _repo_collect(*args)
            assert proc.returncode == 0, f"{args}: {proc.stdout[-4000:]}{proc.stderr}"
            assert " error" not in proc.stdout, f"{args}: {proc.stdout[-4000:]}"
            match = re.search(r"(\d+) tests collected", proc.stdout)
            assert match, proc.stdout[-2000:]
            counts.append(int(match.group(1)))

        assert counts[0] == counts[1] > 0, (left, right, counts)


# --------------------------------------------------------------------------
# finding 17, wave 2 — the rootdir anchor
# --------------------------------------------------------------------------

# THREE CASES OF THIS SECTION STAYED WITH openxFactory'S TREE (plan 034 T035):
# `test_a_pytest_run_started_inside_a_conftestless_directory_is_guarded`,
# `test_the_unittest_fallback_route_installs_the_same_guard` and
# `test_the_bare_unittest_route_is_detected_as_unguarded`. Each one drives
# openxFactory's own files: the probe `tests/notebooklm/test_hermeticity_guard.py`
# in a conftest-less directory, its `pytest.ini`, and its guarded
# `tests/hermetic_unittest.py`. The carve moved none of those (all three are
# `not_moved` rows), so the three cases go back to openxFactory as named tests
# (T047). This leg has no conftest-less test directory and no unittest runner,
# so nothing here is left for them to test.


def test_the_rootdir_anchor_is_what_puts_the_hookup_in_scope():
    """The mechanism, asserted rather than assumed: a run started INSIDE
    `tests/` resolves its rootdir to the REPOSITORY and names the anchor as its
    configfile.

    At this leg the anchor is `pyproject.toml` (plan 034 T035). With no anchor,
    that run's rootdir would be `tests/` itself, and the repository-root
    `conftest.py` (this suite's `src/` path and its host profile) would fall out
    of the conftest chain, however correct that conftest is. The table is
    checked too: without it pytest 8 uses the file only as a fallback, when no
    configuration file is found anywhere above, so a `pytest.ini` in an
    enclosing directory would take the rootdir (see `ROOTDIR_ANCHOR`).

    The rootdir is matched as the WHOLE value. openxFactory's copy matches a
    substring, which also accepts `<repository>/tests`. A `tests/pyproject.toml`
    with a pytest table produces exactly that rootdir, and it still prints
    `configfile: pyproject.toml`, so a substring match and the configfile check
    would both pass while the root conftest was cut out."""
    anchor = REPO_ROOT / hermeticity.ROOTDIR_ANCHOR
    assert anchor.is_file(), f"{hermeticity.ROOTDIR_ANCHOR} is the rootdir anchor"
    assert "[tool.pytest.ini_options]" in anchor.read_text(encoding="utf-8"), (
        f"{hermeticity.ROOTDIR_ANCHOR} is an inifile only while it carries a "
        "[tool.pytest.ini_options] table")

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
         "--collect-only", "test_hermeticity.py"],
        cwd=str(REPO_ROOT / "tests"), capture_output=True, text=True,
        timeout=300)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(rf"^rootdir: {re.escape(str(REPO_ROOT))}(,|$)",
                     proc.stdout, re.MULTILINE), proc.stdout
    assert f"configfile: {hermeticity.ROOTDIR_ANCHOR}" in proc.stdout, proc.stdout


# `test_the_gate_runs_its_unittest_fallback_through_the_guarded_runner` stayed
# with `scripts/validate-docs.sh` in codexFactory (adopt-neutral-tooling-home
# tranche B, 2026-08-03): that shell gate is codexFactory's own and keeps its
# codex-specific checks there (change task 3.1), so its source pin lives beside
# it. openxFactory's unittest fallback route is still proved above by
# `test_the_unittest_fallback_route_installs_the_same_guard` and its negative
# control.


def test_no_production_handler_swallows_a_baseexception():
    """The invariant the WHOLE guard rests on, as a test instead of a stale comment.

    `HermeticityViolation` derives from `BaseException` precisely so the production
    `except Exception` degradation clauses cannot absorb it. `tests/hermeticity.py`
    asserted in prose that "nothing in scripts/ideation_dashboard/ catches
    BaseException or uses a bare except: (checked)" — and that went stale within a
    day: the wave-1 repair added two `except BaseException` handlers (both
    re-raising, so the guard still propagated) and the PR #49 completeness critic
    found the comment still claiming otherwise. A handler that did NOT re-raise
    would disable the entire mechanism with a green suite.

    So: every `except BaseException` (and every bare `except:`) in the package must
    contain a `raise`. Parsed, not grepped, so a handler nested in a helper counts
    the same as a top-level one.

    AT THIS LEG THE PACKAGE IS `src/opendox/` (plan 034 T035). The scan still
    named `scripts/ideation_dashboard/`, a directory this leg does not have, so
    it read no file and passed on nothing. It now reads the package, the
    `opendox.runtime` subpackage included, and it fails if it reads no module at
    all."""
    import ast

    offenders = []
    scanned = 0
    package = REPO_ROOT / "src" / "opendox"
    for path in sorted(package.rglob("*.py")):
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            caught = node.type
            bare = caught is None
            base = isinstance(caught, ast.Name) and caught.id == "BaseException"
            tupled = isinstance(caught, ast.Tuple) and any(
                isinstance(e, ast.Name) and e.id == "BaseException"
                for e in caught.elts)
            if not (bare or base or tupled):
                continue
            reraises = any(isinstance(inner, ast.Raise)
                           for inner in ast.walk(ast.Module(body=node.body,
                                                            type_ignores=[])))
            if not reraises:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert scanned, f"the scan read no module under {package}, so it proved nothing"
    assert offenders == [], (
        "these handlers catch BaseException (or bare) WITHOUT re-raising, so they "
        "would swallow HermeticityViolation and silently disable the FR-043 "
        f"guard: {offenders}")


# --------------------------------------------------------------------------
# finding 19a — the harness no longer resolves its shapes through `conftest`
# --------------------------------------------------------------------------

def test_the_scratch_harness_does_not_depend_on_the_ambient_conftest_name(tmp_path,
                                                                          monkeypatch):
    """`build_scratch_repo` used to run `from conftest import staging_fragment`
    inside its own body. pytest deletes `sys.modules["conftest"]` before importing
    each directory's conftest, so that name resolves to whichever conftest was
    imported LAST: running this suite AFTER `tests/doc-health` in one process
    raised `ImportError: cannot import name 'staging_fragment' from 'conftest'` at
    SETUP, making the branch's evidence counts depend on collection order.

    Here the ambient name is deliberately pointed at a module that has no shapes
    at all — the harness must not notice."""
    decoy = types.ModuleType("conftest")
    decoy.__file__ = "<decoy: a conftest with no staging shapes>"
    monkeypatch.setitem(sys.modules, "conftest", decoy)

    repo = build_scratch_repo(tmp_path)
    fragment = (repo.root / f"ideation/staging/{repo.topic_id}/README.md").read_text(
        encoding="utf-8")
    assert "Kind: staging-packet" in fragment
    assert repo.origin_branches() == ("main",)


def test_the_harness_imports_its_shapes_from_the_plainly_named_module():
    """The source pin behind the behaviour above: `session_fixtures` names
    `staging_shapes`, never the ambient `conftest`."""
    text = (REPO_ROOT / "tests" / "session_fixtures.py").read_text(encoding="utf-8")
    assert "from staging_shapes import staging_fragment" in text
    ambient = [line for line in text.splitlines()
               if line.strip().startswith("from conftest import")]
    assert ambient == [], ambient
