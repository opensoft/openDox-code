"""Structural test hermeticity: the real `nlm`, `gh` and `omp` are UNREACHABLE.

Why this module exists. FR-043 — "Tests MUST NOT create real NotebookLM
notebooks; the adapter MUST be stubbed" — was enforced only by PER-TEST
DISCIPLINE. `cli._notebook_port()` and `serve._make_adapter()` both DEFAULT to
`workbench.NotebookAdapter()`, whose runner is a real `nlm` subprocess, so a test
that simply forgot to inject its fake reached the SHARED NotebookLM account. It
reached it SILENTLY in both directions, too: every adapter call site wraps the
runner in `except Exception` and degrades to `skipped=True` (FR-042 requires a
notebook never to block a session), so such a test passed identically whether
`nlm` was absent, present-and-failing, or present-and-succeeding. PR #49 review
finding 17 measured three tests doing exactly that — running `nlm notebook
create`, a source upload, and a `notebook delete --confirm` against the live
account. Fixing those three would not fix the class: the next test written
forgets again.

So hermeticity is made structural, in two INDEPENDENT layers:

  1. **PATH** — a shim directory is prepended to `PATH` for the whole session.
     Its `nlm`, `gh` and `omp` are refusals: each prints the offending test's
     nodeid, the requirement that binary would break, and the seam to inject
     instead, then exits non-zero. This covers every route to the binary,
     including a child process and `sync-notebooklm-books.nlm`, and it makes the
     suite behave the SAME on a host with the real binaries installed and on one
     without — the ambient-installation dependency was itself part of the defect.
  2. **the in-process seams** — `workbench._default_runner` (the one place `nlm`
     is spoken) and `session_pr.SubprocessCommandRunner.run` (the one place `gh`
     and the branch `git push` are spoken) are replaced by a refusal that RAISES.
     Layer 1 alone would be absorbed: a non-zero exit is precisely the
     degradation signal the adapter exists to swallow, so the escape would still
     pass silently.

`omp` HAS LAYER 1 ONLY, and that asymmetry is deliberate rather than an omission
(add-doxbench-distilled-abstract task 2.3). The in-process seam would be
`doxbench_bridge._spawn_child`, and poisoning it would also break the ONE thing
the bridge's own live smoke exists to do — run a real harness against a keyless
local provider, a module that skips cleanly everywhere else and that no gate may
require (`test_doxbench_bridge_live.py`). Layer 2 exists because a non-zero exit
is exactly the degradation signal the NOTEBOOK adapter swallows; the bridge
swallows nothing of the kind — a child that will not start surfaces as an
unavailable catalog and a raised dispatch — so layer 1 is not absorbed here the
way it was there. A test that must exercise a turn injects `spawn=`, which every
bridge test already does.

`HermeticityViolation` derives from `BaseException` DELIBERATELY. `except
Exception` is what `NotebookAdapter` and `branch_session.open_session_notebook`
use to turn a notebook failure into a notice, and a guard those clauses catch is
a guard that no-ops. A `BaseException` propagates through them to the test runner
as a failure, which is the entire point.

What this does NOT do: it never substitutes a working fake, and it never relaxes
`available()`. A test that legitimately exercises the adapter still INJECTS its
own double explicitly — `NotebookAdapter(runner=..., available=...)`,
`FakeNotebookAdapter`, a monkeypatched `cli._notebook_port`, `adapter_factory=`,
`GhPullRequests(runner=...)`, `FakePullRequests`. Only the DEFAULTS are poisoned,
so no existing assertion is weakened and no test needs editing to stay hermetic.

Registered from EVERY `conftest.py` under `tests/`. At this leg that is one
file, `tests/conftest.py`, because `tests/` is one flat directory here (see
`CONFTEST_HOOKUPS`). The rootdir is anchored at the repository by
`pyproject.toml` and its `[tool.pytest.ini_options]` table (openxFactory's copy
of this module anchors on its `pytest.ini`). A run started inside `tests/`
therefore still has the repository as its rootdir, and the repository-root
`conftest.py` stays in its conftest chain (see `ROOTDIR_ANCHOR`).

THE THIRD ROUTE IS NOT PYTEST AT ALL. A `python3 -m unittest discover` run
reaches no conftest at all, and a fixture cannot reach it. PR #49 review finding
17, residue 2, measured this reaching a real-binary stand-in twice with an empty
ledger, in codexFactory's `scripts/validate-docs.sh`, which ran the doc-health
and notebooklm suites when they lived in codexFactory — before the fix
(2026-07-27) replaced that bare fallback with codexFactory's own guarded
runner. openxFactory's `tests/hermetic_unittest.py` was later copied from that
runner, and it stayed in openxFactory at the carve, so THIS LEG HAS NO
UNITTEST RUNNER and no gate here takes that route. The two layers stay
installable WITHOUT pytest all the same — `install_binary_shim` and
`runner_seams`, which the fixtures below use — and `import pytest` stays
optional, because the world this module must also be able to guard is by
definition a world without pytest.

`tests/test_hermeticity.py` proves the guard at this leg: it asserts an
unguarded real-binary invocation is refused at both layers, pins the hookup set
and the rootdir anchor, and collects `tests` and `tests_runtime` in both
argument orders. Delete the guard or the anchor and those tests fail. The
proofs that drive openxFactory's own conftest-less directory and its unittest
runner live in openxFactory with the tree they test (plan 034 T035).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:            # pragma: no cover - the no-pytest fallback
    # The `unittest discover` world (the no-pytest route `tests/hermetic_unittest.py`
    # guards). Everything above the fixtures works there; the fixtures themselves
    # are pytest's own API and are simply not defined, which no caller in that
    # world asks for.
    pytest = None

TESTS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TESTS_ROOT.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# The binaries no test may reach. `nlm` is FR-043 itself; `gh` is the same class
# of escape on the pull-request port (FR-029/FR-034 — the invoking engineer's own
# ambient credential), and it is guarded now rather than after a test forgets.
# `omp` is the doxBench model harness (add-doxbench-distilled-abstract task 2.3),
# added when an entrypoint began DECLARING an `OmpHarnessBridge`: its child is a
# real `omp --mode rpc` process started through
# `doxbench_bridge._spawn_child`, and until now the only thing standing between
# a test and a real harness was the per-test discipline of passing `spawn=` —
# the same guarantee finding 17 proved worthless for `nlm`.
GUARDED_BINARIES = ("nlm", "gh", "omp")

# THE STAMP, and it is deliberately BINARY-NEUTRAL. This used to be
# `MARKER = "FR-043"` — the NotebookLM requirement — on every refusal, which was
# already loose for `gh` and would have made an `omp` refusal cite a requirement
# about NotebookLM notebooks. A refusal naming the WRONG requirement is worse
# than one naming none: it sends the reader to the wrong document. So the marker
# is now the guard's own identifier (still one fixed string every route can grep
# for, which is all any caller ever used it as), and the requirement each binary
# would actually break is named BESIDE it, per binary, by the table below.
MARKER = "XF-HERMETIC"

# What each guarded binary's refusal cites. Kept here rather than in the shim
# template so the PATH layer, the in-process layer and the `unittest` route all
# read one declaration.
GUARDED_BINARY_REQUIREMENTS = {
    "nlm": "FR-043 (tests MUST NOT create real NotebookLM notebooks)",
    "gh": "FR-029/FR-034 (no test may spend the engineer's own gh credential)",
    "omp": ("the doxBench provider boundary (no gate may require a real omp; "
            "inject the bridge's own spawn seam)"),
}

# The seam to inject INSTEAD, per binary: the refusal's job is not only to stop
# the escape but to say what the test should have done.
GUARDED_BINARY_SEAMS = {
    "nlm": "FakeNotebookAdapter, NotebookAdapter(runner=), cli._notebook_port, "
           "or serve adapter_factory=",
    "gh": "FakePullRequests, or GhPullRequests(runner=)",
    "omp": "OmpHarnessBridge(spawn=...), or a monkeypatched "
           "doxbench_bridge._spawn_child",
}


def requirement_for(binary: str) -> str:
    """The requirement `binary`'s refusal cites. An unlisted binary gets the
    guard's own general statement rather than somebody else's requirement id."""
    return GUARDED_BINARY_REQUIREMENTS.get(
        binary, "test hermeticity: no test may reach a real external binary")


def seam_for(binary: str) -> str:
    """What to inject instead of reaching `binary`."""
    return GUARDED_BINARY_SEAMS.get(
        binary, "the double at that port's own injection seam")


REFUSAL_EXIT_CODE = 97


# ---------------------------------------------------------------------------
# THE AMBIENT `conftest` SLOT (issue #305). Repairs the hazard the block below
# documents, without adding a module name or a pytest.ini option.
# ---------------------------------------------------------------------------

# The hook names `claim_conftest_slot` writes into a conftest's namespace, pinned
# by test_hermeticity: no directory conftest may define one of its own, because a
# plain assignment either way round silently drops one of the two.
HOOKS_INSTALLED_BY_THE_CLAIM = ("pytest_collectstart", "pytest_runtest_setup")


def claim_conftest_slot(namespace: dict) -> dict:
    """Make the calling conftest.py the `sys.modules["conftest"]` occupant for
    its OWN subtree, so multi-directory invocations stop being order-dependent.

    Call it at the bottom of a ROOTLESS directory conftest — one whose directory
    has no `__init__.py` — as `claim_conftest_slot(globals())`.

    THE HAZARD. `conftest` is an ambient top-level module name with exactly one
    `sys.modules` entry, and `_importconftest` DELETES that entry before
    importing each rootless conftest.py (`_pytest/config/__init__.py:753`), so
    whichever loaded last owns it. Ordinary collection hides this: directory
    conftests load lazily as traversal reaches them, so each directory's test
    modules are imported while their own conftest still holds the slot. Several
    path ARGUMENTS break exactly that, because `_set_initial_conftests` loads
    every argument's conftest BEFORE collection begins
    (`_pytest/config/__init__.py:615`) — so the LAST argument's conftest is what
    the first argument's `from conftest import AS_OF, FakeGit, ...` sites read.
    Measured at f9457d6f, the base this repair was written against:
    `pytest tests/doc-health tests/avatar_runtime --collect-only` collected 184
    with 27 collection errors, while the same two arguments swapped collected 993
    clean. The absolute counts move with every test added — the point they pin is
    the DIFFERENCE between two argument orders, which is now zero; the behavioural
    pin re-measures it on the live tree rather than trusting these numerals.

    THE REPAIR, and why it is exactly these two hooks. Both are dispatched
    through the node's `ihook` — an `FSHookProxy` that subtracts the conftest
    plugins not in scope for that node's path (`_pytest/main.py:731`) — so the
    copy installed here fires ONLY for nodes under this conftest's own directory
    and can never reach a sibling's:

      * `pytest_collectstart` runs immediately before a collector's `collect()`
        (`_pytest/runner.py:588`), which for a `Module` is where the test module
        is imported. That is the collection-time leg.
      * `pytest_runtest_setup` runs before each test body
        (`_pytest/runner.py:241`). That is the run-time leg, for the seven
        sites that do `from conftest import ...` INSIDE a test function. Under a
        plain `pytest tests/` those read whichever conftest was collected LAST —
        `tests/ideation-dashboard/`'s, alphabetically — and they are harmless
        today only by luck: the four in that directory happen to be asking for
        the module that already holds the slot, and the three in
        `tests/doc-health/` ask for `REPO_ROOT`, which both conftests define
        identically. This hook stops it being luck.

    THE ONE PLACE NOT TO CALL IT is `tests/conftest.py`. pluggy calls hook
    implementations in LIFO registration order, and the suite-wide conftest
    registers BEFORE every directory one, so its claim would run LAST and undo
    theirs (measured on a scratch tree: the green two-directory run goes
    straight back to two collection errors). A conftest whose directory has an
    `__init__.py` needs nothing either — pytest imports it as
    `<package>.conftest`, and it never touches the flat slot. That, and NOT the
    module's `__name__`, is what the refusal below keys on: under
    `--import-mode=importlib` (or `consider_namespace_packages=true`, both
    reachable through `PYTEST_ADDOPTS`) pytest gives a ROOTLESS conftest a dotted
    name like `tests.doc-health.conftest` too, and refusing on the name there
    would raise inside conftest collection — aborting the whole run with rc=4 and
    the FR-043 guard never registered, over a shape that merely wants the hooks
    installed harmlessly.

    IT RETURNS THE TWO HOOKS, and refuses if either name is already bound in the
    namespace. The install is a plain assignment into `globals()`, so a conftest
    that defines its OWN `pytest_collectstart` or `pytest_runtest_setup` — before
    or after the call — silently defeats the claim, and pytest reports nothing.
    A conftest that needs its own must call ours from inside it:

        _slot = claim_conftest_slot(globals())

        def pytest_collectstart(collector):
            _slot["pytest_collectstart"](collector)
            ...                     # whatever else this directory needs
    """
    directory = Path(namespace["__file__"]).resolve().parent
    if (directory / "__init__.py").is_file():
        raise RuntimeError(
            "claim_conftest_slot is for a ROOTLESS conftest.py — one whose "
            f"directory has no __init__.py. {directory} is a package, so pytest "
            "imports its conftest as `<package>.conftest` and it never contends "
            "for the flat `conftest` slot")
    already = sorted(name for name in HOOKS_INSTALLED_BY_THE_CLAIM
                     if name in namespace)
    if already:
        raise RuntimeError(
            f"{directory.name}/conftest.py already defines {', '.join(already)}; "
            "installing the slot claim over it would silently drop that hook, and "
            "defining it after the call would silently drop the claim. Call the "
            "returned function from inside your own implementation instead — see "
            "claim_conftest_slot's docstring")
    module = sys.modules[namespace["__name__"]]

    def pytest_collectstart(collector) -> None:
        sys.modules["conftest"] = module

    def pytest_runtest_setup(item) -> None:
        sys.modules["conftest"] = module

    hooks = {"pytest_collectstart": pytest_collectstart,
             "pytest_runtest_setup": pytest_runtest_setup}
    namespace.update(hooks)
    return hooks


# The hookups this guard must be registered from (pinned by test_hermeticity):
# EVERY conftest.py under tests/, so no directory is guarded only by luck.
#
# AT THIS LEG THAT IS ONE FILE (plan 034 T035), and the rest of this block is
# openxFactory's history, carried with the module. `tests/` is one flat
# directory here, and its `conftest.py` is the replica of openxFactory's
# `tests/ideation-dashboard/conftest.py`: a DIRECTORY conftest, so it registers
# the guard AND claims the ambient `conftest` slot. The suite-wide conftest at
# this leg is the repository-root `conftest.py`, above `tests/`. It registers
# nothing here and must not claim, for the LIFO reason `claim_conftest_slot`'s
# docstring gives for openxFactory's `tests/conftest.py`.
# `tests_runtime/conftest.py` is not under `tests/` and does not register the
# guard.
#
# Not one per directory, deliberately. `conftest` is an ambient top-level module
# name and pytest keeps exactly one of them in `sys.modules`, so ADDING an
# UNCLAIMING conftest.py to a directory hijacks that name for its siblings: a
# `tests/notebooklm/conftest.py` sorted after `tests/doc-health/` broke all 18
# doc-health modules' `from conftest import FakeGit` in codexFactory's
# `scripts/validate-docs.sh` (measured), which ran these tests when they lived
# in codexFactory before the doc-health relocation (adopt-neutral-tooling-home,
# 2026-08-03). Directories without a conftest are therefore guarded through
# `tests/conftest.py`, which covers every invocation whose CONFTEST CHAIN reaches
# `tests/`.
#
# WAVE 2 CLOSED THE HOLE THAT LEFT, without adding a module name: the repo-root
# `pytest.ini` anchors `rootdir` (and therefore `confcutdir`) at the repository, so
# `tests/conftest.py` is in the chain even for a run started INSIDE a conftest-less
# directory — which used to be completely unguarded (`which nlm` resolving to a
# real-binary stand-in, three invocations landed, ledger empty; measured in
# `tests/notebooklm/` and `tests/merge-master/`). See `pytest.ini` for why an
# inifile is the right instrument and a per-directory conftest is not.
#
# THE HIJACK ITSELF NOW HAS A REPAIR (issue #305, 2026-08-26). Every DIRECTORY
# conftest listed here calls `claim_conftest_slot(globals())` — defined above —
# which re-claims `sys.modules["conftest"]` for its subtree from two path-scoped
# hooks, so a directory's test modules import THEIR conftest whatever order the
# arguments arrive in: at f9457d6f `pytest tests/doc-health tests/avatar_runtime`
# went from 184 collected / 27 collection errors to 993 collected clean, matching
# the order that already worked (absolute counts drift with the tree; the invariant
# is that the two orders agree). That does not make adding a conftest.py free — a
# new one still has to be listed here AND carry the claim, both pinned by
# test_hermeticity — but a collision with the siblings is no longer its cost.
# `tests/conftest.py` is the one entry that must NOT claim (LIFO hook order
# would make its claim the last one to run); see the docstring above.
CONFTEST_HOOKUPS = ("conftest.py",)

# Conftests under `tests/` that exist but CANNOT register the guard themselves
# (adopt-neutral-tooling-home tranche B, 2026-08-03). The Hermes
# runtime-contracts suite's files are digest-indexed PostgreSQL conformance
# INPUTS: `validate-hermes-runtime-contracts.py` pins their result-source
# identity (HGR-FIXTURE-DATABASE-RESULT-SOURCE) and collects the suite inside
# a repository snapshot that carries no `tests/hermeticity.py`, so adding the
# guard import both invalidates the pinned evidence and breaks snapshot
# collection (measured, 2026-08-03). Those directories are still guarded
# through `tests/conftest.py` whenever the conftest chain reaches `tests/`,
# which the `pytest.ini` rootdir anchor guarantees for in-repo invocations.
#
# This leg carries no such suite, so nothing is exempt (plan 034 T035).
CONFTEST_EXEMPT_HOOKUPS: tuple[str, ...] = ()

# The rootdir anchor's filename, pinned by test_hermeticity: without an inifile
# somewhere at or above the invocation, rootdir falls back to the arguments' common
# ancestor and the hookup above goes out of scope.
#
# At this leg the anchor is `pyproject.toml` (plan 034 T035), and its
# `[tool.pytest.ini_options]` table is what makes it a firm one. With the table,
# pytest's upward search takes this file as the configfile as soon as it reaches
# it. Without the table, pytest 8 still falls back to it, but only when it finds
# no other configuration file anywhere above, so a `pytest.ini` in an enclosing
# directory would take the rootdir away. The anchor's test checks the table as
# well. With no anchor at all, a run started inside `tests/` makes `tests/` the
# rootdir, and the repository-root `conftest.py` (the `src/` path and the
# suite's host profile) falls out of its chain.
ROOTDIR_ANCHOR = "pyproject.toml"

# Both layers APPEND every refusal here, so a run leaves a complete inventory of
# what tried to escape and which test tried it — the measurement the review had to
# build a private shim for. A refusal is never silent; this makes it durable too.
REFUSAL_LOG_ENV = "XF_HERMETIC_REFUSAL_LOG"

_SHIM_TEMPLATE = """#!/bin/sh
if [ -n "${{{log_env}:-}}" ]; then
  echo "{name} $* :: ${{PYTEST_CURRENT_TEST:-<unknown>}}" >> "${{{log_env}}}"
fi
echo "{marker} test hermeticity: refusing to run the real '{name}' binary." >&2
echo "  offending test: ${{PYTEST_CURRENT_TEST:-<unknown: not under pytest>}}" >&2
echo "  refused argv:   {name} $*" >&2
echo "  requirement:    {requirement}" >&2
echo "  the suite is hermetic by construction (tests/hermeticity.py). Inject a" >&2
echo "  double at the seam instead: {seam}." >&2
exit {code}
"""


class HermeticityViolation(BaseException):
    """A test tried to reach a real external binary.

    A `BaseException` on purpose — see this module's docstring. Every production
    call site that speaks `nlm` catches `Exception` and DEGRADES, so a guard
    raising an ordinary exception would be swallowed and the escape would stay
    invisible.

    This docstring used to assert "nothing in `scripts/ideation_dashboard/` catches
    `BaseException` or uses a bare `except:` (checked)". That went STALE inside one
    day: later repair phases added two `except BaseException` handlers
    (`branch_session._commit_gate_action_locked`, `gate_routes._abandon_session`),
    and the PR #49 completeness critic caught the prose still claiming otherwise.
    Both RE-RAISE, so the guard does still reach the runner — but a comment cannot
    check that, and a future handler that swallowed instead would disable this whole
    mechanism with a green suite. It is a TEST now, not a claim:
    `test_hermeticity.py::test_no_production_handler_swallows_a_baseexception`
    parses the package and requires every `BaseException` handler to re-raise."""


def current_test() -> str:
    """The nodeid pytest is currently running, for the refusal message."""
    return os.environ.get("PYTEST_CURRENT_TEST", "<unknown: no PYTEST_CURRENT_TEST>")


def refusal_message(binary: str, args) -> str:
    return (f"{MARKER} test hermeticity: refusing to run the real '{binary}' "
            f"binary.\n  offending test: {current_test()}\n"
            f"  refused argv:   {binary} {' '.join(str(a) for a in args)}\n"
            f"  requirement:    {requirement_for(binary)}\n"
            "  the suite is hermetic by construction (tests/hermeticity.py). "
            f"Inject a double at the seam instead: {seam_for(binary)}.")


def refusal_log() -> Path | None:
    """Where refusals are recorded, when a session fixture has declared one."""
    declared = os.environ.get(REFUSAL_LOG_ENV)
    return Path(declared) if declared else None


def record_refusal(binary: str, args) -> None:
    """Append one refusal to the ledger. Best-effort by design: a ledger that
    cannot be written must never become the reason a refusal does not happen."""
    path = refusal_log()
    if path is None:
        return
    line = f"{binary} {' '.join(str(a) for a in args)} :: {current_test()}\n"
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def build_shim_dir(target: Path, names=GUARDED_BINARIES) -> Path:
    """Write executable refusals for `names` into `target` and return it."""
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        script = target / name
        script.write_text(
            _SHIM_TEMPLATE.format(marker=MARKER, name=name, code=REFUSAL_EXIT_CODE,
                                  log_env=REFUSAL_LOG_ENV,
                                  requirement=requirement_for(name),
                                  seam=seam_for(name)),
            encoding="utf-8")
        script.chmod(0o755)
    return target


def install_binary_shim(target: Path):
    """LAYER 1, installable without pytest: build the shim and put it FIRST on
    `PATH`, declaring the refusal ledger unless the environment already named one.

    Returns `(shim_dir, restore)` — `restore()` puts `PATH` and the ledger
    variable back, so the fixture below stays a fixture and the `unittest` runner
    can simply not call it (its process ends anyway)."""
    shim = build_shim_dir(Path(target))
    previous_path = os.environ.get("PATH", "")
    previous_log = os.environ.get(REFUSAL_LOG_ENV)
    os.environ["PATH"] = f"{shim}{os.pathsep}{previous_path}" if previous_path \
        else str(shim)
    if previous_log is None:
        os.environ[REFUSAL_LOG_ENV] = str(shim.parent / "refusals.log")

    def restore() -> None:
        os.environ["PATH"] = previous_path
        if previous_log is None:
            os.environ.pop(REFUSAL_LOG_ENV, None)

    return shim, restore


def runner_seams():
    """LAYER 2's targets, as ONE declaration: `(object, attribute, replacement)`.

    Both installers read this table — the fixture through `monkeypatch` (so it is
    undone per test) and `tests/hermetic_unittest.py` through `setattr` (no
    monkeypatch exists in that world) — so the two routes cannot guard different
    seams. Imported inside the function so the patch targets are the modules the
    tests themselves hold.

    AT THIS LEG BOTH SEAMS ARE `opendox`'s OWN, and they are imported with no
    probe (plan 034 T035). openxFactory's copy probes `ideation_dashboard.*`
    with `find_spec` and returns NO seams while that package is absent, a guard
    from before the package reached openxFactory (adopt-neutral-tooling-home
    tranche A). Carried here unchanged, the probe named a package this leg does
    not have, so it always answered "absent" and LAYER 2 WAS OFF in this suite:
    the carve manifest's row for this file records both reaches as resolving
    "to nothing at a destination that lacks them". Layer 1 was still on, and a
    non-zero exit is the very degradation the notebook adapter swallows, so an
    escape through the default runner would have passed. Turning the layer on
    here left the whole `tests/` directory green, so no test was escaping.
    Both modules belong to this leg, so a probe could only hide a breakage: a
    seam module that fails to import now fails every test, loudly, instead of
    switching the layer off in silence."""
    from opendox import session_pr as session_pr_mod
    from opendox import workbench as workbench_mod

    return (
        (workbench_mod, "_default_runner", refuse_nlm),
        (session_pr_mod.SubprocessCommandRunner, "run", refuse_command),
    )


def refuse_nlm(*args, **kwargs):
    """Stands in for `workbench._default_runner` — the ONE place `nlm` is run."""
    record_refusal("nlm", args)
    raise HermeticityViolation(refusal_message("nlm", args))


def refuse_command(self, *args, **kwargs):
    """Stands in for `session_pr.SubprocessCommandRunner.run` — the ONE place
    `gh` and the session branch's `git push` are run. Both are refused: a push
    to a real remote is the same escape as a `gh pr create`."""
    binary = str(args[0]) if args else "<command>"
    record_refusal(binary, args[1:])
    raise HermeticityViolation(refusal_message(binary, args[1:]))


@pytest.fixture(scope="session", autouse=True)
def hermetic_binary_path(tmp_path_factory):
    """Layer 1: the real `nlm`/`gh` are not on `PATH` for the whole session.

    Yields the shim directory so a test can assert `shutil.which` resolves into
    it rather than to `/usr/local/bin`. The installation itself is
    `install_binary_shim`, shared with the `unittest` runner so the two routes
    install the same layer 1."""
    shim, restore = install_binary_shim(tmp_path_factory.mktemp("hermetic-bin"))
    try:
        yield shim
    finally:
        restore()


@pytest.fixture(autouse=True)
def hermetic_external_runners(monkeypatch, hermetic_binary_path):
    """Layer 2: the in-process default runners RAISE instead of shelling out.

    The seams come from `runner_seams()` — one declaration, two installers — and
    are set with `raising=True` so a rename of either fails this fixture loudly
    rather than leaving the suite unguarded."""
    for target, attribute, replacement in runner_seams():
        monkeypatch.setattr(target, attribute, replacement, raising=True)
